import itertools
import random
import pytest
import simpy
from festival_ble_sim.config import TrafficConfig
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.traffic import generate_message, sample_interval_s, traffic_generator


def test_generate_message_payload_within_range():
    config = TrafficConfig(payload_size_range_bytes=(20, 30), message_ttl_s=60.0)
    rng = random.Random(1)
    msg = generate_message(msg_id=1, now=5.0, src_id=1, dst_id=2, config=config, rng=rng)
    assert 20 <= msg.size_bytes <= 30
    assert msg.ttl_s == 60.0
    assert msg.creation_time == 5.0
    assert msg.hops == 0


def test_sample_interval_s_average_matches_configured_mean():
    config = TrafficConfig(mean_interval_s=4.0)
    rng = random.Random(42)
    samples = [sample_interval_s(config, rng) for _ in range(5000)]
    mean = sum(samples) / len(samples)
    assert mean == pytest.approx(4.0, rel=0.15)


class _FakeNode:
    def __init__(self, node_id):
        self.id = node_id
        self.buffer = {}

    def store_message(self, message):
        self.buffer[message.msg_id] = message


def test_traffic_generator_creates_messages_over_time():
    env = simpy.Environment()
    nodes = {1: _FakeNode(1), 2: _FakeNode(2), 3: _FakeNode(3)}
    metrics = MetricsCollector()
    config = TrafficConfig(mean_interval_s=1.0, payload_size_range_bytes=(10, 10), message_ttl_s=100.0)
    id_gen = itertools.count(1)
    rng = random.Random(7)
    env.process(traffic_generator(env, nodes, config, metrics, id_gen, rng))
    env.run(until=20.0)
    total_buffered = sum(len(n.buffer) for n in nodes.values())
    report = metrics.build_report([], 0)
    assert report.messages_created > 0
    assert total_buffered == report.messages_created
