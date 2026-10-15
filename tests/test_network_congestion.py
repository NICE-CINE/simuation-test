import random
import pytest
from festival_ble_sim.config import BleConfig, EnergyConfig
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


def test_message_too_large_for_link_budget_stays_queued():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=1000, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(transfer_rate_bytes_per_s=100.0, contact_check_interval_s=1.0)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
    )
    assert contact.has_message(1) is False
    assert 1 in sender.buffer
    assert metrics.build_report([], 0).total_transmissions == 0


def test_message_fitting_link_budget_is_forwarded():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(transfer_rate_bytes_per_s=100.0, contact_check_interval_s=1.0)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
    )
    assert contact.has_message(1) is True


def test_max_concurrent_links_prioritizes_closest_contact():
    sender = _node(1, 0.0, 0.0)
    near = _node(2, 5.0, 0.0)
    far = _node(3, 15.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(near)
    grid.insert(far)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(max_concurrent_links=1)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
    )
    assert near.has_message(1) is True
    assert far.has_message(1) is False


def test_no_link_limit_services_every_neighbor():
    sender = _node(1, 0.0, 0.0)
    near = _node(2, 5.0, 0.0)
    far = _node(3, 15.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(near)
    grid.insert(far)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(max_concurrent_links=None)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config,
    )
    assert near.has_message(1) is True
    assert far.has_message(1) is True


def test_packet_loss_prevents_forward_but_consumes_tx_energy_only():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(packet_loss_base_probability=1.0, packet_loss_max_probability=1.0)
    rng = random.Random(0)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config, rng=rng,
    )
    assert contact.has_message(1) is False
    assert 1 in sender.buffer
    report = metrics.build_report([], 0)
    assert report.packet_loss_count == 1
    assert report.total_transmissions == 0
    assert sender.battery_mah == pytest.approx(99.0)
    assert contact.battery_mah == pytest.approx(100.0)


def test_weak_signal_near_edge_of_range_loses_more_than_close_contact():
    ble_config = BleConfig(packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0)

    def _loss_rate(contact_x: float, trials: int) -> float:
        losses = 0
        for seed in range(trials):
            sender = _node(1, 0.0, 0.0, buffer_capacity=10)
            sender.radio_range_m = 1000.0
            contact = _node(2, contact_x, 0.0, buffer_capacity=10)
            grid = SpatialGrid(2000.0, 2000.0, cell_size_m=1000.0)
            grid.insert(sender)
            grid.insert(contact)
            msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
            sender.store_message(msg)
            process_node_contacts(
                now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
                energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=ble_config,
                rng=random.Random(seed),
            )
            if not contact.has_message(1):
                losses += 1
        return losses / trials

    near_loss_rate = _loss_rate(contact_x=1.0, trials=200)
    far_loss_rate = _loss_rate(contact_x=29.5, trials=200)

    assert near_loss_rate < 0.05
    assert far_loss_rate > 0.15
    assert far_loss_rate > near_loss_rate


def test_zero_packet_loss_probability_never_drops_with_rng():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    metrics = MetricsCollector()
    ble_config = BleConfig(
        packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0, weak_signal_max_probability=0.0
    )
    rng = random.Random(0)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config, rng=rng,
    )
    assert contact.has_message(1) is True
    assert metrics.build_report([], 0).packet_loss_count == 0


def test_message_routing_ignores_costs_no_energy_or_loss_even_on_lossy_link():
    sender = _node(1, 0.0, 0.0)
    contact = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0)
    sender.store_message(msg)
    contact.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    ble_config = BleConfig(packet_loss_base_probability=1.0, packet_loss_max_probability=1.0)
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics, ble_config=ble_config, rng=random.Random(0),
    )
    assert sender.battery_mah == 100.0
    assert metrics.build_report([], 0).packet_loss_count == 0


def test_link_budget_is_shared_by_all_of_a_senders_links():
    sender = _node(1, 0.0, 0.0)
    a, b = _node(2, 5.0, 0.0), _node(3, 0.0, 5.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in (sender, a, b):
        grid.insert(n)
    sender.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=60, creation_time=0.0, ttl_s=100.0))
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=MetricsCollector(),
        ble_config=BleConfig(transfer_rate_bytes_per_s=100.0, contact_check_interval_s=1.0),
    )
    assert [a.has_message(1), b.has_message(1)].count(True) == 1


def test_link_budget_is_shared_by_all_of_a_receivers_senders_in_one_tick():
    import simpy
    from festival_ble_sim.network import network_engine
    s1, s2, receiver = _node(1, 0.0, 0.0), _node(2, 30.0, 0.0), _node(3, 15.0, 0.0)
    nodes = {1: s1, 2: s2, 3: receiver}
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in nodes.values():
        grid.insert(n)
    s1.store_message(Message(msg_id=1, src_id=1, dst_id=3, size_bytes=60, creation_time=0.0, ttl_s=100.0))
    s2.store_message(Message(msg_id=2, src_id=2, dst_id=3, size_bytes=60, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    env = simpy.Environment()
    ble = BleConfig(transfer_rate_bytes_per_s=100.0, contact_check_interval_s=1.0, connection_setup_s=0.0)
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, 1.0, ble_config=ble))
    env.run(until=1.5)
    assert metrics.build_report([], 0).messages_delivered == 1
    env.run(until=2.5)
    assert metrics.build_report([], 0).messages_delivered == 2


def test_beacon_cannot_link_to_a_phone_that_cannot_answer():
    beacon = BaseNode(node_id=1, position=Position(0.0, 0.0), radio_range_m=60.0, buffer_capacity=10, battery_mah=100.0)
    beacon.is_beacon = True
    near_phone, far_phone = _node(2, 15.0, 0.0), _node(3, 40.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in (beacon, near_phone, far_phone):
        grid.insert(n)
    beacon.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    process_node_contacts(
        now=1.0, sender=beacon, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=MetricsCollector(), ble_config=BleConfig(max_concurrent_links=None),
    )
    assert near_phone.has_message(1) and not far_phone.has_message(1)


def test_receiver_link_slots_are_shared_by_every_sender():
    import simpy
    from festival_ble_sim.network import network_engine
    s1, s2, receiver = _node(1, 0.0, 0.0), _node(2, 10.0, 0.0), _node(3, 5.0, 0.0)
    nodes = {1: s1, 2: s2, 3: receiver}
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in nodes.values():
        grid.insert(n)
    s1.store_message(Message(msg_id=1, src_id=1, dst_id=3, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    s2.store_message(Message(msg_id=2, src_id=2, dst_id=3, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    env = simpy.Environment()
    ble = BleConfig(max_concurrent_links=1, connection_setup_s=0.0)
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, 1.0, ble_config=ble))
    env.run(until=1.5)
    assert metrics.build_report([], 0).messages_delivered == 1


def _engine(nodes, ble):
    import simpy
    from festival_ble_sim.network import network_engine
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in nodes.values():
        grid.insert(n)
    metrics = MetricsCollector()
    env = simpy.Environment()
    env.process(network_engine(env, nodes, grid, EpidemicRouting(), _energy_model(), metrics, 1.0, ble_config=ble))
    return env, grid, metrics


def test_connection_carries_nothing_before_its_setup_time():
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    env, _, metrics = _engine({1: a, 2: b}, BleConfig(connection_setup_s=3.0))
    env.run(until=3.5)
    assert metrics.build_report([], 0).messages_delivered == 0
    env.run(until=4.5)
    assert metrics.build_report([], 0).messages_delivered == 1


def test_established_connection_keeps_its_slot_against_a_closer_newcomer():
    a, b, c = _node(1, 0.0, 0.0), _node(2, 15.0, 0.0), _node(3, 90.0, 90.0)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    a.store_message(Message(msg_id=2, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    env, grid, _ = _engine({1: a, 2: b, 3: c}, BleConfig(max_concurrent_links=1, connection_setup_s=0.0))
    env.run(until=1.5)
    old_x, old_y = c.position.x, c.position.y
    c.position = Position(2.0, 0.0)
    grid.update(c, old_x, old_y)
    env.run(until=5.5)
    assert b.has_message(1) and not c.has_message(1)
