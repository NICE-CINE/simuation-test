from __future__ import annotations
import random
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision, per_destination_table_bytes

if TYPE_CHECKING:
    from ..nodes import BaseNode


class BandFanoutRouting(RoutingAlgorithm):
    # Bounded-fanout relaying aimed at contacts that are far enough to spread
    # the message but not at the fringe of the range, where shadowing makes
    # packets drop. Each copy may be relayed `fanout` times (the relayed copy
    # gets a fresh budget), then only direct delivery remains. Neighbors that
    # were in range of the destination within `met_dst_window_s` are the
    # exception: they get the copy without spending the holder's budget, but
    # the copy they receive is only passed on to other such neighbors.
    def __init__(
        self,
        fanout: int = 3,
        max_hops: int = 4,
        band: Tuple[float, float] = (0.4, 0.6),
        seed: int = 0,
        purge_delivered: bool = True,
        met_dst_window_s: Optional[float] = 1200.0,
    ) -> None:
        if fanout < 1:
            raise ValueError("fanout must be >= 1")
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        if not 0.0 <= band[0] < band[1]:
            raise ValueError("band must satisfy 0 <= low < high")
        if met_dst_window_s is not None and met_dst_window_s <= 0:
            raise ValueError("met_dst_window_s must be > 0 or None")
        self._fanout = fanout
        self._max_hops = max_hops
        self._band = band
        # Delivery acks spread by the engine purge copies; off = copies live
        # until their TTL.
        self.uses_delivery_acks = purge_delivered
        self._met_window = met_dst_window_s
        self._rng = random.Random(seed)
        self._nodes: Dict[int, "BaseNode"] = {}
        self._selected: Dict[int, Set[int]] = {}
        self._informed: Dict[int, Set[int]] = {}
        self._last_seen: Dict[int, Dict[int, float]] = {}
        self._now = 0.0
        # Relays already spent per (holder, message), not stored in routing_state:
        # a copy cloned by the beacon backhaul would otherwise inherit the
        # source beacon's exhausted budget instead of starting fresh.
        self._relayed: Dict[int, Dict[int, int]] = {}

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._now = now
        self._selected = {}
        self._informed = {}
        if self._met_window is not None:
            for node_id, neighbors in neighbors_by_node.items():
                row = self._last_seen.setdefault(node_id, {})
                for n in neighbors:
                    row[n.id] = now
        for node_id, neighbors in neighbors_by_node.items():
            node = self._nodes.get(node_id)
            if node is None:
                continue
            spent = self._relayed.get(node_id)
            if spent:
                for msg_id in [m for m in spent if m not in node.buffer]:
                    del spent[msg_id]
            if not node.is_active or not neighbors:
                continue
            pending = [m for m in node.buffer.values() if self._can_relay(m, node_id)]
            if pending:
                self._selected[node_id] = self._select(node, neighbors, pending)
            informed = self._informed_neighbors(node, neighbors, now)
            if informed:
                self._informed[node_id] = informed

    def _met_dst(self, contact: "BaseNode", dst_id: int, now: float) -> bool:
        if self._met_window is None:
            return False
        seen = self._last_seen.get(contact.id, {}).get(dst_id)
        return seen is not None and now - seen <= self._met_window

    def _informed_neighbors(self, holder: "BaseNode", neighbors: List["BaseNode"], now: float) -> Set[int]:
        if self._met_window is None:
            return set()
        messages = [m for m in holder.buffer.values() if m.hops < self._max_hops]
        return {
            n.id
            for n in neighbors
            if any(m.dst_id != n.id and not n.has_message(m.msg_id) and self._met_dst(n, m.dst_id, now) for m in messages)
        }

    def _can_relay(self, message: Message, holder_id: int) -> bool:
        if message.hops >= self._max_hops:
            return False
        return self._relayed.get(holder_id, {}).get(message.msg_id, 0) < self._fanout

    def _select(self, holder: "BaseNode", neighbors: List["BaseNode"], pending: List[Message]) -> Set[int]:
        # A neighbor that already has every pending message (or is their
        # destination) can't use a relay slot: drawing it would burn a link
        # without ever spending fanout budget.
        # Sorted by id: the grid returns neighbors in set order (memory
        # addresses), and the GPS noise below is drawn neighbor by neighbor.
        useful = sorted(
            (n for n in neighbors if any(m.dst_id != n.id and not n.has_message(m.msg_id) for m in pending)),
            key=lambda n: n.id,
        )
        origin = holder.gps_position()
        ratios = [(origin.distance_to(n.gps_position()) / holder.radio_range_m, n.id) for n in useful]
        ratios.sort()
        low, high = self._band
        in_band = [node_id for ratio, node_id in ratios if low <= ratio <= high]
        if len(in_band) >= self._fanout:
            return set(self._rng.sample(in_band, self._fanout))
        out_of_band = sorted(
            ((low - ratio if ratio < low else ratio - high), node_id)
            for ratio, node_id in ratios
            if not low <= ratio <= high
        )
        fill = [node_id for _, node_id in out_of_band[: self._fanout - len(in_band)]]
        return set(in_band) | set(fill)

    def select_links(self, sender: "BaseNode", neighbors: List["BaseNode"], max_links: int) -> List["BaseNode"]:
        # Without this the engine would keep only the nearest links and the
        # band, 12-18 m out, would almost never be reachable in a dense crowd.
        # Destinations of what the sender holds come first: direct delivery
        # bypasses decide() but still needs a link; informed neighbors share
        # the second tier with the drawn relays.
        dst_ids = {m.dst_id for m in sender.buffer.values()}
        chosen_ids = self._informed.get(sender.id, set()) | self._selected.get(sender.id, set())
        if not dst_ids and not chosen_ids:
            return super().select_links(sender, neighbors, max_links)
        ranked = super().select_links(sender, neighbors, len(neighbors))
        destinations = [n for n in ranked if n.id in dst_ids]
        chosen = [n for n in ranked if n.id in chosen_ids and n.id not in dst_ids]
        others = [n for n in ranked if n.id not in dst_ids and n.id not in chosen_ids]
        return (destinations + chosen + others)[:max_links]

    def connection_table_bytes(self, node: "BaseNode", peer: "BaseNode") -> int:
        # When node last met each destination the peer carries messages for.
        return per_destination_table_bytes(peer)

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        if message.hops >= self._max_hops:
            return RoutingDecision.IGNORE
        if self._met_dst(contact, message.dst_id, now):
            return RoutingDecision.FORWARD
        if not self._can_relay(message, holder.id):
            return RoutingDecision.IGNORE
        if contact.id not in self._selected.get(holder.id, ()):
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        if self._met_dst(contact, message.dst_id, self._now):
            self._relayed.setdefault(contact.id, {})[message.msg_id] = self._fanout
            return
        spent = self._relayed.setdefault(holder.id, {})
        spent[message.msg_id] = spent.get(message.msg_id, 0) + 1
        self._relayed.get(contact.id, {}).pop(message.msg_id, None)
