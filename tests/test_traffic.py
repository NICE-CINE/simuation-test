import itertools
import random
import pytest
import simpy
from festival_ble_sim.config import TrafficConfig
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.traffic import (
    generate_message,
    sample_interval_s,
    sample_message_rate_per_hour,
    traffic_process,
)


def test_generate_message_payload_within_range():
    config = TrafficConfig(payload_size_range_bytes=(20, 30), message_ttl_s=60.0)
    rng = random.Random(1)
    msg = generate_message(msg_id=1, now=5.0, src_id=1, dst_id=2, config=config, rng=rng)
    assert 20 <= msg.size_bytes <= 30
    assert msg.ttl_s == 60.0
    assert msg.creation_time == 5.0
    assert msg.hops == 0


def test_generate_message_carries_configured_ttl_hops():
    config = TrafficConfig(payload_size_range_bytes=(20, 30), message_ttl_hops=6)
    msg = generate_message(msg_id=1, now=5.0, src_id=1, dst_id=2, config=config, rng=random.Random(1))
    assert msg.ttl_hops == 6


def test_generate_message_ttl_hops_none_means_unlimited():
    config = TrafficConfig(payload_size_range_bytes=(20, 30), message_ttl_hops=None)
    msg = generate_message(msg_id=1, now=5.0, src_id=1, dst_id=2, config=config, rng=random.Random(1))
    assert msg.ttl_hops is None


def test_sample_message_rate_per_hour_stays_within_configured_range():
    config = TrafficConfig(messages_per_hour_range=(0.5, 2.0))
    rng = random.Random(42)
    samples = [sample_message_rate_per_hour(config, rng) for _ in range(2000)]
    assert all(0.5 <= s <= 2.0 for s in samples)
    mean = sum(samples) / len(samples)
    assert mean == pytest.approx(1.25, rel=0.15)


def test_sample_interval_s_average_matches_rate():
    rng = random.Random(42)
    rate_per_hour = 720.0  # one message every 5s on average
    samples = [sample_interval_s(rate_per_hour, rng) for _ in range(5000)]
    mean = sum(samples) / len(samples)
    assert mean == pytest.approx(5.0, rel=0.15)


def _FakeNode(node_id):
    return BaseNode(node_id, Position(float(node_id), 0.0), radio_range_m=10.0, buffer_capacity=1000, battery_mah=100.0)


def _run_traffic(nodes, config, until=20.0, seed=7):
    env = simpy.Environment()
    metrics = MetricsCollector()
    env.process(traffic_process(env, nodes[1], nodes, config, metrics, itertools.count(1), random.Random(seed)))
    env.run(until=until)
    return metrics.build_report([], 0)


_FAST = dict(messages_per_hour_range=(3600.0, 3600.0), payload_size_range_bytes=(10, 10), message_ttl_s=100.0)


def test_traffic_process_creates_messages_over_time():
    env = simpy.Environment()
    nodes = {1: _FakeNode(1), 2: _FakeNode(2), 3: _FakeNode(3)}
    metrics = MetricsCollector()
    config = TrafficConfig(
        messages_per_hour_range=(3600.0, 3600.0), payload_size_range_bytes=(10, 10), message_ttl_s=100.0,
        friends_only=False,
    )
    id_gen = itertools.count(1)
    rng = random.Random(7)
    env.process(traffic_process(env, nodes[1], nodes, config, metrics, id_gen, rng))
    env.run(until=20.0)
    report = metrics.build_report([], 0)
    assert report.messages_created > 0
    assert len(nodes[1].buffer) == report.messages_created


def test_traffic_process_zero_rate_creates_no_messages():
    env = simpy.Environment()
    nodes = {1: _FakeNode(1), 2: _FakeNode(2)}
    metrics = MetricsCollector()
    config = TrafficConfig(messages_per_hour_range=(0.0, 0.0), payload_size_range_bytes=(10, 10))
    id_gen = itertools.count(1)
    rng = random.Random(1)
    env.process(traffic_process(env, nodes[1], nodes, config, metrics, id_gen, rng))
    env.run(until=1000.0)
    report = metrics.build_report([], 0)
    assert report.messages_created == 0


def test_traffic_process_requires_another_active_node():
    env = simpy.Environment()
    nodes = {1: _FakeNode(1)}
    metrics = MetricsCollector()
    config = TrafficConfig(messages_per_hour_range=(3600.0, 3600.0), payload_size_range_bytes=(10, 10), friends_only=False)
    id_gen = itertools.count(1)
    rng = random.Random(1)
    env.process(traffic_process(env, nodes[1], nodes, config, metrics, id_gen, rng))
    env.run(until=20.0)
    report = metrics.build_report([], 0)
    assert report.messages_created == 0


def test_traffic_process_only_writes_to_friends():
    nodes = {i: _FakeNode(i) for i in range(1, 6)}
    nodes[1].friends = {3}
    report = _run_traffic(nodes, TrafficConfig(**_FAST))
    assert report.messages_created > 0
    assert {m.dst_id for m in nodes[1].buffer.values()} == {3}


def test_traffic_process_friendless_node_sends_nothing():
    nodes = {i: _FakeNode(i) for i in range(1, 6)}
    assert _run_traffic(nodes, TrafficConfig(**_FAST)).messages_created == 0


def test_traffic_process_carries_src_gps_and_last_known_dst_position():
    nodes = {1: _FakeNode(1), 2: _FakeNode(2)}
    nodes[1].friends = {2}
    nodes[1].record_known_position(2, Position(42.0, 7.0), 3.0)
    _run_traffic(nodes, TrafficConfig(**_FAST))
    for message in nodes[1].buffer.values():
        assert message.src_position == Position(1.0, 0.0)
        assert message.dst_position == Position(42.0, 7.0)
        assert message.dst_position_time == 3.0


def test_traffic_process_unknown_dst_position_is_none():
    nodes = {1: _FakeNode(1), 2: _FakeNode(2)}
    nodes[1].friends = {2}
    _run_traffic(nodes, TrafficConfig(**_FAST))
    assert nodes[1].buffer
    assert all(m.dst_position is None for m in nodes[1].buffer.values())
