from __future__ import annotations
from collections import OrderedDict
from dataclasses import replace
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from ..config import EnergyConfig
from ..energy import EnergyModel
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_CacheKey = Tuple[int, int]


class ManagedFloodRouting(RoutingAlgorithm):
    # Bluetooth Mesh managed flooding, not store-carry-forward: a node relays
    # a PDU only during a short window after first hearing it, then forgets
    # the payload. Loops and storms are bounded by three mechanisms, as in
    # the spec's network layer: the TTL (hops), a bounded per-node network
    # message cache that drops any PDU already seen, and the relay window.
    # The SEQ of a PDU is modeled as routing_state["attempt"]: an
    # acknowledged source drops the payload after its relay window like any
    # relay (so it can't carry it to the destination later), and if no ack
    # arrives within ack_timeout_s it re-originates with a new SEQ, which
    # caches treat as a fresh PDU. Acks flood back as tokens (same TTL/window
    # rules) and purge copies; each ack hop is charged tx/rx energy for
    # ack_size_bytes, but not airtime (the engine's link budget never sees it).
    def __init__(
        self,
        ttl: int = 7,
        relay_window_s: float = 3.0,
        cache_size: int = 256,
        acknowledged: bool = True,
        ack_timeout_s: float = 30.0,
        max_source_retransmissions: int = 2,
        ack_size_bytes: int = 16,
        energy: Optional[EnergyConfig] = None,
    ) -> None:
        if ttl < 0:
            raise ValueError("ttl must be >= 0")
        if relay_window_s <= 0:
            raise ValueError("relay_window_s must be > 0")
        if cache_size < 1:
            raise ValueError("cache_size must be >= 1")
        if ack_timeout_s <= 0:
            raise ValueError("ack_timeout_s must be > 0")
        if max_source_retransmissions < 0:
            raise ValueError("max_source_retransmissions must be >= 0")
        if ack_size_bytes < 0:
            raise ValueError("ack_size_bytes must be >= 0")
        self._ttl = ttl
        self._relay_window_s = relay_window_s
        self._cache_size = cache_size
        self._acknowledged = acknowledged
        self._ack_timeout_s = ack_timeout_s
        self._max_retransmissions = max_source_retransmissions
        energy_model = EnergyModel(energy if energy is not None else EnergyConfig())
        self._ack_tx_mah = energy_model.cost_of_tx(ack_size_bytes)
        self._ack_rx_mah = energy_model.cost_of_rx(ack_size_bytes)

        self._nodes: Dict[int, "BaseNode"] = {}
        # Per node, insertion-ordered: the oldest entry is the first evicted
        # once cache_size is hit, like a fixed-size mesh message cache.
        self._cache: Dict[int, "OrderedDict[_CacheKey, float]"] = {}
        self._acks: Dict[int, "OrderedDict[int, None]"] = {}
        # (node_id, msg_id, hops, learned_at) still inside their relay window.
        self._relaying_acks: List[Tuple[int, int, int, float]] = []
        # msg_id -> (source, PDU as last sent, first sent at), awaiting an ack.
        self._pending: Dict[int, Tuple["BaseNode", Message, float]] = {}
        self._now = 0.0

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    def _remember(self, node_id: int, key: _CacheKey, now: float) -> float:
        cache = self._cache.setdefault(node_id, OrderedDict())
        first_seen = cache.get(key)
        if first_seen is not None:
            return first_seen
        cache[key] = now
        while len(cache) > self._cache_size:
            cache.popitem(last=False)
        return now

    def in_cache(self, node_id: int, msg_id: int, attempt: int = 0) -> bool:
        return (msg_id, attempt) in self._cache.get(node_id, {})

    def knows_ack(self, node_id: int, msg_id: int) -> bool:
        return msg_id in self._acks.get(node_id, {})

    def _learn_ack(self, node_id: int, msg_id: int, hops: int, now: float) -> None:
        acks = self._acks.setdefault(node_id, OrderedDict())
        if msg_id in acks:
            return
        acks[msg_id] = None
        while len(acks) > self._cache_size:
            acks.popitem(last=False)
        self._relaying_acks.append((node_id, msg_id, hops, now))
        node = self._nodes.get(node_id)
        if node is not None:
            node.buffer.pop(msg_id, None)

    def _refresh(self, node: "BaseNode", message: Message, now: float) -> bool:
        # Returns whether `node` may still relay `message` right now, dropping
        # it from the buffer once its relay window is over.
        if self.knows_ack(node.id, message.msg_id):
            node.buffer.pop(message.msg_id, None)
            return False
        attempt = message.routing_state.get("attempt", 0)
        first_seen = self._remember(node.id, (message.msg_id, attempt), now)
        if now - first_seen <= self._relay_window_s:
            return True
        node.buffer.pop(message.msg_id, None)
        if self._acknowledged and node.id == message.src_id:
            self._pending.setdefault(message.msg_id, (node, message, first_seen))
        return False

    def _retransmit_unacked(self, now: float) -> None:
        for msg_id, (source, message, sent_at) in list(self._pending.items()):
            if self.knows_ack(source.id, msg_id):
                del self._pending[msg_id]
                continue
            if now - sent_at <= self._ack_timeout_s:
                continue
            del self._pending[msg_id]
            attempt = message.routing_state.get("attempt", 0)
            if attempt >= self._max_retransmissions or not source.is_active or message.is_expired(now):
                continue
            retry = replace(message, routing_state={**message.routing_state, "attempt": attempt + 1})
            self._remember(source.id, (msg_id, attempt + 1), now)
            source.store_message(retry)

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if not self._refresh(holder, message, now):
            return RoutingDecision.IGNORE
        if message.hops >= self._ttl:
            return RoutingDecision.IGNORE
        attempt = message.routing_state.get("attempt", 0)
        if (
            contact.has_message(message.msg_id)
            or self.in_cache(contact.id, message.msg_id, attempt)
            or self.knows_ack(contact.id, message.msg_id)
        ):
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        attempt = forwarded_copy.routing_state.get("attempt", 0)
        self._remember(contact.id, (forwarded_copy.msg_id, attempt), self._now)

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        if not self._acknowledged:
            return
        self._learn_ack(message.dst_id, message.msg_id, 0, self._now)
        if not self.knows_ack(holder.id, message.msg_id):
            self._charge_ack_hop(self._nodes.get(message.dst_id), holder)
            self._learn_ack(holder.id, message.msg_id, 1, self._now)

    def _charge_ack_hop(self, sender: Optional["BaseNode"], receiver: "BaseNode") -> None:
        # Per pair, like the engine charges data PDUs.
        if sender is not None:
            sender.consume_energy(self._ack_tx_mah)
        receiver.consume_energy(self._ack_rx_mah)

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._now = now
        # Two-phase like the engine's buffer snapshot: an ack learned this
        # tick is relayed further only from next tick on.
        still_relaying: List[Tuple[int, int, int, float]] = []
        learned: List[Tuple["BaseNode", "BaseNode", int, int]] = []
        for node_id, msg_id, hops, learned_at in self._relaying_acks:
            if now - learned_at > self._relay_window_s or hops >= self._ttl:
                continue
            still_relaying.append((node_id, msg_id, hops, learned_at))
            for neighbor in neighbors_by_node.get(node_id, ()):
                if neighbor.is_active and not self.knows_ack(neighbor.id, msg_id):
                    learned.append((self._nodes.get(node_id), neighbor, msg_id, hops + 1))
        self._relaying_acks = still_relaying
        for sender, receiver, msg_id, hops in learned:
            if self.knows_ack(receiver.id, msg_id):
                continue
            self._charge_ack_hop(sender, receiver)
            self._learn_ack(receiver.id, msg_id, hops, now)

        # Without this sweep an isolated node would keep an expired PDU until
        # its next contact, and the engine's direct-delivery branch (which
        # never calls decide) would turn that into store-carry-forward.
        for node in self._nodes.values():
            for message in list(node.buffer.values()):
                self._refresh(node, message, now)
        self._retransmit_unacked(now)
