import pytest
import simpy
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import network_engine, process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=20.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.5, rx_cost_mah_per_byte=0.0)
    )


def test_direct_delivery_to_destination():
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert dest.has_message(1) is True
    report = metrics.build_report([], 0)
    assert report.messages_delivered == 1
    assert sender.battery_mah == pytest.approx(99.0)
    assert dest.battery_mah == pytest.approx(99.5)


def test_relay_forward_increments_hops_without_mutating_senders_copy():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0, hops=0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is True
    assert relay.buffer[1].hops == 1
    assert sender.buffer[1].hops == 0
    assert metrics.build_report([], 0).total_transmissions == 1


def test_expired_message_is_purged_before_contact_check():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=10.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=100.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert 1 not in sender.buffer
    assert relay.has_message(1) is False


def test_inactive_contact_is_skipped():
    sender = _node(1, 0.0, 0.0)
    relay = _node(2, 5.0, 0.0)
    relay.is_active = False
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is False


def test_inactive_sender_is_skipped():
    sender = _node(1, 0.0, 0.0)
    sender.is_active = False
    relay = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(relay)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.buffer[1] = msg
    metrics = MetricsCollector()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=metrics)
    assert relay.has_message(1) is False


def test_network_engine_delivers_after_one_interval():
    env = simpy.Environment()
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    sender.store_message(msg)
    nodes = {1: sender, 2: dest}
    metrics = MetricsCollector()
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, contact_check_interval_s=5.0))
    env.run(until=4.0)
    assert dest.has_message(1) is False
    env.run(until=6.0)
    assert dest.has_message(1) is True


def test_network_engine_two_hop_relay_takes_two_intervals():
    env = simpy.Environment()
    a = _node(1, 0.0, 0.0)
    b = _node(2, 15.0, 0.0)
    c = _node(3, 30.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(a)
    grid.insert(b)
    grid.insert(c)
    msg = Message(msg_id=1, src_id=1, dst_id=3, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b, 3: c}
    metrics = MetricsCollector()
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, contact_check_interval_s=5.0))
    env.run(until=7.0)
    assert c.has_message(1) is False
    env.run(until=11.0)
    assert c.has_message(1) is True
    report = metrics.build_report([], 0)
    assert report.messages_delivered == 1
    assert report.avg_hops == pytest.approx(2.0)
