from __future__ import annotations
import math
from typing import Dict, List, Set, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_ON_BEACON = "on_beacon"
_REASON = "_reason"


class FreshSprayRouting(RoutingAlgorithm):
    # Binary spray of a copy budget, plus: replicate to anyone who met the
    # destination recently, hand the last copy to whoever met it more
    # recently than the holder (FRESH), one replica onto the beacon backbone,
    # and a network-wide ACK purge. The engine charges tx energy on each lost
    # attempt for every buffered message, so the purge and the single-copy
    # handoff (not keeping stale copies) are what keep energy low.
    def __init__(
        self,
        initial_tokens: int = 16,
        met_dst_window_s: float = 1200.0,
        min_freshness_gain_s: float = 5.0,
        battery_low_pct: float = 0.15,
    ) -> None:
        if initial_tokens < 1:
            raise ValueError("initial_tokens must be >= 1")
        self._initial_tokens = initial_tokens
        self._met_dst_window = met_dst_window_s
        self._min_gain = min_freshness_gain_s
        self._battery_low_pct = battery_low_pct
        self._last_seen: Dict[int, Dict[int, float]] = {}
        self._delivered: Set[int] = set()
        self._nodes: Dict[int, "BaseNode"] = {}

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        for node_id, neighbors in neighbors_by_node.items():
            row = self._last_seen.setdefault(node_id, {})
            for n in neighbors:
                row[n.id] = now
            node = self._nodes.get(node_id)
            if self._delivered and node is not None and node.buffer:
                for mid in [mid for mid in node.buffer if mid in self._delivered]:
                    del node.buffer[mid]

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        self._delivered.add(message.msg_id)
        holder.buffer.pop(message.msg_id, None)

    def _seen(self, node_id: int, other_id: int) -> float:
        return self._last_seen.get(node_id, {}).get(other_id, -math.inf)

    @staticmethod
    def _battery_pct(node: "BaseNode") -> float:
        initial = node.initial_battery_mah
        if initial == math.inf or initial <= 0:
            return 1.0
        return node.battery_mah / initial

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        state = message.routing_state
        if getattr(contact, "is_beacon", False):
            if state.get(_ON_BEACON):
                return RoutingDecision.IGNORE
            state[_REASON] = "beacon"
            return RoutingDecision.FORWARD
        if self._battery_pct(contact) < self._battery_low_pct:
            return RoutingDecision.IGNORE
        dst = message.dst_id
        if now - self._seen(contact.id, dst) <= self._met_dst_window:
            state[_REASON] = "met_dst"
            return RoutingDecision.FORWARD
        if state.get(_TOKENS, self._initial_tokens) > 1:
            state[_REASON] = "spray"
            return RoutingDecision.FORWARD
        if self._seen(contact.id, dst) > self._seen(holder.id, dst) + self._min_gain:
            state[_REASON] = "focus"
            return RoutingDecision.FORWARD
        return RoutingDecision.IGNORE

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        reason = message.routing_state.pop(_REASON, "spray")
        forwarded_copy.routing_state.pop(_REASON, None)
        tokens = message.routing_state.get(_TOKENS, self._initial_tokens)
        if reason == "beacon":
            message.routing_state[_ON_BEACON] = True
            forwarded_copy.routing_state[_ON_BEACON] = True
            forwarded_copy.routing_state[_TOKENS] = 1
        elif reason == "met_dst":
            forwarded_copy.routing_state[_TOKENS] = 1
        elif reason == "spray":
            message.routing_state[_TOKENS] = tokens - tokens // 2
            forwarded_copy.routing_state[_TOKENS] = tokens // 2
        else:
            forwarded_copy.routing_state[_TOKENS] = 1
            # Beacons are fixed and mains-powered: they keep a copy for
            # whenever the destination walks past them again.
            if not getattr(holder, "is_beacon", False):
                holder.buffer.pop(message.msg_id, None)
