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


def test_delivery_records_source_position_at_destination():
    sender = _node(1, 0.0, 0.0)
    dest = _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(dest)
    msg = Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=4.0, ttl_s=100.0, src_position=Position(3.0, 4.0))
    sender.store_message(msg)
    process_node_contacts(now=5.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(), metrics=MetricsCollector())
    assert dest.known_positions[1] == (Position(3.0, 4.0), 4.0)
    assert 2 not in sender.known_positions


def test_inactive_neighbor_does_not_take_a_link_slot():
    from festival_ble_sim.config import BleConfig
    sender = _node(1, 0.0, 0.0)
    departed = _node(2, 1.0, 0.0)
    departed.is_active = False
    far = _node(3, 10.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in (sender, departed, far):
        grid.insert(n)
    sender.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(), energy_model=_energy_model(),
        metrics=MetricsCollector(), ble_config=BleConfig(max_concurrent_links=1),
    )
    assert far.has_message(1)


def test_on_tick_neighbors_exclude_inactive_nodes():
    from festival_ble_sim.config import BleConfig
    from festival_ble_sim.routing.base import RoutingAlgorithm, RoutingDecision

    class Spy(RoutingAlgorithm):
        seen = []

        def on_tick(self, now, neighbors_by_node):
            self.seen.append({k: sorted(n.id for n in v) for k, v in neighbors_by_node.items()})

        def decide(self, message, holder, contact, now):
            return RoutingDecision.IGNORE

    a, b, c = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0), _node(3, 10.0, 0.0)
    b.is_active = False
    nodes = {1: a, 2: b, 3: c}
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in nodes.values():
        grid.insert(n)
    env = simpy.Environment()
    spy = Spy()
    env.process(network_engine(env, nodes, grid, spy, _energy_model(), MetricsCollector(), 1.0, ble_config=BleConfig()))
    env.run(until=1.5)
    assert spy.seen == [{1: [3], 3: [1]}]


def test_sender_that_runs_out_of_battery_stops_sending_mid_tick():
    sender = BaseNode(node_id=1, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=1.0)
    a, b = _node(2, 5.0, 0.0), _node(3, 0.0, 5.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in (sender, a, b):
        grid.insert(n)
    sender.store_message(Message(msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    process_node_contacts(
        now=1.0, sender=sender, grid=grid, routing_algorithm=EpidemicRouting(),
        energy_model=_energy_model(), metrics=metrics,
    )
    assert sender.battery_depleted
    assert metrics.build_report([], 0).total_transmissions == 1


class _Announcer(EpidemicRouting):
    def __init__(self, sizes):
        self.sizes = sizes
        self.received = []

    def control_broadcasts(self, now):
        return self.sizes

    def on_control_received(self, now, received, sent):
        self.received.append(received)
        self.sent = sent


def _lossless_ble(**kw):
    from dataclasses import replace
    from festival_ble_sim.config import BleConfig
    ble = BleConfig()
    params = dict(shadowing_std_db=0.0)
    return replace(
        ble,
        phone_radio=replace(ble.phone_radio, **params),
        beacon_radio=replace(ble.beacon_radio, **params),
        packet_loss_base_probability=0.0,
        collision_loss_coefficient=0.0,
        **kw,
    )


def test_control_broadcast_reaches_neighbors_and_bills_energy():
    import random
    env = simpy.Environment()
    a, b, c = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0), _node(3, 90.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    for n in (a, b, c):
        grid.insert(n)
    algo = _Announcer({1: 50})
    env.process(network_engine(env, {1: a, 2: b, 3: c}, grid, algo, _energy_model(), MetricsCollector(),
                               contact_check_interval_s=1.0, ble_config=_lossless_ble(), rng=random.Random(0)))
    env.run(until=1.5)
    assert algo.received == [{2: [1]}] and algo.sent == [1]
    assert a.battery_mah < 100.0 and b.battery_mah < 100.0 and c.battery_mah == 100.0


def test_control_broadcast_takes_airtime_from_data():
    import random

    def delivered(sizes):
        env = simpy.Environment()
        a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
        grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
        grid.insert(a)
        grid.insert(b)
        a.store_message(Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0))
        env.process(network_engine(env, {1: a, 2: b}, grid, _Announcer(sizes), _energy_model(), MetricsCollector(),
                                   contact_check_interval_s=1.0,
                                   ble_config=_lossless_ble(transfer_rate_bytes_per_s=100.0), rng=random.Random(0)))
        env.run(until=1.5)
        return 1 in b.delivered_ids

    assert delivered({}) and not delivered({1: 95})


def test_control_broadcast_skips_a_receiver_that_died_this_tick():
    import random
    from festival_ble_sim.network import _send_control_broadcast
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    b.is_active = False
    received = {}
    _send_control_broadcast(a, 50, [b], _energy_model(), MetricsCollector(), _lossless_ble(), random.Random(0),
                            None, {}, received)
    assert received == {} and b.battery_mah == 100.0


def test_announce_and_data_share_one_backoff_draw():
    import random
    env = simpy.Environment()
    a, b = _node(1, 0.0, 0.0), _node(2, 5.0, 0.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(a)
    grid.insert(b)
    a.store_message(Message(msg_id=1, src_id=1, dst_id=2, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    b.store_message(Message(msg_id=2, src_id=2, dst_id=1, size_bytes=10, creation_time=0.0, ttl_s=100.0))
    metrics = MetricsCollector()
    ble = _lossless_ble(relay_backoff_coefficient=1.0, relay_backoff_max_probability=1.0)
    env.process(network_engine(env, {1: a, 2: b}, grid, _Announcer({1: 50}), _energy_model(), metrics,
                               contact_check_interval_s=1.0, ble_config=ble, rng=random.Random(0)))
    env.run(until=1.5)
    assert metrics.build_report([], 0).backoff_count == 2
    assert a.battery_mah == 100.0
