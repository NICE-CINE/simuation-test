import random
import pytest
import simpy
from festival_ble_sim.config import BeaconConfig, EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import beacon_backhaul_relay, network_engine
from festival_ble_sim.nodes import BaseNode, BeaconNode
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.spatial import SpatialGrid


def _beacon(node_id, x, y, buffer_capacity=10):
    return BeaconNode(node_id=node_id, position=Position(x, y), radio_range_m=5.0, buffer_capacity=buffer_capacity)


def _phone(node_id, x, y, buffer_capacity=10, battery=100.0):
    return BaseNode(node_id=node_id, position=Position(x, y), radio_range_m=5.0, buffer_capacity=buffer_capacity, battery_mah=battery)


def _energy_model():
    return EnergyModel(EnergyConfig())


def test_beacon_backhaul_relays_out_of_radio_range_within_one_tick():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    c = _beacon(3, 1000.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0, hops=0)
    a.store_message(msg)
    nodes = {1: a, 2: b, 3: c}
    snapshot = {node_id: list(node.buffer.values()) for node_id, node in nodes.items()}
    metrics = MetricsCollector()
    beacon_backhaul_relay(now=1.0, beacon_ids=[1, 2, 3], nodes=nodes, snapshot=snapshot, metrics=metrics)
    assert b.has_message(1) is True
    assert c.has_message(1) is True
    assert b.buffer[1].hops == 0
    assert c.buffer[1].hops == 0
    assert metrics.build_report([], 0).backhaul_transmissions == 2


def test_backhaul_does_not_leak_within_same_tick_to_unrelated_phone():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    phone = _phone(3, 502.0, 0.0)  # in BLE range of b, not of a
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b, 3: phone}
    grid = SpatialGrid(1000.0, 1000.0, cell_size_m=5.0)
    grid.insert(a)
    grid.insert(b)
    grid.insert(phone)
    env = simpy.Environment()
    metrics = MetricsCollector()
    env.process(
        network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, contact_check_interval_s=1.0)
    )
    env.run(until=1.5)
    # b received the message via backhaul this tick, but its own BLE contact
    # processing this same tick only saw its pre-tick (empty) buffer.
    assert b.has_message(1) is True
    assert phone.has_message(1) is False
    env.run(until=2.5)
    assert phone.has_message(1) is True


def test_backhaul_noop_with_fewer_than_two_beacons():
    a = _beacon(1, 0.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a}
    snapshot = {1: list(a.buffer.values())}
    metrics = MetricsCollector()
    beacon_backhaul_relay(now=1.0, beacon_ids=[1], nodes=nodes, snapshot=snapshot, metrics=metrics)
    assert metrics.build_report([], 0).backhaul_transmissions == 0


def test_backhaul_skips_expired_messages():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=5.0)
    a.buffer[1] = msg
    nodes = {1: a, 2: b}
    snapshot = {1: [msg], 2: []}
    metrics = MetricsCollector()
    beacon_backhaul_relay(now=100.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=metrics)
    assert b.has_message(1) is False


def test_high_latency_makes_immediate_relay_the_rare_case():
    # contact_check_interval_s=1.0 vs backhaul_latency_s=100.0 -> attempt
    # probability 0.01 per tick: across many independent single-tick calls,
    # only a small minority should relay right away.
    beacon_config = BeaconConfig(backhaul_latency_s=100.0)
    relayed = 0
    trials = 300
    for seed in range(trials):
        a = _beacon(1, 0.0, 0.0)
        b = _beacon(2, 500.0, 0.0)
        msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
        a.store_message(msg)
        nodes = {1: a, 2: b}
        snapshot = {1: list(a.buffer.values()), 2: []}
        beacon_backhaul_relay(
            now=1.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=MetricsCollector(),
            contact_check_interval_s=1.0, beacon_config=beacon_config, rng=random.Random(seed),
        )
        if b.has_message(1):
            relayed += 1
    assert relayed / trials == pytest.approx(0.01, abs=0.03)


def test_low_latency_relative_to_tick_still_relays_immediately():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b}
    snapshot = {1: list(a.buffer.values()), 2: []}
    metrics = MetricsCollector()
    beacon_config = BeaconConfig(backhaul_latency_s=0.01)
    beacon_backhaul_relay(
        now=1.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=metrics,
        contact_check_interval_s=1.0, beacon_config=beacon_config, rng=random.Random(0),
    )
    assert b.has_message(1) is True


def test_guaranteed_backhaul_loss_prevents_delivery_and_is_recorded():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b}
    snapshot = {1: list(a.buffer.values()), 2: []}
    metrics = MetricsCollector()
    beacon_config = BeaconConfig(backhaul_loss_probability=1.0)
    beacon_backhaul_relay(
        now=1.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=metrics,
        contact_check_interval_s=1.0, beacon_config=beacon_config, rng=random.Random(0),
    )
    assert b.has_message(1) is False
    report = metrics.build_report([], 0)
    assert report.backhaul_loss_count == 1
    assert report.backhaul_transmissions == 0


def test_zero_backhaul_loss_probability_never_drops_with_rng():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b}
    snapshot = {1: list(a.buffer.values()), 2: []}
    metrics = MetricsCollector()
    beacon_config = BeaconConfig(backhaul_loss_probability=0.0)
    beacon_backhaul_relay(
        now=1.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=metrics,
        contact_check_interval_s=1.0, beacon_config=beacon_config, rng=random.Random(0),
    )
    assert b.has_message(1) is True
    assert metrics.build_report([], 0).backhaul_loss_count == 0


def test_no_beacon_config_or_rng_preserves_prior_instant_reliable_behavior():
    a = _beacon(1, 0.0, 0.0)
    b = _beacon(2, 500.0, 0.0)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
    a.store_message(msg)
    nodes = {1: a, 2: b}
    snapshot = {1: list(a.buffer.values()), 2: []}
    metrics = MetricsCollector()
    beacon_backhaul_relay(now=1.0, beacon_ids=[1, 2], nodes=nodes, snapshot=snapshot, metrics=metrics)
    assert b.has_message(1) is True
