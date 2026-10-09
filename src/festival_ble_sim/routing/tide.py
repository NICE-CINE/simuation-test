from __future__ import annotations
import math
import random
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_L0 = "l0"
_REINJECTIONS = "reinjections"
_FORWARD_REASON = "_forward_reason"
_PROPHET_AGING_UNIT_S = 30.0


class TideRouting(RoutingAlgorithm):
    # TIDE (Tokens, Islands, Density, Energy), reduced to the network level
    # like dasfv.py: one shared instance reads every node's neighbourhood off
    # on_tick, so the 2-hop view, density, neighbours' energy and the
    # encounter table need no advertisement/GATT wire format. ACKs purge
    # network-wide instantly (same as dasfv). Not modelled: crypto,
    # ephemeral IDs, buffer digests, advertising interval / scan duty cycle
    # (no discovery energy in the engine), clock skew (age = now - creation),
    # per-sender buffer quota, reputation and "late first" transmit order
    # (the engine owns send order).
    def __init__(
        self,
        w: float = 0.5,
        tau_s: float = 1200.0,
        p_encounter_init: float = 0.75,
        beta: float = 0.25,
        gamma: float = 0.98,
        enable_transitivity: bool = False,
        rho_target: float = 15.0,
        rho_ref: float = 10.0,
        l_max: int = 16,
        l_min: int = 2,
        delta: float = 0.05,
        election_period_s: float = 300.0,
        member_fallback_s: float = 30.0,
        leaf_battery_pct: float = 0.15,
        max_syncs_per_minute: Optional[int] = 5,
        late_after_s: float = 600.0,
        reinjection_schedule_s: Tuple[float, float, float] = (180.0, 360.0, 1200.0),
        density_ewma_alpha: float = 0.1,
        islands: bool = True,
        weighted_tokens: bool = True,
        election: bool = True,
        reinjection: bool = True,
        energy_factor: bool = True,
        seed: Optional[int] = 0,
    ) -> None:
        if not 0.0 <= w <= 1.0:
            raise ValueError("w must be in [0, 1]")
        if l_min < 1 or l_max < l_min:
            raise ValueError("need 1 <= l_min <= l_max")
        if tau_s <= 0 or rho_target <= 0 or rho_ref <= 0:
            raise ValueError("tau_s, rho_target and rho_ref must be > 0")
        self._w = w
        self._tau_s = tau_s
        self._p_init = p_encounter_init
        self._beta = beta
        self._gamma = gamma
        self._enable_transitivity = enable_transitivity
        self._rho_target = rho_target
        self._rho_ref = rho_ref
        self._l_max = l_max
        self._l_min = l_min
        self._delta = delta
        self._election_period_s = election_period_s
        self._member_fallback_s = member_fallback_s
        self._leaf_battery_pct = leaf_battery_pct
        self._max_syncs = max_syncs_per_minute
        self._late_after_s = late_after_s
        # Cumulative multipliers of L0 per reinjection step (L0/2, L0, L0/2).
        self._reinjection_schedule = list(zip(reinjection_schedule_s, (0.5, 1.0, 0.5)))
        self._alpha = density_ewma_alpha
        # Ablation switches (spec's "études d'ablation" table).
        self._islands = islands
        self._weighted_tokens = weighted_tokens
        self._election = election
        self._reinjection = reinjection
        self._energy_factor_on = energy_factor
        self._rng = random.Random(seed)

        self._nodes: Dict[int, "BaseNode"] = {}
        self._predictability: Dict[int, Dict[int, float]] = {}
        self._util_clock: Dict[int, Dict[int, float]] = {}
        self._last_met: Dict[int, Dict[int, float]] = {}
        self._neighbor_ids: Dict[int, Set[int]] = {}
        self._prev_tick: Optional[float] = None
        self._density: Dict[int, float] = {}
        self._is_relay: Dict[int, bool] = {}
        self._next_election: Dict[int, float] = {}
        self._last_relay_seen: Dict[int, float] = {}
        # holder -> [window start, peers synced in this window]
        self._syncs: Dict[int, List] = {}
        self._delivered_ids: Set[int] = set()
        self._now = 0.0

    # --- node state -------------------------------------------------------

    @staticmethod
    def _battery_pct(node: "BaseNode") -> float:
        initial = node.initial_battery_mah
        if initial == math.inf or initial <= 0:
            return 1.0
        return node.battery_mah / initial

    def _energy(self, node: "BaseNode") -> float:
        if not self._energy_factor_on:
            return 1.0
        b = self._battery_pct(node)
        if b >= 0.5:
            return 1.0
        if b <= 0.2:
            return 0.2
        return 0.2 + 0.8 * (b - 0.2) / 0.3

    def _is_leaf(self, node: "BaseNode") -> bool:
        return not node.is_beacon and self._battery_pct(node) < self._leaf_battery_pct

    def _acts_as_relay(self, node: "BaseNode", now: float) -> bool:
        if node.is_beacon or not self._election:
            return True
        if self._is_leaf(node):
            return False
        if self._is_relay.get(node.id, False):
            return True
        return now - self._last_relay_seen.get(node.id, -math.inf) > self._member_fallback_s

    # --- encounter table (PRoPHET + freshness) ----------------------------

    def _decayed(self, a: int, b: int, now: float) -> float:
        p = self._predictability.get(a, {}).get(b, 0.0)
        if p == 0.0:
            return 0.0
        return p * (self._gamma ** (max(0.0, now - self._util_clock[a][b]) / _PROPHET_AGING_UNIT_S))

    def _set_p(self, a: int, b: int, p: float, now: float) -> None:
        self._predictability.setdefault(a, {})[b] = p
        self._util_clock.setdefault(a, {})[b] = now

    def _encounter(self, a: int, b: int, now: float) -> None:
        p_old = self._decayed(a, b, now)
        self._set_p(a, b, p_old + (1 - p_old) * self._p_init, now)
        if self._enable_transitivity:
            p_ab = self._decayed(a, b, now)
            for dst in list(self._predictability.get(b, {})):
                if dst == a:
                    continue
                p_old = self._decayed(a, dst, now)
                self._set_p(a, dst, p_old + (1 - p_old) * p_ab * self._decayed(b, dst, now) * self._beta, now)

    def _utility(self, node: "BaseNode", dst: int, now: float) -> float:
        met = self._last_met.get(node.id, {}).get(dst)
        freshness = 0.0 if met is None else math.exp(-(now - met) / self._tau_s)
        u = self._w * self._decayed(node.id, dst, now) + (1 - self._w) * freshness
        return min(1.0, self._energy(node) * u)

    # --- hooks ------------------------------------------------------------

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        prev = self._prev_tick
        self._neighbor_ids = {nid: {n.id for n in ns} for nid, ns in neighbors_by_node.items()}
        for nid, ns in neighbors_by_node.items():
            met = self._last_met.setdefault(nid, {})
            for n in ns:
                # A contact spanning several ticks is one PRoPHET encounter.
                if met.get(n.id) != prev:
                    self._encounter(nid, n.id, now)
                met[n.id] = now
            rho = self._density.get(nid)
            self._density[nid] = len(ns) if rho is None else (1 - self._alpha) * rho + self._alpha * len(ns)
        self._prev_tick = now

        for nid, ns in neighbors_by_node.items():
            node = self._nodes.get(nid)
            if node is None:
                continue
            if now >= self._next_election.get(nid, 0.0):
                self._elect(node, ns, now)
            if any(self._is_relay.get(n.id, False) or n.is_beacon for n in ns):
                self._last_relay_seen[nid] = now

    def _elect(self, node: "BaseNode", neighbors: List["BaseNode"], now: float) -> None:
        self._next_election[node.id] = now + self._election_period_s
        if self._is_leaf(node):
            self._is_relay[node.id] = False
            return
        # An outgoing relay keeps the role while it still carries others' messages.
        if self._is_relay.get(node.id) and any(m.src_id != node.id for m in node.buffer.values()):
            return
        rho = self._density.get(node.id, 0.0)
        e = self._energy(node)
        e_bar = sum(self._energy(n) for n in neighbors) / len(neighbors) if neighbors else e
        p = 1.0 if rho <= self._rho_target else min(1.0, self._rho_target / rho * e / e_bar)
        self._is_relay[node.id] = self._rng.random() < p

    def _initial_tokens(self, holder_id: int) -> int:
        rho = max(self._density.get(holder_id, 0.0), 1e-9)
        raw = round(self._l_max * math.sqrt(self._rho_ref / rho))
        return int(min(self._l_max, max(self._l_min, raw)))

    def _sync_allowed(self, holder_id: int, contact_id: int, now: float) -> bool:
        if self._max_syncs is None:
            return True
        window = self._syncs.get(holder_id)
        if window is None or now - window[0] >= 60.0:
            window = self._syncs[holder_id] = [now, set()]
        return contact_id in window[1] or len(window[1]) < self._max_syncs

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if message.msg_id in self._delivered_ids:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE

        state = message.routing_state
        if _TOKENS not in state:
            state[_L0] = self._initial_tokens(holder.id)
            state[_TOKENS] = state[_L0]
            state[_REINJECTIONS] = 0
        if self._reinjection and holder.id == message.src_id:
            self._maybe_reinject(message, now)
        self._before_route(message, holder, now)

        if not self._sync_allowed(holder.id, contact.id, now):
            return RoutingDecision.IGNORE

        # Islands: any neighbour (member or relay) that sees the destination
        # right now gets a copy it can deliver next tick.
        if self._islands and message.dst_id in self._neighbor_ids.get(contact.id, ()):
            state[_FORWARD_REASON] = "island"
            return RoutingDecision.FORWARD

        if not self._acts_as_relay(contact, now):
            return RoutingDecision.IGNORE

        tokens = state[_TOKENS]
        if tokens > 1:
            if not self._spray_ok(message, holder, contact, now):
                return RoutingDecision.IGNORE
            state[_FORWARD_REASON] = "spray"
            return RoutingDecision.FORWARD
        if tokens == 1 and self._focus_ok(message, holder, contact, now):
            state[_FORWARD_REASON] = "focus"
            return RoutingDecision.FORWARD
        return RoutingDecision.IGNORE

    # Extension points, overridden by TIDE-G (tide_g.py).

    def _before_route(self, message: Message, holder: "BaseNode", now: float) -> None:
        pass

    def _spray_ok(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> bool:
        return True

    def _focus_ok(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> bool:
        u_holder = self._utility(holder, message.dst_id, now)
        u_contact = self._utility(contact, message.dst_id, now)
        return u_contact > u_holder + self._delta

    def _token_share(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> float:
        if not self._weighted_tokens:
            return 0.5
        u_a = self._utility(holder, message.dst_id, now)
        u_b = self._utility(contact, message.dst_id, now)
        return 0.5 if u_a + u_b == 0.0 else u_b / (u_a + u_b)

    def _maybe_reinject(self, message: Message, now: float) -> None:
        state = message.routing_state
        age = now - message.creation_time
        while state[_REINJECTIONS] < len(self._reinjection_schedule):
            at_s, share = self._reinjection_schedule[state[_REINJECTIONS]]
            if age < at_s:
                return
            state[_TOKENS] = min(self._l_max, state[_TOKENS] + max(1, round(state[_L0] * share)))
            state[_REINJECTIONS] += 1

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        reason = message.routing_state.pop(_FORWARD_REASON, "spray")
        forwarded_copy.routing_state.pop(_FORWARD_REASON, None)
        if self._max_syncs is not None:
            self._syncs[holder.id][1].add(contact.id)
        tokens = message.routing_state[_TOKENS]

        if reason == "island":
            forwarded_copy.routing_state[_TOKENS] = 0
            return

        if reason == "focus":
            forwarded_copy.routing_state[_TOKENS] = 1
            if holder.id == message.src_id:
                message.routing_state[_TOKENS] = 0  # shadow copy, kept for reinjection
            else:
                holder.buffer.pop(message.msg_id, None)
            return

        share = self._token_share(message, holder, contact, self._now)
        k_b = int(min(tokens - 1, max(1, round(tokens * share))))
        message.routing_state[_TOKENS] = tokens - k_b
        forwarded_copy.routing_state[_TOKENS] = k_b

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        self._delivered_ids.add(message.msg_id)

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        best_id = None
        best_key = None
        for mid, m in node.buffer.items():
            if m.src_id == node.id:
                continue  # never evict own messages
            key = (
                mid not in self._delivered_ids,
                not m.is_expired(now),
                now - m.creation_time <= self._late_after_s,
                m.routing_state.get(_TOKENS, 1) > 1,
                self._utility(node, m.dst_id, now),
                -m.hops,
            )
            if best_key is None or key < best_key:
                best_id, best_key = mid, key
        return best_id
