from __future__ import annotations
import math
from typing import Dict, Set, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_MULE_REPLICATED = "mule_replicated"
_FORWARD_REASON = "_forward_reason"


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
        mule_min_battery_pct: float = 0.40,
        battery_low_pct: float = 0.15,
        battery_evac_pct: float = 0.30,
    ) -> None:
        if k_min < 1:
            raise ValueError("k_min must be >= 1")
        if l_max < k_min:
            raise ValueError("l_max must be >= k_min")
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
        self._mule_min_battery_pct = mule_min_battery_pct
        self._battery_low_pct = battery_low_pct
        self._battery_evac_pct = battery_evac_pct

        # PRoPHET-style delivery predictability, nested by holder id so a
        # single node's row can be read/updated without scanning every pair
        # in the run -- matters at the 10000-node scale this simulator targets.
        self._predictability: Dict[int, Dict[int, float]] = {}
        # a's last-seen timestamp for b. Doubles as: the PRoPHET aging clock,
        # the local-density window (count of recent entries for a node) and
        # the 2-hop freshness check (has b recently seen the destination).
        self._last_seen: Dict[int, Dict[int, float]] = {}
        # Rolling contact-set generations per node, for the mule turnover
        # heuristic (Jaccard dissimilarity between consecutive windows).
        self._window_contacts: Dict[int, Set[int]] = {}
        self._prev_window_contacts: Dict[int, Set[int]] = {}
        self._window_id = None
        # Network-wide ACK purge: once any node delivers a msg_id, every
        # other holder's next decide() call for it purges the stale copy.
        # Models ACK propagation as instant/reliable (the spec's own ACK
        # gossip is cheap/epidemic) rather than simulating bloom-filter
        # dissemination over BLE.
        self._delivered_ids: Set[int] = set()

    def _decayed(self, a: int, b: int, now: float) -> float:
        p = self._predictability.get(a, {}).get(b, 0.0)
        if p == 0.0:
            return 0.0
        last = self._last_seen.get(a, {}).get(b, now)
        return p * (self._gamma ** (max(0.0, now - last) / 30.0))

    def _maybe_rotate_window(self, now: float) -> None:
        window_id = int(now // self._window_rotation_s)
        if self._window_id is None:
            self._window_id = window_id
            return
        if window_id != self._window_id:
            self._prev_window_contacts = self._window_contacts
            self._window_contacts = {}
            self._window_id = window_id

    def _touch_encounter(self, a: int, b: int, now: float) -> None:
        if self._last_seen.get(a, {}).get(b) == now:
            return  # already updated for this ordered pair this tick
        for x, y in ((a, b), (b, a)):
            p_old = self._decayed(x, y, now)
            self._predictability.setdefault(x, {})[y] = p_old + (1 - p_old) * self._p_encounter_init
            self._last_seen.setdefault(x, {})[y] = now
        if self._enable_transitivity:
            self._apply_transitivity(a, b, now)
        self._maybe_rotate_window(now)
        for x, y in ((a, b), (b, a)):
            self._window_contacts.setdefault(x, set()).add(y)

    def _apply_transitivity(self, a: int, b: int, now: float) -> None:
        p_ab = self._decayed(a, b, now)
        for dst in list(self._predictability.get(b, {}).keys()):
            if dst in (a, b):
                continue
            p_bc = self._decayed(b, dst, now)
            p_old = self._decayed(a, dst, now)
            self._predictability.setdefault(a, {})[dst] = p_old + (1 - p_old) * p_ab * p_bc * self._beta
            self._last_seen.setdefault(a, {})[dst] = now
        for dst in list(self._predictability.get(a, {}).keys()):
            if dst in (a, b):
                continue
            p_ac = self._decayed(a, dst, now)
            p_old = self._decayed(b, dst, now)
            self._predictability.setdefault(b, {})[dst] = p_old + (1 - p_old) * p_ab * p_ac * self._beta
            self._last_seen.setdefault(b, {})[dst] = now

    def _density(self, node_id: int, now: float) -> int:
        contacts = self._last_seen.get(node_id, {})
        return sum(1 for t in contacts.values() if now - t <= self._density_window_s)

    def _recently_seen(self, node_id: int, other_id: int, now: float) -> bool:
        t = self._last_seen.get(node_id, {}).get(other_id)
        return t is not None and (now - t) <= self._two_hop_freshness_s

    def _initial_tokens(self, density: int) -> int:
        raw = self._l_base * math.sqrt(self._d_ref / max(density, 1))
        return int(min(self._l_max, max(self._k_min, round(raw))))

    def _battery_pct(self, node: "BaseNode") -> float:
        initial = getattr(node, "initial_battery_mah", math.inf)
        if initial == math.inf or initial <= 0:
            return 1.0
        return node.battery_mah / initial

    def _turnover(self, node_id: int) -> float:
        current = self._window_contacts.get(node_id, set())
        previous = self._prev_window_contacts.get(node_id, set())
        if not previous:
            return 0.0
        union = current | previous
        if not union:
            return 0.0
        jaccard = len(current & previous) / len(union)
        return 1.0 - jaccard

    def _is_mule(self, node: "BaseNode", now: float) -> bool:
        return (
            self._turnover(node.id) >= self._mule_turnover_threshold
            and self._battery_pct(node) >= self._mule_min_battery_pct
        )

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered_ids:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE

        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE

        self._touch_encounter(holder.id, contact.id, now)

        tokens = message.routing_state.get(_TOKENS)
        if tokens is None:
            tokens = self._initial_tokens(self._density(holder.id, now))
            message.routing_state[_TOKENS] = tokens

        if self._battery_pct(contact) < self._battery_low_pct and contact.id != message.dst_id:
            return RoutingDecision.IGNORE

        dst = message.dst_id
        if self._recently_seen(contact.id, dst, now):
            message.routing_state[_FORWARD_REASON] = "two_hop"
            return RoutingDecision.FORWARD

        if tokens > 1:
            message.routing_state[_FORWARD_REASON] = (
                "spray_mule" if self._is_mule(contact, now) else "spray"
            )
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
            and self._is_mule(contact, now)
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
            # Holder keeps its own copy and its full token budget; the mule
            # gets exactly one token, flagged so it can't be replicated again
            # downstream and so the last copy is never the one moved to it.
            forwarded_copy.routing_state[_TOKENS] = 1
            forwarded_copy.routing_state[_MULE_REPLICATED] = True
            message.routing_state[_MULE_REPLICATED] = True
            return

        if reason == "two_hop":
            if tokens <= 1:
                # Last copy handed off to a carrier known to be near the
                # destination right now: a move, not a spray.
                forwarded_copy.routing_state[_TOKENS] = tokens
                del holder.buffer[message.msg_id]
            else:
                forwarded_copy.routing_state[_TOKENS] = 1
                message.routing_state[_TOKENS] = tokens - 1
            return

        if reason == "focus":
            # Single remaining copy moves to a materially better carrier.
            forwarded_copy.routing_state[_TOKENS] = tokens
            del holder.buffer[message.msg_id]
            return

        # Spray: split the token budget. A mule gets a smaller share so a
        # single mule contact can't drain the whole budget in one contact.
        if reason == "spray_mule":
            contact_share = max(1, tokens // 3)
        else:
            contact_share = tokens // 2
        holder_share = tokens - contact_share
        message.routing_state[_TOKENS] = holder_share
        forwarded_copy.routing_state[_TOKENS] = contact_share
