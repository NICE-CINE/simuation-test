from __future__ import annotations
from dataclasses import replace
import pytest
import simpy
from festival_ble_sim.config import AreaConfig, BleConfig, EnergyConfig, RadioParams, SimulationConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import network_engine
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.routing.managed_flood import ManagedFloodRouting
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, x=0.0, y=0.0, buffer_capacity=50):
    return BaseNode(
        node_id=node_id, position=Position(x, y), radio_range_m=20.0,
        buffer_capacity=buffer_capacity, battery_mah=100.0,
    )


def _msg(msg_id=1, src_id=1, dst_id=99, hops=0, ttl_hops=None):
    return Message(
        msg_id=msg_id, src_id=src_id, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=1000.0,
        hops=hops, ttl_hops=ttl_hops,
    )


def _energy_model():
    return EnergyModel(
        EnergyConfig(tx_cost_mah_per_event=0.0, tx_cost_mah_per_byte=0.0, rx_cost_mah_per_event=0.0, rx_cost_mah_per_byte=0.0)
    )


def _lossless_ble():
    radio = RadioParams(
        tx_power_dbm=0.0, path_loss_exponent=2.0, reference_distance_m=1.0,
        reference_loss_db=40.0, receiver_sensitivity_dbm=-90.0, shadowing_std_db=0.0,
    )
    return BleConfig(
        phone_radio=radio, beacon_radio=radio, max_concurrent_links=None,
        packet_loss_base_probability=0.0, packet_loss_congestion_coefficient=0.0,
        weak_signal_max_probability=0.0, packet_loss_max_probability=0.0,
        relay_backoff_coefficient=0.0, relay_backoff_max_probability=0.0,
        collision_loss_coefficient=0.0, collision_loss_max_probability=0.0,
    )


def _engine(nodes, algo):
    env = simpy.Environment()
    grid = SpatialGrid(1000.0, 100.0, cell_size_m=20.0)
    for node in nodes.values():
        grid.insert(node)
    metrics = MetricsCollector()
    algo.on_simulation_start(nodes)
    env.process(network_engine(
        env, nodes, grid, algo, _energy_model(), metrics, contact_check_interval_s=1.0, ble_config=_lossless_ble(),
    ))
    return env, metrics


def _run(nodes, algo, until):
    env, metrics = _engine(nodes, algo)
    env.run(until=until)
    return metrics.build_report([], 0)


def _line(n, spacing=15.0):
    return {i: _node(i, x=(i - 1) * spacing) for i in range(1, n + 1)}


def _forward(algo, msg, holder, contact, now):
    algo.decide(msg, holder, contact, now)
    copy = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    contact.store_message(copy)
    algo.on_forward(msg, holder, contact, copy)
    return copy


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        ManagedFloodRouting(ttl=-1)
    with pytest.raises(ValueError):
        ManagedFloodRouting(relay_window_s=0.0)
    with pytest.raises(ValueError):
        ManagedFloodRouting(cache_size=0)
    with pytest.raises(ValueError):
        ManagedFloodRouting(ack_timeout_s=0.0)
    with pytest.raises(ValueError):
        ManagedFloodRouting(max_source_retransmissions=-1)
    with pytest.raises(ValueError):
        ManagedFloodRouting(ack_size_bytes=-1)


def test_forwards_fresh_pdu_to_uncached_neighbor():
    algo = ManagedFloodRouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=1.0) is RoutingDecision.FORWARD


def test_ttl_stops_relaying():
    algo = ManagedFloodRouting(ttl=3)
    holder, contact = _node(1), _node(2)
    msg = _msg(hops=3)
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=1.0) is RoutingDecision.IGNORE


def test_message_cache_rejects_pdu_a_node_already_relayed_and_dropped():
    algo = ManagedFloodRouting(relay_window_s=2.0, acknowledged=False)
    a, b, c = _node(1), _node(2), _node(3)
    msg = _msg()
    a.store_message(msg)
    copy_b = _forward(algo, msg, a, b, now=1.0)
    algo.decide(copy_b, b, c, now=10.0)
    assert 1 not in b.buffer
    assert algo.in_cache(b.id, 1)
    late_copy = replace(copy_b, hops=2)
    c.store_message(late_copy)
    algo._remember(c.id, (1, 0), now=10.0)
    assert algo.decide(late_copy, c, b, now=11.0) is RoutingDecision.IGNORE
    assert algo.decide(late_copy, c, _node(4), now=11.0) is RoutingDecision.FORWARD


def test_small_cache_forgets_oldest_pdu():
    algo = ManagedFloodRouting(cache_size=2)
    for msg_id in (1, 2, 3):
        algo._remember(5, (msg_id, 0), now=float(msg_id))
    assert not algo.in_cache(5, 1)
    assert algo.in_cache(5, 2) and algo.in_cache(5, 3)


def test_relay_drops_pdu_after_window():
    algo = ManagedFloodRouting(relay_window_s=3.0)
    a, b, c = _node(1), _node(2), _node(3)
    msg = _msg()
    a.store_message(msg)
    copy_b = _forward(algo, msg, a, b, now=1.0)
    assert algo.decide(copy_b, b, c, now=4.0) is RoutingDecision.FORWARD
    assert algo.decide(copy_b, b, c, now=5.0) is RoutingDecision.IGNORE
    assert 1 not in b.buffer


def test_unacknowledged_source_retransmits_with_new_seq_then_gives_up():
    algo = ManagedFloodRouting(relay_window_s=1.0, ack_timeout_s=5.0, max_source_retransmissions=1)
    source, contact = _node(1), _node(2)
    algo.on_simulation_start({1: source, 2: contact})
    source.store_message(_msg())
    algo.on_tick(0.0, {})
    algo.on_tick(3.0, {})
    assert 1 not in source.buffer
    algo.on_tick(6.0, {})
    retry = source.buffer[1]
    assert retry.routing_state["attempt"] == 1
    algo._remember(contact.id, (1, 0), now=0.0)
    assert algo.decide(retry, source, contact, now=6.0) is RoutingDecision.FORWARD
    for now in (8.0, 12.0, 20.0):
        algo.on_tick(now, {})
    assert 1 not in source.buffer


def test_source_does_not_carry_pdu_to_destination_after_relay_window():
    nodes = {1: _node(1), 2: _node(2, x=10.0)}
    nodes[2].is_active = False
    nodes[1].store_message(_msg(dst_id=2))
    algo = ManagedFloodRouting(relay_window_s=2.0, ack_timeout_s=100.0)
    env, metrics = _engine(nodes, algo)
    env.run(until=5.5)
    nodes[2].is_active = True
    env.run(until=10.5)
    assert metrics.build_report([], 0).messages_delivered == 0


def test_ack_hops_cost_energy():
    nodes = _line(3)
    nodes[1].store_message(_msg(dst_id=3))
    algo = ManagedFloodRouting(
        relay_window_s=10.0, ack_timeout_s=100.0, ack_size_bytes=0,
        energy=EnergyConfig(tx_cost_mah_per_event=1.0, tx_cost_mah_per_byte=0.0,
                            rx_cost_mah_per_event=1.0, rx_cost_mah_per_byte=0.0),
    )
    _run(nodes, algo, until=5.5)
    assert algo.knows_ack(1, 1)
    # Data PDUs are free here (_energy_model is all zeros): ack hops 3->2->1.
    assert [nodes[i].energy_consumed_mah for i in (1, 2, 3)] == [1.0, 2.0, 1.0]


def test_multi_hop_delivery_along_a_line_takes_one_tick_per_hop():
    nodes = _line(6)
    nodes[1].store_message(_msg(dst_id=6))
    env, metrics = _engine(nodes, ManagedFloodRouting(ttl=7))
    env.run(until=4.5)
    assert not nodes[6].has_message(1)
    env.run(until=5.5)
    report = metrics.build_report([], 0)
    assert report.messages_delivered == 1
    assert report.avg_hops == pytest.approx(5.0)


def test_broadcast_reaches_every_node_within_ttl_and_no_further():
    nodes = _line(8)
    nodes[1].store_message(_msg(dst_id=999))
    algo = ManagedFloodRouting(ttl=4, acknowledged=False)
    _run(nodes, algo, until=20.5)
    reached = {i for i in nodes if algo.in_cache(i, 1)}
    assert reached == {1, 2, 3, 4, 5}


def test_flood_is_storm_free_each_node_receives_exactly_once_then_goes_quiet():
    nodes = {i: _node(i, x=(i % 5) * 8.0, y=(i // 5) * 8.0) for i in range(1, 16)}
    nodes[1].store_message(_msg(dst_id=999))
    algo = ManagedFloodRouting(ttl=10, acknowledged=False)
    env, metrics = _engine(nodes, algo)
    env.run(until=15.5)
    assert all(algo.in_cache(i, 1) for i in nodes)
    assert metrics.build_report([], 0).total_transmissions == len(nodes) - 1
    assert all(not n.buffer for n in nodes.values())
    env.run(until=60.5)
    assert metrics.build_report([], 0).total_transmissions == len(nodes) - 1


def test_ack_floods_back_and_purges_copies_at_source():
    nodes = _line(5)
    nodes[1].store_message(_msg(dst_id=5))
    algo = ManagedFloodRouting(relay_window_s=10.0, ack_timeout_s=100.0)
    report = _run(nodes, algo, until=12.5)
    assert report.messages_delivered == 1
    assert algo.knows_ack(1, 1)
    assert all(not n.buffer for n in nodes.values())


def test_fewer_transmissions_than_epidemic_in_mobile_run():
    config = SimulationConfig(
        duration_s=300.0, num_festivaliers=60, random_seed=7, area=AreaConfig(width_m=100.0, height_m=100.0)
    )
    flood = run_simulation(config, routing_algorithm=ManagedFloodRouting())
    epidemic = run_simulation(config, routing_algorithm=EpidemicRouting())
    assert flood.messages_delivered > 0
    assert flood.total_transmissions < epidemic.total_transmissions
