import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=20.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.5, rx_cost_mah_per_byte=0.0)
    )


def test_hop_exhausted_message_is_not_relayed_to_a_non_destination_contact():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=4, ttl_hops=4)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is False
    assert metrics.build_report([], 0).total_transmissions == 0


def test_hop_exhausted_message_is_still_delivered_directly_to_destination():
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=4, ttl_hops=4)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert dest.has_message(1) is True
    assert metrics.build_report([], 0).messages_delivered == 1


def test_message_below_hop_limit_still_relays_normally():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=2, ttl_hops=4)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is True
    assert relay.buffer[1].hops == 3


def test_unlimited_ttl_hops_never_blocks_relay():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=500, ttl_hops=None)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is True
