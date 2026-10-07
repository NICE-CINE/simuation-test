from __future__ import annotations
import math
from typing import Dict, List, NamedTuple, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message, Position
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_ESCALATION = "escalation"
_REASON = "_reason"
# Same short cold fix as TIDE-G2's message_fix_s, paid by a destination
# that has no fresh periodic fix when it builds the ACK.
_ACK_FIX_S = 5.0


class _Hint(NamedTuple):
    position: Position
    radius_m: float


class GeoSprayFocusRouting(RoutingAlgorithm):
    # GSF: Spray-and-Focus whose copy budget and relay choice follow the
    # destination's last known position (message.dst_position), falling back
    # to encounter-based Spray-and-Focus without a usable hint. The source
    # escalates an undelivered message: l_max tokens and no geography, then
    # flooding. One shared instance holds the encounter table, GPS fixes and
    # delivered set instead of simulating summary exchanges; ACKs purge
    # network-wide on the next tick (as dasfv/fresh_spray), only the ACK's
    # position travels back with a delay. Spec: docs/GSF.md.
    def __init__(
        self,
        hint_max_age_s: float = 900.0,
        hint_cell_m: float = 25.0,
        hint_r0_m: float = 30.0,
        drift_mps: float = 0.3,
        r_focus_m: float = 120.0,
        r_flood_m: float = 300.0,
        l_min: int = 2,
        l_max: int = 12,
        radius_tokens: bool = True,
        spray_slack_m: float = 50.0,
        min_progress_m: float = 15.0,
        min_freshness_gain_s: float = 30.0,
        island_delivery: bool = True,
        escalation_schedule_s: Optional[Tuple[float, float]] = (60.0, 180.0),
        gps_period_s: float = 30.0,
        fix_max_age_s: float = 60.0,
        gps_current_ma: float = 10.0,
        gps_policy: str = "all",
        ack_hint: bool = True,
        ack_hint_delay_factor: float = 1.0,
        refresh_hint: bool = True,
    ) -> None:
        if l_min < 1 or l_max < l_min:
            raise ValueError("need 1 <= l_min <= l_max")
        if hint_max_age_s <= 0 or r_focus_m <= 0 or gps_period_s <= 0:
            raise ValueError("hint_max_age_s, r_focus_m and gps_period_s must be > 0")
        if gps_policy not in ("all", "carriers"):
            raise ValueError("gps_policy must be 'all' or 'carriers'")
        if escalation_schedule_s is not None and not 0 < escalation_schedule_s[0] <= escalation_schedule_s[1]:
            raise ValueError("escalation_schedule_s must be None or 0 < first <= second")
        if ack_hint_delay_factor < 0:
            raise ValueError("ack_hint_delay_factor must be >= 0")
        self._hint_max_age_s = hint_max_age_s
        self._hint_cell_m = hint_cell_m
        self._hint_r0_m = hint_r0_m
        self._drift_mps = drift_mps
        self._r_focus_m = r_focus_m
        self._r_flood_m = r_flood_m
        self._l_min = l_min
        self._l_max = l_max
        self._radius_tokens = radius_tokens
        self._spray_slack_m = spray_slack_m
        self._min_progress_m = min_progress_m
        self._min_gain_s = min_freshness_gain_s
        self._island_delivery = island_delivery
        self._escalation = escalation_schedule_s
        self._gps_period_s = gps_period_s
        self._fix_max_age_s = fix_max_age_s
        self._gps_current_ma = gps_current_ma
        self._gps_policy = gps_policy
        self._ack_hint = ack_hint
        self._ack_hint_delay_factor = ack_hint_delay_factor
        self._refresh_hint = refresh_hint

        self._nodes: Dict[int, "BaseNode"] = {}
        self._neighbor_ids: Dict[int, Set[int]] = {}
        self._last_met: Dict[int, Dict[int, float]] = {}
        self._fixes: Dict[int, Tuple[Position, float]] = {}
        self._next_gps_round = 0.0
        self._delivered: Set[int] = set()
        self._to_purge: Set[int] = set()
        # (available_at, src_id, dst_id, dst position, fix time)
        self._pending_ack_hints: List[Tuple[float, int, int, Position, float]] = []
        self._prev_tick: Optional[float] = None
        self._seen: Set[int] = set()
        self.stats = {
            "routed": 0, "hinted": 0, "spray": 0, "focus_geo": 0, "focus_encounter": 0, "island": 0,
            "flood": 0, "escalations": 0, "gps_fixes": 0, "ack_hints": 0,
        }

    # --- hooks ------------------------------------------------------------

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._prev_tick = now
        self._neighbor_ids = {nid: {n.id for n in ns} for nid, ns in neighbors_by_node.items()}
        for nid, ns in neighbors_by_node.items():
            met = self._last_met.setdefault(nid, {})
            for n in ns:
                met[n.id] = now
        if self._to_purge:
            # Only newly delivered ids: decide() drops any copy missed here.
            for nid in neighbors_by_node:
                node = self._nodes.get(nid)
                if node is not None and node.buffer:
                    for mid in [mid for mid in node.buffer if mid in self._to_purge]:
                        del node.buffer[mid]
            self._to_purge.clear()
        self._flush_ack_hints(now)
        if now < self._next_gps_round:
            return
        self._next_gps_round = now + self._gps_period_s
        fix_mah = self._gps_current_ma * self._gps_period_s / 3600.0
        for nid, ns in neighbors_by_node.items():
            node = self._nodes.get(nid)
            if node is None or node.is_beacon or not self._needs_gps(node, ns, now):
                continue
            fix = node.gps_fix()
            if fix is not None:
                self._fixes[nid] = (fix, now)
            node.consume_energy(fix_mah)
            self.stats["gps_fixes"] += 1

    def _needs_gps(self, node: "BaseNode", neighbors: List["BaseNode"], now: float) -> bool:
        if self._gps_policy == "all":
            return bool(neighbors)
        return any(self._geo_hint(m, now) is not None for m in node.buffer.values())

    # --- geography --------------------------------------------------------

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
        return _Hint(pos, self._hint_r0_m + self._drift_mps * age)

    def _geo_hint(self, message: Message, now: float) -> Optional[_Hint]:
        hint = self._hint(message, now)
        if hint is None or hint.radius_m > self._r_flood_m or message.routing_state.get(_ESCALATION, 0) > 0:
            return None
        return hint

    def _fix(self, node: "BaseNode", now: float) -> Optional[Position]:
        if node.is_beacon:
            return node.position
        fix = self._fixes.get(node.id)
        if fix is None or now - fix[1] > self._fix_max_age_s:
            return None
        return fix[0]

    def _distance(self, node: "BaseNode", hint: _Hint, now: float) -> Optional[float]:
        pos = self._fix(node, now)
        return None if pos is None else pos.distance_to(hint.position)

    def _met(self, node_id: int, dst_id: int) -> float:
        return self._last_met.get(node_id, {}).get(dst_id, -math.inf)

    # --- routing ----------------------------------------------------------

    def _initial_tokens(self, message: Message, now: float) -> int:
        hint = self._hint(message, now)
        if not self._radius_tokens or hint is None or hint.radius_m > self._r_flood_m:
            return self._l_max
        raw = math.ceil(self._l_max * (hint.radius_m / self._r_focus_m) ** 2)
        return int(min(self._l_max, max(self._l_min, raw)))

    def _prepare(self, message: Message, holder: "BaseNode", now: float) -> None:
        state = message.routing_state
        is_source = holder.id == message.src_id
        if is_source and self._refresh_hint:
            known = holder.known_positions.get(message.dst_id)
            if known is not None and (message.dst_position_time is None or known[1] > message.dst_position_time):
                message.dst_position, message.dst_position_time = known
        if _TOKENS not in state:
            state[_TOKENS] = self._initial_tokens(message, now)
            state[_ESCALATION] = 0
        if not is_source:
            return
        if message.msg_id not in self._seen:
            self._seen.add(message.msg_id)
            self.stats["routed"] += 1
            if self._hint(message, now) is not None:
                self.stats["hinted"] += 1
        if self._escalation is None:
            return
        age = now - message.creation_time
        level = 2 if age >= self._escalation[1] else 1 if age >= self._escalation[0] else 0
        if level > state[_ESCALATION]:
            self.stats["escalations"] += level - state[_ESCALATION]
            state[_ESCALATION] = level
            state[_TOKENS] = max(state[_TOKENS], self._l_max)

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        self._prepare(message, holder, now)
        reason = self._reason(message, holder, contact, now)
        if reason is None:
            return RoutingDecision.IGNORE
        message.routing_state[_REASON] = reason
        return RoutingDecision.FORWARD

    def _reason(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> Optional[str]:
        state = message.routing_state
        dst = message.dst_id
        if self._island_delivery and dst in self._neighbor_ids.get(contact.id, ()):
            return "island"
        if state[_ESCALATION] >= 2:
            return "flood"
        hint = self._geo_hint(message, now)
        d_a = self._distance(holder, hint, now) if hint is not None else None
        d_b = self._distance(contact, hint, now) if hint is not None else None

        if state[_TOKENS] > 1:
            # Oriented spray: a contact clearly farther from the hint than the
            # holder gets nothing; without fixes on both sides, plain spray.
            if d_a is not None and d_b is not None and d_b > d_a + self._spray_slack_m:
                return None
            return "spray"
        if state[_TOKENS] < 1:
            return None
        if d_a is not None and d_b is not None and d_a > hint.radius_m:
            return "focus_geo" if d_b <= d_a - self._min_progress_m else None
        if self._met(contact.id, dst) > self._met(holder.id, dst) + self._min_gain_s:
            return "focus_encounter"
        return None

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        reason = message.routing_state.pop(_REASON, "spray")
        forwarded_copy.routing_state.pop(_REASON, None)
        self.stats[reason] += 1
        if reason == "island":
            forwarded_copy.routing_state[_TOKENS] = 0
        elif reason == "flood":
            forwarded_copy.routing_state[_TOKENS] = 1
        elif reason == "spray":
            tokens = message.routing_state[_TOKENS]
            message.routing_state[_TOKENS] = tokens - tokens // 2
            forwarded_copy.routing_state[_TOKENS] = tokens // 2
        else:
            forwarded_copy.routing_state[_TOKENS] = 1
            if holder.id == message.src_id:
                message.routing_state[_TOKENS] = 0  # shadow copy, kept for escalation
            else:
                holder.buffer.pop(message.msg_id, None)

    # --- ACK --------------------------------------------------------------

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        if message.msg_id in self._delivered:
            return
        self._delivered.add(message.msg_id)
        self._to_purge.add(message.msg_id)
        if self._ack_hint:
            # No `now` in this hook: on_tick stamps _prev_tick before any contact.
            now = self._prev_tick if self._prev_tick is not None else message.creation_time
            self._queue_ack_hint(message, now)

    def _queue_ack_hint(self, message: Message, now: float) -> None:
        dst = self._nodes.get(message.dst_id)
        if dst is None:
            return
        if dst.is_beacon:
            fix: Optional[Tuple[Position, float]] = (dst.position, now)
        else:
            fix = self._fixes.get(dst.id)
            if fix is None or now - fix[1] > self._fix_max_age_s:
                pos = dst.gps_fix()
                dst.consume_energy(self._gps_current_ma * _ACK_FIX_S / 3600.0)
                self.stats["gps_fixes"] += 1
                fix = None if pos is None else (pos, now)
                if fix is not None:
                    self._fixes[dst.id] = fix
        if fix is None:
            return
        available_at = now + self._ack_hint_delay_factor * max(0.0, now - message.creation_time)
        self._pending_ack_hints.append((available_at, message.src_id, message.dst_id, fix[0], fix[1]))

    def _flush_ack_hints(self, now: float) -> None:
        if not self._pending_ack_hints:
            return
        pending = []
        for item in self._pending_ack_hints:
            available_at, src_id, dst_id, pos, fix_time = item
            if available_at > now:
                pending.append(item)
                continue
            src = self._nodes.get(src_id)
            if src is not None and src.is_active:
                # Engine-owned table on purpose: it fills the next message's
                # dst_position, exactly as a reply would.
                src.record_known_position(dst_id, pos, fix_time)
                self.stats["ack_hints"] += 1
        self._pending_ack_hints = pending

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        best_id = None
        best_key = None
        for mid, m in node.buffer.items():
            if m.src_id == node.id:
                continue  # never evict own messages
            key = (mid not in self._delivered, not m.is_expired(now), m.routing_state.get(_TOKENS, 1), -m.hops)
            if best_key is None or key < best_key:
                best_id, best_key = mid, key
        return best_id
