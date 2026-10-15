from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingDecision
from .managed_flood import ManagedFloodRouting

if TYPE_CHECKING:
    from ..nodes import BaseNode

_NEVER = float("-inf")


@dataclass
class _Outbox:
    source: "BaseNode"
    sends: int = 0
    sent_at: float = _NEVER
    reachable_until: float = _NEVER
    couriers: Set[int] = field(default_factory=set)


class BitchatRouting(ManagedFloodRouting):
    # bitchat's private-message path (permissionlesstech/bitchat iOS, commit
    # 5e9287f), reduced to the network level; defaults are its constants.
    # - Mesh (RelayController, BLEService): directed packets are always
    #   relayed, TTL 7, no degree clamp; a node directly linked to the
    #   recipient sends to it only; dedup keeps 1000 ids for 300 s; a relay
    #   with no onward link spools the packet 60 s and retries every 5 s.
    # - Outbox (MessageRouter): the source only floods while the recipient is
    #   reachable (its announce, 7 hops clamped to 5 past 6 neighbors, heard
    #   within 60 s, every 4 s), resends on each unreachable -> reachable
    #   transition, at most 8 sends, and keeps the message until the ack.
    # - Couriers (CourierStore): the source hands sealed copies to up to 3
    #   connected peers, mutual favorites (friends) first, each with a
    #   spray-and-wait budget of 4 halved to every other peer met; a courier
    #   hands over directly on contact, or floods a copy when the recipient's
    #   announce reaches it, every 10 min at most.
    # Acks are managed_flood's flooded acks (they also purge copies), relay
    # jitter is below the tick, full courier stores reject instead of evicting.
    # Announces go over the radio: each round every node sends its own and
    # relays every other one that reaches it, approximated by the size of
    # its connected component (one BFS per round instead of one per origin),
    # spread over the round and capped at the node's airtime, so a big
    # crowd's announce flood crowds the data out. Who hears an announce is
    # still the loss-free BFS of _announce_reach.
    def __init__(
        self,
        ttl: int = 7,
        relay_window_s: float = 1.0,
        cache_size: int = 1000,
        dedup_max_age_s: float = 300.0,
        spool_window_s: float = 60.0,
        spool_capacity: int = 512,
        maintenance_interval_s: float = 5.0,
        announce_interval_s: float = 4.0,
        announce_ttl: int = 7,
        high_degree_threshold: int = 6,
        dense_announce_ttl: int = 5,
        reachability_retention_s: float = 60.0,
        max_send_attempts: int = 8,
        max_couriers_per_message: int = 3,
        courier_initial_copies: int = 4,
        courier_handover_cooldown_s: float = 600.0,
        courier_capacity: int = 40,
        courier_verified_capacity: int = 20,
        courier_per_favorite_depositor: int = 5,
        courier_per_verified_depositor: int = 2,
        # Header, sender id, nickname, Noise and signing keys, signature
        # (estimated, not read off a capture).
        announce_bytes: int = 150,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            ttl=ttl, relay_window_s=relay_window_s, cache_size=cache_size,
            max_source_retransmissions=0, **kwargs,
        )
        if min(dedup_max_age_s, spool_window_s, maintenance_interval_s, announce_interval_s) <= 0:
            raise ValueError("durations must be > 0")
        if min(spool_capacity, max_send_attempts, courier_initial_copies) < 1:
            raise ValueError("spool_capacity, max_send_attempts and courier_initial_copies must be >= 1")
        self._dedup_max_age_s = dedup_max_age_s
        self._spool_window_s = spool_window_s
        self._spool_capacity = spool_capacity
        self._maintenance_interval_s = maintenance_interval_s
        self._announce_interval_s = announce_interval_s
        self._announce_ttl = announce_ttl
        self._high_degree_threshold = high_degree_threshold
        self._dense_announce_ttl = dense_announce_ttl
        self._reachability_retention_s = reachability_retention_s
        self._max_send_attempts = max_send_attempts
        self._max_couriers = max_couriers_per_message
        self._courier_copies = courier_initial_copies
        self._handover_cooldown_s = courier_handover_cooldown_s
        self._courier_capacity = courier_capacity
        self._courier_verified_capacity = courier_verified_capacity
        self._per_depositor = {"favorite": courier_per_favorite_depositor, "verified": courier_per_verified_depositor}
        self._announce_bytes = announce_bytes
        self._airtime_bytes = math.inf
        self._tick_s = 1.0
        self._announce_load: Dict[int, float] = {}

        self._outbox: Dict[int, _Outbox] = {}
        # node -> msg_id -> spooled at, oldest first.
        self._spool: Dict[int, "OrderedDict[int, float]"] = {}
        self._flush_now: Set[Tuple[int, int]] = set()
        # (courier, msg_id) -> last remote handover; pruned lazily.
        self._carriers: Dict[Tuple[int, int], float] = {}
        self._neighbors_by_node: Dict[int, List["BaseNode"]] = {}
        self._neighbor_ids: Dict[int, Set[int]] = {}
        self._reach: Dict[int, Set[int]] = {}
        self._last_announce = _NEVER
        self._last_maintenance = _NEVER
        self._forward_reason = ""

    def _remember(self, node_id: int, key: Any, now: float) -> float:
        first_seen = super()._remember(node_id, key, now)
        if now - first_seen <= self._dedup_max_age_s:
            return first_seen
        cache = self._cache[node_id]
        cache.move_to_end(key)
        cache[key] = now
        return now

    def in_cache(self, node_id: int, msg_id: int, attempt: Any = 0) -> bool:
        first_seen = self._cache.get(node_id, {}).get((msg_id, attempt))
        return first_seen is not None and self._now - first_seen <= self._dedup_max_age_s

    @staticmethod
    def _role(node: "BaseNode", message: Message) -> str:
        return message.routing_state.get("role", "source" if node.id == message.src_id else "flood")

    def _flood_hops(self, node: "BaseNode", message: Message) -> int:
        # A courier's handover starts a fresh flood: TTL counts from it.
        if self._role(node, message) == "flood":
            return message.hops - message.routing_state.get("base", 0)
        return 0

    def _refresh(self, node: "BaseNode", message: Message, now: float) -> bool:
        if node.id == message.src_id and message.msg_id not in self._outbox and self._role(node, message) == "source":
            self._open_outbox(node, message, now)
        return super()._refresh(node, message, now)

    def _relay_window_over(self, node: "BaseNode", message: Message) -> None:
        if self._role(node, message) != "flood":
            return
        spool = self._spool.setdefault(node.id, OrderedDict())
        if message.msg_id in spool or (node.id, message.msg_id) in self._flush_now:
            return
        if message.routing_state.get("had_link") or self._flood_hops(node, message) >= self._ttl:
            node.buffer.pop(message.msg_id, None)
            return
        spool[message.msg_id] = self._now
        while len(spool) > self._spool_capacity:
            victim, _ = spool.popitem(last=False)
            node.buffer.pop(victim, None)

    def _neighbor_set(self, node_id: int) -> Set[int]:
        ids = self._neighbor_ids.get(node_id)
        if ids is None:
            ids = self._neighbor_ids[node_id] = {n.id for n in self._neighbors_by_node.get(node_id, ())}
        return ids

    def _announce_relay_ttl(self, received_ttl: int, degree: int) -> int:
        if degree <= 2:
            return received_ttl - 1
        cap = self._dense_announce_ttl if degree >= self._high_degree_threshold else self._announce_ttl
        return max(2, min(received_ttl, cap)) - 1

    def _announce_reach(self, origin: int) -> Set[int]:
        # Nodes that hear `origin`'s announce this round, first arrival wins.
        reach = self._reach.get(origin)
        if reach is not None:
            return reach
        reach = {origin}
        frontier = [(origin, self._announce_ttl)]
        while frontier:
            next_frontier = []
            for sender_id, ttl in frontier:
                for neighbor in self._neighbors_by_node.get(sender_id, ()):
                    if neighbor.id in reach:
                        continue
                    reach.add(neighbor.id)
                    if ttl > 1:
                        degree = len(self._neighbors_by_node.get(neighbor.id, ()))
                        next_frontier.append((neighbor.id, self._announce_relay_ttl(ttl, degree)))
            frontier = next_frontier
        self._reach[origin] = reach
        return reach

    def _open_outbox(self, source: "BaseNode", message: Message, now: float) -> None:
        entry = self._outbox[message.msg_id] = _Outbox(source)
        if source.id in self._announce_reach(message.dst_id):
            self._send(entry, message, now)

    def _send(self, entry: _Outbox, message: Message, now: float) -> None:
        message.routing_state["attempt"] = entry.sends
        entry.sends += 1
        entry.sent_at = now
        entry.reachable_until = now + self._reachability_retention_s

    def _tier(self, depositor: "BaseNode", courier: "BaseNode") -> str:
        return "favorite" if depositor.id in courier.friends and courier.id in depositor.friends else "verified"

    def _accepts(self, courier: "BaseNode", depositor: "BaseNode", message: Message) -> bool:
        if getattr(courier, "is_beacon", False) or courier.id == message.dst_id or courier.has_message(message.msg_id):
            return False
        tier = self._tier(depositor, courier)
        carried = [m.routing_state for m in courier.buffer.values() if m.routing_state.get("role") == "courier"]
        if len(carried) >= self._courier_capacity:
            return False
        if tier == "verified" and sum(rs["tier"] == "verified" for rs in carried) >= self._courier_verified_capacity:
            return False
        return sum(rs["giver"] == depositor.id for rs in carried) < self._per_depositor[tier]

    def _deposit_ok(self, entry: _Outbox, message: Message, holder: "BaseNode", contact: "BaseNode") -> bool:
        if len(entry.couriers) >= self._max_couriers or contact.id in entry.couriers:
            return False
        if not self._accepts(contact, holder, message):
            return False
        if self._tier(holder, contact) == "favorite":
            return True
        # MessageRouter.eligibleCouriers ranks mutual favorites first.
        return not any(
            n.id not in entry.couriers and self._tier(holder, n) == "favorite" and self._accepts(n, holder, message)
            for n in self._neighbors_by_node.get(holder.id, ())
        )

    def _spray_ok(self, message: Message, holder: "BaseNode", contact: "BaseNode") -> bool:
        state = message.routing_state
        return (
            state["copies"] > 1
            and contact.id != state["giver"]
            and contact.id not in state["sprayed"]
            and self._accepts(contact, holder, message)
        )

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if self.knows_ack(holder.id, message.msg_id):
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE
        if message.dst_id in self._neighbor_set(holder.id):
            return RoutingDecision.IGNORE
        role = self._role(holder, message)
        if role == "source":
            entry = self._outbox.get(message.msg_id)
            flooding = entry is not None and now - entry.sent_at <= self._relay_window_s
            if not flooding and entry is not None and self._deposit_ok(entry, message, holder, contact):
                self._forward_reason = "deposit"
                return RoutingDecision.FORWARD
        elif role == "courier":
            flooding = now - self._carriers.get((holder.id, message.msg_id), _NEVER) <= self._relay_window_s
            if not flooding and self._spray_ok(message, holder, contact):
                self._forward_reason = "spray"
                return RoutingDecision.FORWARD
        else:
            flooding = (holder.id, message.msg_id) in self._flush_now or self._refresh(holder, message, now)
            if flooding and contact.id != message.routing_state.get("ingress"):
                message.routing_state["had_link"] = True
        if not flooding or self._flood_hops(holder, message) >= self._ttl:
            return RoutingDecision.IGNORE
        attempt = message.routing_state.get("attempt", 0)
        if (
            contact.has_message(message.msg_id)
            or self.in_cache(contact.id, message.msg_id, attempt)
            or self.knows_ack(contact.id, message.msg_id)
        ):
            return RoutingDecision.IGNORE
        self._forward_reason = "flood"
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        state = forwarded_copy.routing_state
        attempt = message.routing_state.get("attempt", 0)
        state.clear()
        if self._forward_reason == "flood":
            base = message.routing_state.get("base", 0) if self._role(holder, message) == "flood" else message.hops
            state.update(role="flood", attempt=attempt, base=base, ingress=holder.id)
            super().on_forward(message, holder, contact, forwarded_copy)
            return
        if self._forward_reason == "deposit":
            self._outbox[message.msg_id].couriers.add(contact.id)
            copies = self._courier_copies
        else:
            copies = message.routing_state["copies"] // 2
            message.routing_state["copies"] -= copies
            message.routing_state["sprayed"].add(contact.id)
        state.update(role="courier", copies=copies, sprayed=set(), giver=holder.id, tier=self._tier(holder, contact))
        self._carriers[(contact.id, forwarded_copy.msg_id)] = _NEVER

    def on_ble_config(self, ble_config) -> None:
        self._tick_s = ble_config.contact_check_interval_s
        self._airtime_bytes = ble_config.transfer_rate_bytes_per_s * ble_config.contact_check_interval_s

    def _component_sizes(self) -> Dict[int, int]:
        sizes: Dict[int, int] = {}
        for start in self._neighbors_by_node:
            if start in sizes:
                continue
            component = [start]
            seen = {start}
            for node_id in component:
                for n in self._neighbors_by_node.get(node_id, ()):
                    if n.id not in seen:
                        seen.add(n.id)
                        component.append(n.id)
            for node_id in component:
                sizes[node_id] = len(component)
        return sizes

    def control_broadcasts(self, now: float) -> Dict[int, int]:
        sizes = super().control_broadcasts(now)
        for node_id, load in self._announce_load.items():
            sizes[node_id] = int(min(self._airtime_bytes, sizes.get(node_id, 0) + load))
        return sizes

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        for node_id, msg_id in self._flush_now:
            self._nodes[node_id].buffer.pop(msg_id, None)
        self._flush_now = set()
        self._neighbors_by_node = neighbors_by_node
        self._neighbor_ids = {}
        self._reach = {}
        super().on_tick(now, neighbors_by_node)
        if now - self._last_announce >= self._announce_interval_s:
            self._last_announce = now
            per_tick = self._announce_bytes * self._tick_s / self._announce_interval_s
            self._announce_load = {node_id: size * per_tick for node_id, size in self._component_sizes().items()}
            self._announce_round(now)
        if now - self._last_maintenance >= self._maintenance_interval_s:
            self._last_maintenance = now
            self._flush_spools(now)

    def _announce_round(self, now: float) -> None:
        for msg_id, entry in list(self._outbox.items()):
            message = entry.source.buffer.get(msg_id)
            if message is None or self._role(entry.source, message) != "source":
                del self._outbox[msg_id]
                continue
            if entry.source.id not in self._announce_reach(message.dst_id):
                continue
            if now > entry.reachable_until:
                if entry.sends >= self._max_send_attempts:
                    entry.source.buffer.pop(msg_id, None)
                    del self._outbox[msg_id]
                    continue
                self._send(entry, message, now)
            entry.reachable_until = now + self._reachability_retention_s

        for (node_id, msg_id), handed_at in list(self._carriers.items()):
            message = self._nodes[node_id].buffer.get(msg_id)
            if message is None or message.routing_state.get("role") != "courier":
                del self._carriers[(node_id, msg_id)]
                continue
            if now - handed_at >= self._handover_cooldown_s and node_id in self._announce_reach(message.dst_id):
                self._carriers[(node_id, msg_id)] = now
                message.routing_state["attempt"] = ("courier", node_id, now)

    def _flush_spools(self, now: float) -> None:
        for node_id, spool in self._spool.items():
            node = self._nodes[node_id]
            for msg_id, spooled_at in list(spool.items()):
                message = node.buffer.get(msg_id)
                if message is None or now - spooled_at > self._spool_window_s:
                    del spool[msg_id]
                    node.buffer.pop(msg_id, None)
                    continue
                ingress = message.routing_state.get("ingress")
                if any(n.id != ingress for n in self._neighbors_by_node.get(node_id, ())):
                    del spool[msg_id]
                    self._flush_now.add((node_id, msg_id))
