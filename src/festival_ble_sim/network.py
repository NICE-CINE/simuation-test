from __future__ import annotations
from dataclasses import replace
from typing import Dict, List, Optional
from .energy import EnergyModel
from .metrics import MetricsCollector
from .models import Message
from .nodes import BaseNode
from .routing.base import RoutingAlgorithm, RoutingDecision
from .spatial import SpatialGrid


def process_node_contacts(
    now: float,
    sender: BaseNode,
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    messages: Optional[List[Message]] = None,
) -> None:
    expired_ids = [mid for mid, m in sender.buffer.items() if m.is_expired(now)]
    for mid in expired_ids:
        del sender.buffer[mid]

    if not sender.buffer or not sender.is_active:
        return

    # Process only what sender held at tick start (or what the caller
    # passes explicitly). A message received from another node earlier
    # in this same tick must wait until next tick to be relayed further
    # — otherwise propagation speed depends on node iteration order.
    if messages is None:
        messages = list(sender.buffer.values())

    neighbors = grid.get_nearby(sender, sender.radio_range_m)
    for contact in neighbors:
        if not contact.is_active:
            continue

        for message in messages:
            if message.msg_id not in sender.buffer:
                continue
            if not contact.is_active:
                break

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

            decision = routing_algorithm.decide(message, sender, contact)
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


def network_engine(
    env,
    nodes: Dict[int, BaseNode],
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    contact_check_interval_s: float,
):
    while True:
        yield env.timeout(contact_check_interval_s)
        now = env.now
        snapshot = {node_id: list(node.buffer.values()) for node_id, node in nodes.items()}
        for node_id, sender in list(nodes.items()):
            process_node_contacts(
                now, sender, grid, routing_algorithm, energy_model, metrics,
                messages=snapshot[node_id],
            )
