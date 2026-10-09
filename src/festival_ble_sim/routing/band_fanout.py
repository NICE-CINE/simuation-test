from __future__ import annotations
import random
from typing import Dict, List, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_FANOUT_LEFT = "fanout_left"


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

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._selected = {}
        for node_id, neighbors in neighbors_by_node.items():
            node = self._nodes.get(node_id)
            if node is None:
                continue
            if self._delivered:
                for msg_id in [m for m in node.buffer if m in self._delivered]:
                    del node.buffer[msg_id]
            if not node.is_active or not node.buffer or not neighbors:
                continue
            self._selected[node_id] = self._select(node, neighbors)

    def _select(self, holder: "BaseNode", neighbors: List["BaseNode"]) -> Set[int]:
        origin = holder.gps_position()
        ratios = [
            (origin.distance_to(n.gps_position()) / holder.radio_range_m, n.id) for n in neighbors
        ]
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
        chosen_ids = self._selected.get(sender.id, ())
        ranked = super().select_links(sender, neighbors, len(neighbors))
        chosen = [n for n in ranked if n.id in chosen_ids][:max_links]
        others = [n for n in ranked if n.id not in chosen_ids]
        return chosen + others[: max_links - len(chosen)]

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered or contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        if message.hops >= self._max_hops:
            return RoutingDecision.IGNORE
        if message.routing_state.get(_FANOUT_LEFT, self._fanout) <= 0:
            return RoutingDecision.IGNORE
        if contact.id not in self._selected.get(holder.id, ()):
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        message.routing_state[_FANOUT_LEFT] = message.routing_state.get(_FANOUT_LEFT, self._fanout) - 1
        forwarded_copy.routing_state[_FANOUT_LEFT] = self._fanout

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        if self._purge_delivered:
            self._delivered.add(message.msg_id)
            holder.buffer.pop(message.msg_id, None)
