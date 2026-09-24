import random
import pytest
import simpy
from festival_ble_sim.config import BleConfig, EnergyConfig
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


def _no_signal_or_congestion_loss():
    return dict(
        packet_loss_base_probability=0.0,
        packet_loss_congestion_coefficient=0.0,
        weak_signal_max_probability=0.0,
        packet_loss_max_probability=1.0,
    )


def test_sender_with_no_other_transmitters_never_backs_off():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0, **_no_signal_or_congestion_loss())
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
        rng=random.Random(0), contention_counts={1: 0, 2: 0},
    )
    assert contact.has_message(1) is True
    assert metrics.build_report([], 0).backoff_count == 0


def test_sender_always_backs_off_when_backoff_probability_is_one():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0, **_no_signal_or_congestion_loss())
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
        rng=random.Random(0), contention_counts={1: 3, 2: 0},
    )
    assert contact.has_message(1) is False
    assert 1 in sender.buffer
    report = metrics.build_report([], 0)
    assert report.backoff_count == 1
    assert report.total_transmissions == 0
    assert sender.battery_mah == pytest.approx(100.0)


def test_backoff_consumes_no_energy_and_records_no_packet_loss():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0, **_no_signal_or_congestion_loss())
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
        rng=random.Random(0), contention_counts={1: 5, 2: 0},
    )
    report = metrics.build_report([], 0)
    assert report.packet_loss_count == 0
    assert sender.battery_mah == pytest.approx(100.0)


def test_collision_loss_increases_with_receiver_side_contention():
    ble_config = BleConfig(
        relay_backoff_coefficient=0.0,
        collision_loss_coefficient=0.2,
        collision_loss_max_probability=1.0,
        **_no_signal_or_congestion_loss(),
    )

    def _loss_rate(contact_contention: int, trials: int) -> float:
        losses = 0
        for seed in range(trials):
            sender = _node(1, 0.0, 0.0)
            contact = _node(2, 5.0, 0.0)
            grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
            grid.insert(sender)
            grid.insert(contact)
            msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
            sender.store_message(msg)
            process_node_contacts(
                now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
                energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
                rng=random.Random(seed), contention_counts={1: 0, 2: contact_contention},
            )
            if not contact.has_message(1):
                losses += 1
        return losses / trials

    quiet_loss_rate = _loss_rate(contact_contention=1, trials=200)
    busy_loss_rate = _loss_rate(contact_contention=4, trials=200)

    assert quiet_loss_rate == pytest.approx(0.0)
    assert busy_loss_rate > quiet_loss_rate
    assert busy_loss_rate == pytest.approx(0.6, abs=0.1)


def test_no_contention_counts_disables_backoff_and_collision():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0, **_no_signal_or_congestion_loss())
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
        rng=random.Random(0), contention_counts=None,
    )
    assert contact.has_message(1) is True
    assert metrics.build_report([], 0).backoff_count == 0


def test_network_engine_computes_contention_from_live_buffers():
    # Five nodes clustered together, each with a message to send: every
    # sender should see the other four as contention, driving backoff_count
    # up over a run with a non-trivial backoff coefficient.
    env = simpy.Environment()
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    nodes = {}
    for i in range(1, 6):
        node = _node(i, float(i), 0.0)
        node.store_message(
            Message(msg_id=i, src_id=i, dst_id=999, size_bytes=10, creation_time=0.0, ttl_s=1000.0)
        )
        nodes[i] = node
        grid.insert(node)
    metrics = MetricsCollector()
    ble_config = BleConfig(
        relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0, **_no_signal_or_congestion_loss()
    )
    env.process(
        network_engine(
            env, nodes, grid, EpidemicRouting(), _energy_model(), metrics,
            contact_check_interval_s=1.0, ble_config=ble_config, rng=random.Random(0),
        )
    )
    env.run(until=1.5)
    assert metrics.build_report([], 0).backoff_count == 5
