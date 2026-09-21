from __future__ import annotations
import random
from dataclasses import replace
from typing import Dict, List, Optional
from .config import BleConfig
from .energy import EnergyModel
from .metrics import MetricsCollector
from .models import Message
from .nodes import BaseNode, BeaconNode
from .routing.base import RoutingAlgorithm, RoutingDecision
from .spatial import SpatialGrid


def _purge_expired_messages(node: BaseNode, now: float) -> None:
    expired_ids = [mid for mid, m in node.buffer.items() if m.is_expired(now)]
    for mid in expired_ids:
        del node.buffer[mid]


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

    neighbors = grid.get_nearby(sender, sender.radio_range_m)

    # Real BLE stacks only sustain a handful of simultaneous GATT
    # connections; closer contacts (stronger link/RSSI proxy) win the slots.
    if ble_config is not None and ble_config.max_concurrent_links is not None:
        neighbors = sorted(neighbors, key=lambda n: sender.position.distance_to(n.position))
        neighbors = neighbors[: ble_config.max_concurrent_links]

    loss_prob = 0.0
    if ble_config is not None and neighbors:
        loss_prob = min(
            ble_config.packet_loss_max_probability,
            ble_config.packet_loss_base_probability
            + ble_config.packet_loss_congestion_coefficient * max(0, len(neighbors) - 1),
        )

    link_budget_bytes = None
    if ble_config is not None:
        link_budget_bytes = ble_config.transfer_rate_bytes_per_s * ble_config.contact_check_interval_s

    for contact in neighbors:
        if not contact.is_active:
            continue

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


def beacon_backhaul_relay(
    now: float,
    beacon_ids: List[int],
    nodes: Dict[int, BaseNode],
    snapshot: Dict[int, List[Message]],
    metrics: MetricsCollector,
) -> None:
    # Simulates a reliable WiFi/wired backhaul between fixed beacons: no
    # radio-range check, no BLE bandwidth/contention/loss. Reads only the
    # pre-tick snapshot and writes into other beacons' live buffers, so a
    # message relayed here only becomes visible for further relay (BLE or
    # backhaul) starting next tick — preserving the tick-snapshot invariant.
    if len(beacon_ids) < 2:
        return
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
    rng: Optional[random.Random] = None,
):
    beacon_ids = [node_id for node_id, node in nodes.items() if isinstance(node, BeaconNode)]
    while True:
        yield env.timeout(contact_check_interval_s)
        now = env.now
        snapshot = {node_id: list(node.buffer.values()) for node_id, node in nodes.items()}
        beacon_backhaul_relay(now, beacon_ids, nodes, snapshot, metrics)
        for node_id, sender in list(nodes.items()):
            process_node_contacts(
                now, sender, grid, routing_algorithm, energy_model, metrics,
                messages=snapshot[node_id],
                ble_config=ble_config,
                rng=rng,
            )
