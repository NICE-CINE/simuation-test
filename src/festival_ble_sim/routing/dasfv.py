from __future__ import annotations
import math
from typing import Dict, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_MULE_REPLICATED = "mule_replicated"
_FORWARD_REASON = "_forward_reason"
_PROPHET_AGING_UNIT_S = 30.0


class DasfVRouting(RoutingAlgorithm):
    # Single shared instance per run (see prophet.py's own note): every
    # decide() call, across every node, lands on this one object, so it can
    # observe the whole network's contact pattern tick by tick. That's what
    # lets density, the PRoPHET utility table, the 2-hop "who has recently
    # seen whom" check and the mule turnover heuristic work without any
    # beacon/bloom-filter wire format -- they're all read off the same
    # cross-node observation the engine already gives this object for free.
    def __init__(
        self,
        l_base: int = 8,
        k_min: int = 2,
        l_max: int = 32,
        d_ref: float = 20.0,
        delta: float = 0.1,
        p_encounter_init: float = 0.75,
        gamma: float = 0.98,
        beta: float = 0.25,
        enable_transitivity: bool = False,
        eps: float = 0.01,
        density_window_s: float = 10.0,
        two_hop_freshness_s: float = 5.0,
        window_rotation_s: float = 5.0,
        mule_turnover_threshold: float = 0.6,
        mule_min_contacts: int = 3,
        mule_min_speed_mps: float = 0.3,
        mule_min_battery_pct: float = 0.40,
        battery_low_pct: float = 0.15,
        battery_evac_pct: float = 0.30,
    ) -> None:
        if k_min < 1:
            raise ValueError("k_min must be >= 1")
        if l_max < k_min:
            raise ValueError("l_max must be >= k_min")
        if window_rotation_s <= 0:
            raise ValueError("window_rotation_s must be > 0")
        self._l_base = l_base
        self._k_min = k_min
        self._l_max = l_max
        self._d_ref = d_ref
        self._delta = delta
        self._p_encounter_init = p_encounter_init
        self._gamma = gamma
        self._beta = beta
        self._enable_transitivity = enable_transitivity
        self._eps = eps
        self._density_window_s = density_window_s
        self._two_hop_freshness_s = two_hop_freshness_s
        self._window_rotation_s = window_rotation_s
        self._mule_turnover_threshold = mule_turnover_threshold
        self._mule_min_contacts = mule_min_contacts
        self._mule_min_speed_mps = mule_min_speed_mps
        self._mule_min_battery_pct = mule_min_battery_pct
        self._battery_low_pct = battery_low_pct
        self._battery_evac_pct = battery_evac_pct

        # Nested by node id so one node's row is read without scanning every
        # pair in the run -- matters at the 10000-node scale this targets.
        self._predictability: Dict[int, Dict[int, float]] = {}
        # PRoPHET aging clock. Kept apart from _last_seen because a
        # transitive update refreshes it without any physical encounter.
        self._util_clock: Dict[int, Dict[int, float]] = {}
        # Physical sightings only: feeds local density and the 2-hop check.
        self._last_seen: Dict[int, Dict[int, float]] = {}
        # Turnover compares the two last *completed* windows: the window in
        # progress is nearly empty right after each rotation, and comparing
        # against it would flag almost every node as a mule every rotation.
        self._window_contacts: Dict[int, Set[int]] = {}
        self._prev_window_contacts: Dict[int, Set[int]] = {}
        self._prev2_window_contacts: Dict[int, Set[int]] = {}
        self._window_id: Optional[int] = None
        # Pedometer stand-in: without it a static node next to a passing
        # crowd (or a beacon) has high turnover and reads as a mule.
        self._motion_anchor: Dict[int, Tuple[float, float, float]] = {}
        self._speed: Dict[int, float] = {}
        # Network-wide ACK purge, modelled as instant/reliable propagation
        # (the spec's own ACK gossip is cheap/epidemic) rather than
        # simulating bloom-filter dissemination over BLE.
        self._delivered_ids: Set[int] = set()

    def _decayed(self, a: int, b: int, now: float) -> float:
        p = self._predictability.get(a, {}).get(b, 0.0)
        if p == 0.0:
            return 0.0
        last = self._util_clock[a][b]
        return p * (self._gamma ** (max(0.0, now - last) / _PROPHET_AGING_UNIT_S))

    def _set_utility(self, a: int, b: int, p: float, now: float) -> None:
        self._predictability.setdefault(a, {})[b] = p
        self._util_clock.setdefault(a, {})[b] = now

    def _maybe_rotate_window(self, now: float) -> None:
        window_id = int(now // self._window_rotation_s)
        if self._window_id is None:
            self._window_id = window_id
            return
        elapsed = window_id - self._window_id
        if elapsed <= 0:
            return
        if elapsed == 1:
            self._prev2_window_contacts = self._prev_window_contacts
            self._prev_window_contacts = self._window_contacts
        elif elapsed == 2:
            self._prev2_window_contacts = self._window_contacts
            self._prev_window_contacts = {}
        else:
            self._prev2_window_contacts = {}
            self._prev_window_contacts = {}
        self._window_contacts = {}
        self._window_id = window_id

    def _touch_encounter(self, a: int, b: int, now: float) -> bool:
        if self._last_seen.get(a, {}).get(b) == now:
            return False  # this pair was already recorded this tick
        for x, y in ((a, b), (b, a)):
            p_old = self._decayed(x, y, now)
            self._set_utility(x, y, p_old + (1 - p_old) * self._p_encounter_init, now)
            self._last_seen.setdefault(x, {})[y] = now
        if self._enable_transitivity:
            self._apply_transitivity(a, b, now)
        self._maybe_rotate_window(now)
        for x, y in ((a, b), (b, a)):
            self._window_contacts.setdefault(x, set()).add(y)
        return True

    def _apply_transitivity(self, a: int, b: int, now: float) -> None:
        p_ab = self._decayed(a, b, now)
        for src, via in ((a, b), (b, a)):
            for dst in list(self._predictability.get(via, {})):
                if dst in (a, b):
                    continue
                p_via_dst = self._decayed(via, dst, now)
                p_old = self._decayed(src, dst, now)
                self._set_utility(src, dst, p_old + (1 - p_old) * p_ab * p_via_dst * self._beta, now)

    def _observe_motion(self, node: "BaseNode", now: float) -> None:
        position = node.position
        anchor = self._motion_anchor.get(node.id)
        if anchor is None:
            self._motion_anchor[node.id] = (now, position.x, position.y)
            return
        t0, x0, y0 = anchor
        dt = now - t0
        if dt < self._window_rotation_s:
            return
        self._speed[node.id] = math.hypot(position.x - x0, position.y - y0) / dt
        self._motion_anchor[node.id] = (now, position.x, position.y)

    def _density(self, node_id: int, now: float) -> int:
        contacts = self._last_seen.get(node_id, {})
        return sum(1 for t in contacts.values() if now - t <= self._density_window_s)

    def _recently_seen(self, node_id: int, other_id: int, now: float) -> bool:
        t = self._last_seen.get(node_id, {}).get(other_id)
        return t is not None and (now - t) <= self._two_hop_freshness_s

    def _initial_tokens(self, density: int) -> int:
        raw = self._l_base * math.sqrt(self._d_ref / max(density, 1))
        return int(min(self._l_max, max(self._k_min, round(raw))))

    @staticmethod
    def _battery_pct(node: "BaseNode") -> float:
        initial = node.initial_battery_mah
        if initial == math.inf or initial <= 0:
            return 1.0
        return node.battery_mah / initial

    def _turnover(self, node_id: int) -> float:
        current = self._prev_window_contacts.get(node_id)
        previous = self._prev2_window_contacts.get(node_id)
        if not current or not previous:
            return 0.0
        union = current | previous
        if len(union) < self._mule_min_contacts:
            return 0.0
        return 1.0 - len(current & previous) / len(union)

    def _is_mule(self, node: "BaseNode") -> bool:
        if getattr(node, "is_beacon", False):
            return False
        return (
            self._speed.get(node.id, 0.0) >= self._mule_min_speed_mps
            and self._battery_pct(node) >= self._mule_min_battery_pct
            and self._turnover(node.id) >= self._mule_turnover_threshold
        )

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered_ids:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE

        # Recorded before the has_message check so that neighbours already
        # holding this message still count toward density and utility.
        if self._touch_encounter(holder.id, contact.id, now):
            self._observe_motion(holder, now)
            self._observe_motion(contact, now)

        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE

        tokens = message.routing_state.get(_TOKENS)
        if tokens is None:
            tokens = self._initial_tokens(self._density(holder.id, now))
            message.routing_state[_TOKENS] = tokens

        # The engine delivers to the destination itself before ever calling
        # decide(), so this never blocks a final-hop delivery.
        if self._battery_pct(contact) < self._battery_low_pct:
            return RoutingDecision.IGNORE

        dst = message.dst_id
        if self._recently_seen(contact.id, dst, now):
            message.routing_state[_FORWARD_REASON] = "two_hop"
            return RoutingDecision.FORWARD

        if tokens > 1:
            message.routing_state[_FORWARD_REASON] = "spray_mule" if self._is_mule(contact) else "spray"
            return RoutingDecision.FORWARD

        u_holder = self._decayed(holder.id, dst, now)
        u_contact = self._decayed(contact.id, dst, now)
        delta = 0.0 if self._battery_pct(holder) < self._battery_evac_pct else self._delta
        if u_contact > u_holder + delta:
            message.routing_state[_FORWARD_REASON] = "focus"
            return RoutingDecision.FORWARD

        if (
            u_holder < self._eps
            and not message.routing_state.get(_MULE_REPLICATED, False)
            and self._is_mule(contact)
        ):
            message.routing_state[_FORWARD_REASON] = "mule_replicate"
            return RoutingDecision.FORWARD

        return RoutingDecision.IGNORE

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        self._delivered_ids.add(message.msg_id)

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        reason = message.routing_state.pop(_FORWARD_REASON, "spray")
        forwarded_copy.routing_state.pop(_FORWARD_REASON, None)
        tokens = message.routing_state.get(_TOKENS, self._k_min)

        if reason == "mule_replicate":
            # Holder keeps its copy and its tokens, so the last copy is never
            # the one moved onto a (self-declared, unverifiable) mule.
            forwarded_copy.routing_state[_TOKENS] = 1
            forwarded_copy.routing_state[_MULE_REPLICATED] = True
            message.routing_state[_MULE_REPLICATED] = True
            return

        if reason == "two_hop":
            if tokens <= 1:
                forwarded_copy.routing_state[_TOKENS] = tokens
                holder.buffer.pop(message.msg_id, None)
            else:
                forwarded_copy.routing_state[_TOKENS] = 1
                message.routing_state[_TOKENS] = tokens - 1
            return

        if reason == "focus":
            forwarded_copy.routing_state[_TOKENS] = tokens
            holder.buffer.pop(message.msg_id, None)
            return

        # A mule gets a smaller share so one mule contact can't drain the budget.
        contact_share = max(1, tokens // 3) if reason == "spray_mule" else tokens // 2
        message.routing_state[_TOKENS] = tokens - contact_share
        forwarded_copy.routing_state[_TOKENS] = contact_share
