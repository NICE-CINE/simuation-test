from __future__ import annotations
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingDecision
from .fresh_spray import _REASON, _TOKENS, FreshSprayRouting

if TYPE_CHECKING:
    from ..nodes import BaseNode

_PULL = "pull"


class HorizonRouting(FreshSprayRouting):
    # fresh_spray plus a hop-distance field (DSDV-like distance vectors
    # bounded to horizon_hops). Each node broadcasts its vector once per
    # announce_period_s at its own phase (jittered, so the whole crowd never
    # announces in the same tick) through the engine's control_broadcasts
    # path (airtime, channel load, loss, energy). Right before broadcasting it
    # rebuilds its vector from the last one heard from each neighbor within
    # entry_ttl_s: one lost announce doesn't erase a route, a neighbor gone
    # quiet drops out after entry_ttl_s. Rebuilding from scratch only from
    # the current round's receptions collapses the field under ~1/3 per-link
    # reception (a k-hop route needs k consecutive successes).
    # A copy whose holder has a neighbor closer to the destination moves down
    # that gradient, one hop per tick; the last horizon_hops of the hop TTL
    # are kept for that pull (fresh_spray alone burns ~7 of the 8 hops).
    def __init__(
        self,
        horizon_hops: int = 5,
        announce_period_s: float = 5.0,
        entry_ttl_s: float = 15.0,
        announce_entry_bytes: int = 9,
        max_announce_bytes: int = 1650,
        **fresh_spray_kwargs,
    ) -> None:
        if horizon_hops < 1:
            raise ValueError("horizon_hops must be >= 1")
        super().__init__(**fresh_spray_kwargs)
        self._horizon = horizon_hops
        self._period = announce_period_s
        self._entry_ttl = entry_ttl_s
        self._entry_bytes = announce_entry_bytes
        self._max_entries = max(1, max_announce_bytes // announce_entry_bytes)
        self._dist: Dict[int, Dict[int, int]] = {}
        self._vectors: Dict[int, Dict[int, Tuple[int, int]]] = {}
        self._heard: Dict[int, Dict[int, Tuple[Dict[int, Tuple[int, int]], float]]] = {}
        self._next_due: Dict[int, float] = {}
        self._neighbors: Dict[int, List["BaseNode"]] = {}
        self._now = 0.0
        self._next_hops: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {}
        self._sizes: Dict[int, int] = {}
        self.stats = {"pull": 0, "announce_bytes": 0, "announce_rx_bytes": 0, "announces_sent": 0, "announces_received": 0}

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        super().on_tick(now, neighbors_by_node)
        self._neighbors = neighbors_by_node
        self._now = now
        self._next_hops.clear()

    def _rebuild(self, node_id: int, now: float) -> Tuple[Dict[int, int], Dict[int, int]]:
        row = {node_id: 0}
        via = {node_id: node_id}
        heard = self._heard.get(node_id, {})
        for sender_id in [v for v, (_, t) in heard.items() if now - t > self._entry_ttl]:
            del heard[sender_id]
        for sender_id, (vector, _) in heard.items():
            for dst, (hops, next_hop) in vector.items():
                # Split horizon: a route through this very node would only
                # loop back and count up once the real route is gone.
                if next_hop == node_id or hops >= self._horizon:
                    continue
                if row.get(dst, self._horizon + 1) > hops + 1:
                    row[dst] = hops + 1
                    via[dst] = sender_id
        return row, via

    def control_broadcasts(self, now: float) -> Dict[int, int]:
        sizes: Dict[int, int] = {}
        for node_id in self._neighbors:
            due = self._next_due.get(node_id)
            if due is None:
                # Golden-ratio phases spread the nodes evenly over the period.
                due = self._next_due[node_id] = now + (node_id * 0.6180339887 % 1.0) * self._period
            if now < due:
                continue
            # From now, not from the missed slot: a node back from a gap would
            # otherwise catch up and announce again a tick later.
            self._next_due[node_id] = now + self._period
            # A new dict every time: neighbors keep a reference to it as
            # "the last vector heard", so it must never be mutated.
            row, via = self._rebuild(node_id, now)
            self._dist[node_id] = row
            # The engine never sends what exceeds a tick's airtime, and BLE 5
            # extended advertising stops at 1650 bytes: past the cap, only
            # the nearest destinations are announced.
            nearest = sorted(row.items(), key=lambda e: (e[1], e[0]))[:self._max_entries]
            self._vectors[node_id] = {dst: (hops, via[dst]) for dst, hops in nearest}
            sizes[node_id] = len(nearest) * self._entry_bytes
        self._sizes = sizes
        return sizes

    def on_control_received(self, now: float, received: Dict[int, List[int]], sent: List[int]) -> None:
        self.stats["announces_sent"] += len(sent)
        self.stats["announce_bytes"] += sum(self._sizes[node_id] for node_id in sent)
        for node_id, senders in received.items():
            heard = self._heard.setdefault(node_id, {})
            reachable = {n.id for n in self._neighbors.get(node_id, ())}
            self.stats["announces_received"] += len(senders)
            for sender_id in senders:
                self.stats["announce_rx_bytes"] += self._sizes.get(sender_id, 0)
                # A beacon's longer range reaches phones that can't reach it
                # back: a route through it would be unusable.
                if sender_id in reachable:
                    heard[sender_id] = (self._vectors[sender_id], now)

    def _next_hop(self, holder: "BaseNode", dst_id: int) -> Optional[Tuple[int, int]]:
        key = (holder.id, dst_id)
        if key not in self._next_hops:
            best: Optional[Tuple[int, float, int]] = None
            limit = self._dist.get(holder.id, {}).get(dst_id, self._horizon + 1)
            heard = self._heard.get(holder.id, {})
            for n in self._neighbors.get(holder.id, ()):
                # Only what the holder actually received from n: n's own
                # table may be newer than any announce that got through.
                vector, t = heard.get(n.id, (None, 0.0))
                if vector is None or self._now - t > self._entry_ttl:
                    continue
                hops = vector.get(dst_id, (limit,))[0]
                if hops >= limit:
                    continue
                cand = (hops, holder.position.distance_squared_to(n.position), n.id)
                if best is None or cand < best:
                    best = cand
            self._next_hops[key] = None if best is None else (best[2], best[0])
        return self._next_hops[key]

    def _pull_target(self, message: Message, holder: "BaseNode") -> Optional[int]:
        hop = self._next_hop(holder, message.dst_id)
        if hop is None:
            return None
        # The neighbor at distance h needs h-1 more relays, then a direct
        # delivery the hop TTL doesn't gate.
        if message.ttl_hops is not None and message.hops + hop[1] > message.ttl_hops:
            return None
        return hop[0]

    def select_links(self, sender: "BaseNode", neighbors: List["BaseNode"], max_links: int) -> List["BaseNode"]:
        # Shortest-hop next hops tend to be the farthest neighbors, which the
        # default nearest-first link cap would starve.
        wanted = {self._pull_target(m, sender) for m in sender.buffer.values()}
        wanted.discard(None)
        if not wanted:
            return super().select_links(sender, neighbors, max_links)
        ranked = super().select_links(sender, neighbors, len(neighbors))
        return ([n for n in ranked if n.id in wanted] + [n for n in ranked if n.id not in wanted])[:max_links]

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if contact.has_message(message.msg_id):
            return super().decide(message, holder, contact, now)
        target = self._pull_target(message, holder)
        if target is not None:
            if target != contact.id:
                return RoutingDecision.IGNORE
            message.routing_state[_REASON] = _PULL
            return RoutingDecision.FORWARD
        if message.ttl_hops is not None and message.hops >= message.ttl_hops - self._horizon:
            return RoutingDecision.IGNORE
        return super().decide(message, holder, contact, now)

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        if message.routing_state.get(_REASON) != _PULL:
            super().on_forward(message, holder, contact, forwarded_copy)
            return
        message.routing_state.pop(_REASON)
        forwarded_copy.routing_state.pop(_REASON, None)
        self.stats["pull"] += 1
        if getattr(holder, "is_beacon", False):
            # The beacon keeps its copy: handing out its tokens too would mint
            # a full spray budget on every pull.
            forwarded_copy.routing_state[_TOKENS] = 1
            return
        forwarded_copy.routing_state[_TOKENS] = message.routing_state.get(_TOKENS, self._initial_tokens)
        holder.buffer.pop(message.msg_id, None)
