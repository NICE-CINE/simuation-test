from __future__ import annotations
import random
from typing import Dict, List, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode


class BandFanoutRouting(RoutingAlgorithm):
    # Bounded-fanout relaying aimed at contacts that are far enough to spread
    # the message but not at the fringe of the range, where shadowing makes
    # packets drop. Each copy may be relayed `fanout` times (the relayed copy
    # gets a fresh budget), then only direct delivery remains.
    def __init__(
        self,
        fanout: int = 3,
        max_hops: int = 4,
        band: Tuple[float, float] = (0.4, 0.6),
        seed: int = 0,
        purge_delivered: bool = True,
    ) -> None:
        if fanout < 1:
            raise ValueError("fanout must be >= 1")
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        if not 0.0 <= band[0] < band[1]:
            raise ValueError("band must satisfy 0 <= low < high")
        self._fanout = fanout
        self._max_hops = max_hops
        self._band = band
        self._purge_delivered = purge_delivered
        self._rng = random.Random(seed)
        self._delivered: Set[int] = set()
        self._nodes: Dict[int, "BaseNode"] = {}
        self._selected: Dict[int, Set[int]] = {}
        # Relays already spent per (holder, message), not stored in routing_state:
        # a copy cloned by the beacon backhaul would otherwise inherit the
        # source beacon's exhausted budget instead of starting fresh.
        self._relayed: Dict[int, Dict[int, int]] = {}

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._selected = {}
        for node_id, neighbors in neighbors_by_node.items():
            node = self._nodes.get(node_id)
            if node is None:
                continue
            for msg_id in self._delivered.intersection(node.buffer):
                del node.buffer[msg_id]
            spent = self._relayed.get(node_id)
            if spent:
                for msg_id in [m for m in spent if m not in node.buffer]:
                    del spent[msg_id]
            if not node.is_active or not neighbors:
                continue
            pending = [m for m in node.buffer.values() if self._can_relay(m, node_id)]
            if pending:
                self._selected[node_id] = self._select(node, neighbors, pending)

    def _can_relay(self, message: Message, holder_id: int) -> bool:
        if message.hops >= self._max_hops:
            return False
        return self._relayed.get(holder_id, {}).get(message.msg_id, 0) < self._fanout

    def _select(self, holder: "BaseNode", neighbors: List["BaseNode"], pending: List[Message]) -> Set[int]:
        # A neighbor that already has every pending message (or is their
        # destination) can't use a relay slot: drawing it would burn a link
        # without ever spending fanout budget.
        useful = [
            n for n in neighbors if any(m.dst_id != n.id and not n.has_message(m.msg_id) for m in pending)
        ]
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
        # bypasses decide() but still needs a link.
        dst_ids = {m.dst_id for m in sender.buffer.values()}
        chosen_ids = self._selected.get(sender.id, ())
        if not dst_ids and not chosen_ids:
            return super().select_links(sender, neighbors, max_links)
        ranked = super().select_links(sender, neighbors, len(neighbors))
        destinations = [n for n in ranked if n.id in dst_ids]
        chosen = [n for n in ranked if n.id in chosen_ids and n.id not in dst_ids]
        others = [n for n in ranked if n.id not in dst_ids and n.id not in chosen_ids]
        return (destinations + chosen + others)[:max_links]

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered or contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        if not self._can_relay(message, holder.id):
            return RoutingDecision.IGNORE
        if contact.id not in self._selected.get(holder.id, ()):
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        spent = self._relayed.setdefault(holder.id, {})
        spent[message.msg_id] = spent.get(message.msg_id, 0) + 1
        self._relayed.get(contact.id, {}).pop(message.msg_id, None)

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        if self._purge_delivered:
            self._delivered.add(message.msg_id)
            holder.buffer.pop(message.msg_id, None)
