from __future__ import annotations
import math
from typing import Dict, List, NamedTuple, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message, Position
from .tide import TideRouting, _TOKENS

if TYPE_CHECKING:
    from ..nodes import BaseNode

_ZONE = "zone"


class _Hint(NamedTuple):
    position: Position
    age_s: float
    radius_m: float
    confidence: float


class TideGRouting(TideRouting):
    # TIDE-G: TIDE + the destination's own last position as a routing hint.
    # The hint is only what the engine puts in message.dst_position (the
    # destination's GPS from its last message delivered to the source):
    # relays never record where they met anyone. Relays and holders of a
    # hinted message take a GPS fix every gps_period_s; a node without a
    # fresh fix takes no part in the geographic rules. No usable hint, or
    # no fixes on both sides, reduces exactly to TIDE.
    def __init__(
        self,
        hint_max_age_s: float = 900.0,
        hint_tau_s: float = 600.0,
        hint_cell_m: float = 25.0,
        hint_r0_m: float = 30.0,
        drift_mps: float = 0.3,
        geo_lambda_m: float = 100.0,
        min_progress_m: float = 15.0,
        zone_tokens: int = 3,
        gps_period_s: float = 30.0,
        fix_max_age_s: float = 60.0,
        gps_current_ma: float = 10.0,
        gps_for_relays: bool = True,
        geo_focus: bool = True,
        geo_tokens: bool = True,
        zone_search: bool = True,
        refresh_hint: bool = True,
        **tide_kwargs,
    ) -> None:
        super().__init__(**tide_kwargs)
        if hint_max_age_s <= 0 or hint_tau_s <= 0 or geo_lambda_m <= 0 or gps_period_s <= 0:
            raise ValueError("hint_max_age_s, hint_tau_s, geo_lambda_m and gps_period_s must be > 0")
        if zone_tokens < 1:
            raise ValueError("zone_tokens must be >= 1")
        self._hint_max_age_s = hint_max_age_s
        self._hint_tau_s = hint_tau_s
        self._hint_cell_m = hint_cell_m
        self._hint_r0_m = hint_r0_m
        self._drift_mps = drift_mps
        self._geo_lambda_m = geo_lambda_m
        self._min_progress_m = min_progress_m
        self._zone_tokens = zone_tokens
        self._gps_period_s = gps_period_s
        self._fix_max_age_s = fix_max_age_s
        self._gps_current_ma = gps_current_ma
        self._gps_for_relays = gps_for_relays
        self._geo_focus = geo_focus
        self._geo_tokens = geo_tokens
        self._zone_search = zone_search
        self._refresh_hint = refresh_hint
        self._fixes: Dict[int, Tuple[Position, float]] = {}
        self._next_gps_round = 0.0
        self.hint_stats = {"routed": 0, "hinted": 0, "delivered": 0, "delivered_hinted": 0, "gps_fixes": 0}
        self._seen: Set[int] = set()

    # --- GPS fixes --------------------------------------------------------

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        super().on_tick(now, neighbors_by_node)
        if now < self._next_gps_round:
            return
        self._next_gps_round = now + self._gps_period_s
        fix_mah = self._gps_current_ma * self._gps_period_s / 3600.0
        for nid in neighbors_by_node:
            node = self._nodes.get(nid)
            if node is None or node.is_beacon:
                continue
            if self._needs_gps(node, now):
                self._fixes[nid] = (node.gps_position(), now)
                node.consume_energy(fix_mah)
                self.hint_stats["gps_fixes"] += 1

    def _needs_gps(self, node: "BaseNode", now: float) -> bool:
        if self._gps_for_relays and self._acts_as_relay(node, now):
            return True
        return any(self._hint(m, now) is not None for m in node.buffer.values())

    def _fix(self, node: "BaseNode", now: float) -> Optional[Position]:
        if node.is_beacon:
            return node.position
        fix = self._fixes.get(node.id)
        if fix is None or now - fix[1] > self._fix_max_age_s:
            return None
        return fix[0]

    # --- hint -------------------------------------------------------------

    def _hint(self, message: Message, now: float) -> Optional[_Hint]:
        if message.dst_position is None or message.dst_position_time is None:
            return None
        age = now - message.dst_position_time
        if age > self._hint_max_age_s:
            return None
        pos = message.dst_position
        if self._hint_cell_m > 0:
            c = self._hint_cell_m
            pos = Position((math.floor(pos.x / c) + 0.5) * c, (math.floor(pos.y / c) + 0.5) * c)
        return _Hint(pos, age, self._hint_r0_m + self._drift_mps * age, math.exp(-age / self._hint_tau_s))

    def _distance(self, node: "BaseNode", hint: _Hint, now: float) -> Optional[float]:
        pos = self._fix(node, now)
        return None if pos is None else pos.distance_to(hint.position)

    def _geo(self, d: float, hint: _Hint) -> float:
        return 1.0 / (1.0 + max(0.0, d - hint.radius_m) / self._geo_lambda_m)

    def _score(self, node: "BaseNode", message: Message, now: float) -> float:
        u = self._utility(node, message.dst_id, now)
        hint = self._hint(message, now)
        if hint is None:
            return u
        d = self._distance(node, hint, now)
        if d is None:
            return u
        return min(1.0, max(u, self._energy(node) * hint.confidence * self._geo(d, hint)))

    # --- TIDE extension points --------------------------------------------

    def _before_route(self, message: Message, holder: "BaseNode", now: float) -> None:
        state = message.routing_state
        if holder.id == message.src_id and message.msg_id not in self._seen:
            self._seen.add(message.msg_id)
            self.hint_stats["routed"] += 1
            if self._hint(message, now) is not None:
                self.hint_stats["hinted"] += 1
        if self._refresh_hint and holder.id == message.src_id:
            known = holder.known_positions.get(message.dst_id)
            if known is not None and (message.dst_position_time is None or known[1] > message.dst_position_time):
                message.dst_position, message.dst_position_time = known
        if not self._zone_search or state.get(_ZONE) or state.get(_TOKENS) != 1:
            return
        hint = self._hint(message, now)
        if hint is None:
            return
        d = self._distance(holder, hint, now)
        if d is not None and d <= hint.radius_m:
            state[_TOKENS] = self._zone_tokens
            state[_ZONE] = True

    def _spray_ok(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> bool:
        if not message.routing_state.get(_ZONE):
            return True
        hint = self._hint(message, now)
        if hint is None:
            return True
        d = self._distance(contact, hint, now)
        return d is not None and d <= hint.radius_m

    def _focus_ok(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> bool:
        if super()._focus_ok(message, holder, contact, now):
            return True
        if not self._geo_focus:
            return False
        hint = self._hint(message, now)
        if hint is None:
            return False
        d_a = self._distance(holder, hint, now)
        d_b = self._distance(contact, hint, now)
        if d_a is None or d_b is None or d_a <= hint.radius_m:
            return False
        # Never hand the copy to a node TIDE's own rule would hand it back from.
        u_a = self._utility(holder, message.dst_id, now)
        u_b = self._utility(contact, message.dst_id, now)
        return d_b <= d_a - self._min_progress_m and u_b >= u_a - self._delta

    def _token_share(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> float:
        if not self._geo_tokens:
            return super()._token_share(message, holder, contact, now)
        if not self._weighted_tokens:
            return 0.5
        s_a = self._score(holder, message, now)
        s_b = self._score(contact, message, now)
        return 0.5 if s_a + s_b == 0.0 else s_b / (s_a + s_b)

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        if message.msg_id not in self._delivered_ids:
            self.hint_stats["delivered"] += 1
            if self._hint(message, message.creation_time) is not None:
                self.hint_stats["delivered_hinted"] += 1
        super().on_delivered(message, holder)
