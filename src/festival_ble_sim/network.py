from __future__ import annotations
import random
from dataclasses import replace
from typing import Any, Dict, List, Optional
from .config import BeaconConfig, BleConfig
from .energy import EnergyModel
from .metrics import MetricsCollector
from .models import Message
from .nodes import BaseNode, BeaconNode
from .radio import link_margin_db
from .routing.base import RoutingAlgorithm, RoutingDecision
from .spatial import SpatialGrid


def _purge_expired_messages(node: BaseNode, now: float) -> None:
    expired_ids = [mid for mid, m in node.buffer.items() if m.is_expired(now)]
    for mid in expired_ids:
        del node.buffer[mid]


def _compute_contention_counts(
    nodes: Dict[int, BaseNode], grid: SpatialGrid, snapshot: Dict[int, List[Message]]
) -> Dict[int, int]:
    # For each active node, how many other nodes within ITS OWN radio range
    # have something to send this tick — a proxy for the local shared-medium
    # activity a real BLE radio would sense. Used both for the sender's own
    # channel-sense backoff and for the receiver's hidden-terminal collision
    # risk (see process_node_contacts).
    counts: Dict[int, int] = {}
    for node_id, node in nodes.items():
        if not node.is_active:
            counts[node_id] = 0
            continue
        neighbors = grid.get_nearby(node, node.radio_range_m)
        counts[node_id] = sum(1 for n in neighbors if n.is_active and snapshot.get(n.id))
    return counts


def _weak_signal_loss_probability(margin_db: float, ble_config: BleConfig) -> float:
    # Fades from 0 loss at/above the cutoff margin to weak_signal_max_probability
    # right at the receiver sensitivity floor (0 dB margin): a link near the
    # edge of range drops more packets than one deep inside it, on top of
    # (not instead of) congestion-driven loss.
    cutoff = ble_config.signal_margin_cutoff_db
    if margin_db >= cutoff:
        return 0.0
    if margin_db <= 0.0:
        return ble_config.weak_signal_max_probability
    return ble_config.weak_signal_max_probability * (1.0 - margin_db / cutoff)


def process_node_contacts(
    now: float,
    sender: BaseNode,
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    messages: Optional[List[Message]] = None,
    ble_config: Optional[BleConfig] = None,
    rng: Optional[random.Random] = None,
    contention_counts: Optional[Dict[int, int]] = None,
    event_log: Optional[List[Dict[str, Any]]] = None,
) -> None:
    _purge_expired_messages(sender, now)

    if not sender.buffer or not sender.is_active:
        return

    # Process only what sender held at tick start (or what the caller
    # passes explicitly). A message received from another node earlier
    # in this same tick must wait until next tick to be relayed further
    # — otherwise propagation speed depends on node iteration order.
    if messages is None:
        messages = list(sender.buffer.values())

    # CSMA-style channel sensing: back off (skip this whole tick, retry
    # next one) before spending any energy or attempting a transmission,
    # with a probability that grows with how many other nodes the sender
    # can itself hear trying to send this tick.
    if ble_config is not None and rng is not None and contention_counts is not None:
        other_transmitters = contention_counts.get(sender.id, 0)
        if other_transmitters > 0:
            backoff_prob = min(
                ble_config.relay_backoff_max_probability,
                ble_config.relay_backoff_coefficient * other_transmitters,
            )
            if rng.random() < backoff_prob:
                metrics.record_backoff()
                return

    neighbors = grid.get_nearby(sender, sender.radio_range_m)

    # Real BLE stacks only sustain a handful of simultaneous GATT
    # connections; closer contacts (stronger link/RSSI proxy) win the slots.
    if ble_config is not None and ble_config.max_concurrent_links is not None:
        neighbors = sorted(neighbors, key=lambda n: sender.position.distance_to(n.position))
        neighbors = neighbors[: ble_config.max_concurrent_links]

    congestion_loss_prob = 0.0
    if ble_config is not None and neighbors:
        congestion_loss_prob = (
            ble_config.packet_loss_base_probability
            + ble_config.packet_loss_congestion_coefficient * max(0, len(neighbors) - 1)
        )

    radio = None
    if ble_config is not None:
        radio = ble_config.beacon_radio if sender.is_beacon else ble_config.phone_radio

    link_budget_bytes = None
    if ble_config is not None:
        link_budget_bytes = ble_config.transfer_rate_bytes_per_s * ble_config.contact_check_interval_s

    for contact in neighbors:
        if not contact.is_active:
            continue

        loss_prob = 0.0
        if ble_config is not None:
            distance_m = sender.position.distance_to(contact.position)
            # Shadowing (see radio.RadioParams.shadowing_std_db) makes this
            # a stochastic per-tick sample, not a fixed function of
            # distance: an unlucky fade can push the actual received power
            # below the sensitivity floor even inside the deterministic
            # max range used to shortlist `neighbors` above, in which case
            # reception is treated as guaranteed lost this tick — same
            # loss/energy accounting path as any other packet loss below.
            margin_db = link_margin_db(distance_m, radio, rng)
            if margin_db < 0.0:
                # A true outage isn't a "soft" loss source: it bypasses
                # packet_loss_max_probability entirely, since a signal
                # below the noise floor can't be received no matter how
                # that cap is configured.
                loss_prob = 1.0
            else:
                weak_signal_loss_prob = _weak_signal_loss_probability(margin_db, ble_config)

                collision_loss_prob = 0.0
                if contention_counts is not None:
                    other_transmitters = max(0, contention_counts.get(contact.id, 0) - 1)
                    collision_loss_prob = min(
                        ble_config.collision_loss_max_probability,
                        ble_config.collision_loss_coefficient * other_transmitters,
                    )

                loss_prob = min(
                    ble_config.packet_loss_max_probability,
                    congestion_loss_prob + weak_signal_loss_prob + collision_loss_prob,
                )

        remaining_budget = link_budget_bytes

        for message in messages:
            if message.msg_id not in sender.buffer:
                continue
            if not contact.is_active:
                break

            if remaining_budget is not None and message.size_bytes > remaining_budget:
                # Doesn't fit this tick's link budget; stays queued, retried next tick.
                continue
            if remaining_budget is not None:
                remaining_budget -= message.size_bytes

            if rng is not None and loss_prob > 0.0 and rng.random() < loss_prob:
                sender.consume_energy(energy_model.cost_of_tx(message.size_bytes))
                metrics.record_packet_loss()
                continue

            if contact.id == message.dst_id:
                if not contact.has_message(message.msg_id):
                    delivered_msg = replace(
                        message,
                        hops=message.hops + 1,
                        routing_state=dict(message.routing_state),
                    )
                    contact.mark_delivered(delivered_msg.msg_id)
                    sender.consume_energy(energy_model.cost_of_tx(message.size_bytes))
                    contact.consume_energy(energy_model.cost_of_rx(message.size_bytes))
                    metrics.record_transmission()
                    metrics.record_delivery(delivered_msg, now)
                    routing_algorithm.on_delivered(delivered_msg, sender)
                    if event_log is not None:
                        event_log.append({"time": now, "from": sender.id, "to": contact.id, "delivered": True})
                continue

            # Network-layer hop TTL only caps relaying, not direct delivery
            # (handled above): a holder still carries and can hand off a
            # hop-exhausted message straight to its destination, it just
            # stops spreading it to other relays — the same "wait phase"
            # semantics Spray & Wait already uses for its last copy.
            if message.hop_limit_reached():
                continue

            decision = routing_algorithm.decide(message, sender, contact, now)
            if decision is RoutingDecision.FORWARD:
                forwarded = replace(
                    message,
                    hops=message.hops + 1,
                    routing_state=dict(message.routing_state),
                )
                contact.store_message(forwarded)
                sender.consume_energy(energy_model.cost_of_tx(message.size_bytes))
                contact.consume_energy(energy_model.cost_of_rx(message.size_bytes))
                metrics.record_transmission()
                routing_algorithm.on_forward(message, sender, contact, forwarded)
                if event_log is not None:
                    event_log.append({"time": now, "from": sender.id, "to": contact.id, "delivered": False})


def beacon_backhaul_relay(
    now: float,
    beacon_ids: List[int],
    nodes: Dict[int, BaseNode],
    snapshot: Dict[int, List[Message]],
    metrics: MetricsCollector,
    contact_check_interval_s: float = 1.0,
    beacon_config: Optional[BeaconConfig] = None,
    rng: Optional[random.Random] = None,
) -> None:
    # Simulates a WiFi/wired backhaul between fixed beacons: no radio-range
    # check, no BLE bandwidth/contention, and (like the hop count it
    # deliberately never increments) no BLE mesh network-layer hop TTL
    # either — it's a separate wired backbone, not a mesh relay. It isn't
    # perfectly instant or lossless though: see BeaconConfig.backhaul_latency_s
    # / backhaul_loss_probability. Reads only the pre-tick snapshot and
    # writes into other beacons' live buffers, so a message relayed here
    # only becomes visible for further relay (BLE or backhaul) starting
    # next tick — preserving the tick-snapshot invariant. A message not yet
    # attempted (still "in flight") or lost this tick is retried
    # automatically next tick, since the source still holds it and the
    # target still doesn't.
    if len(beacon_ids) < 2:
        return

    attempt_prob = 1.0
    loss_prob = 0.0
    if beacon_config is not None:
        attempt_prob = min(1.0, contact_check_interval_s / beacon_config.backhaul_latency_s)
        loss_prob = beacon_config.backhaul_loss_probability

    for src_id in beacon_ids:
        source = nodes[src_id]
        if not source.is_active:
            continue
        for message in snapshot[src_id]:
            if message.msg_id not in source.buffer or message.is_expired(now):
                continue
            for dst_id in beacon_ids:
                if dst_id == src_id:
                    continue
                target = nodes[dst_id]
                if not target.is_active or target.has_message(message.msg_id):
                    continue
                if rng is not None and attempt_prob < 1.0 and rng.random() >= attempt_prob:
                    continue
                if rng is not None and loss_prob > 0.0 and rng.random() < loss_prob:
                    metrics.record_backhaul_loss()
                    continue
                relayed = replace(message, routing_state=dict(message.routing_state))
                target.store_message(relayed)
                metrics.record_backhaul_transmission()


def network_engine(
    env,
    nodes: Dict[int, BaseNode],
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    contact_check_interval_s: float,
    ble_config: Optional[BleConfig] = None,
    beacon_config: Optional[BeaconConfig] = None,
    rng: Optional[random.Random] = None,
    event_log: Optional[List[Dict[str, Any]]] = None,
):
    beacon_ids = [node_id for node_id, node in nodes.items() if isinstance(node, BeaconNode)]
    while True:
        yield env.timeout(contact_check_interval_s)
        now = env.now
        snapshot = {node_id: list(node.buffer.values()) for node_id, node in nodes.items()}
        beacon_backhaul_relay(
            now, beacon_ids, nodes, snapshot, metrics,
            contact_check_interval_s=contact_check_interval_s,
            beacon_config=beacon_config,
            rng=rng,
        )
        contention_counts = _compute_contention_counts(nodes, grid, snapshot) if ble_config is not None else None
        for node_id, sender in list(nodes.items()):
            process_node_contacts(
                now, sender, grid, routing_algorithm, energy_model, metrics,
                messages=snapshot[node_id],
                ble_config=ble_config,
                rng=rng,
                contention_counts=contention_counts,
                event_log=event_log,
            )
