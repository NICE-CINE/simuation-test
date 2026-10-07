from __future__ import annotations
from festival_ble_sim.config import AreaConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.geo_spray_focus import GeoSprayFocusRouting
from festival_ble_sim.simulation import run_simulation


def _node(node_id, x):
    return BaseNode(
        node_id=node_id, position=Position(x, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=100.0
    )


def _msg(dst_position=None, dst_position_time=None, creation_time=0.0, tokens=None):
    msg = Message(
        msg_id=1, src_id=1, dst_id=99, size_bytes=10, creation_time=creation_time, ttl_s=7200.0,
        dst_position=dst_position, dst_position_time=dst_position_time,
    )
    if tokens is not None:
        msg.routing_state.update({"tokens": tokens, "escalation": 0})
    return msg


def _algo_with(nodes, neighbors, now=1.0, **kwargs):
    # Every node with a neighbour takes an exact fix on the first tick
    # (GPS is noiseless outside a full simulation).
    algo = GeoSprayFocusRouting(hint_cell_m=0.0, **kwargs)
    algo.on_simulation_start({n.id: n for n in nodes})
    algo.on_tick(now, neighbors)
    return algo


def _forward(algo, msg, holder, contact, now=1.0):
    if algo.decide(msg, holder, contact, now) is not RoutingDecision.FORWARD:
        return None
    copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
    contact.store_message(copy)
    algo.on_forward(msg, holder, contact, copy)
    return copy


def test_copy_budget_follows_the_uncertainty_area():
    def budget(hint_age_s):
        src, relay, dst = _node(1, 0.0), _node(2, 20.0), _node(99, 500.0)
        algo = _algo_with([src, relay, dst], {1: [relay], 2: [src], 99: []}, now=1000.0)
        hint = (None, None) if hint_age_s is None else (Position(500.0, 0.0), 1000.0 - hint_age_s)
        msg = _msg(*hint, creation_time=1000.0)
        src.store_message(msg)
        algo.decide(msg, src, relay, 1000.0)
        return msg.routing_state["tokens"]

    assert [budget(None), budget(0.0), budget(150.0), budget(300.0)] == [12, 2, 5, 12]


def test_spray_is_refused_to_a_contact_far_behind_the_holder():
    a, far, near, d = _node(2, 100.0), _node(3, 170.0), _node(4, 80.0), _node(99, 900.0)
    algo = _algo_with([a, far, near, d], {2: [far, near], 3: [a], 4: [a], 99: []})
    msg = _msg(Position(0.0, 0.0), 1.0, tokens=8)
    a.store_message(msg)
    assert algo.decide(msg, a, far, 1.0) is RoutingDecision.IGNORE
    copy = _forward(algo, msg, a, near)
    assert copy.routing_state["tokens"] == msg.routing_state["tokens"] == 4


def test_last_copy_moves_towards_the_hint_only_with_enough_progress():
    a, b, c, d = _node(2, 0.0), _node(3, 20.0), _node(4, 10.0), _node(99, 900.0)
    algo = _algo_with([a, b, c, d], {2: [b, c], 3: [a], 4: [a], 99: []})
    msg = _msg(Position(400.0, 0.0), 1.0, tokens=1)
    a.store_message(msg)
    assert algo.decide(msg, a, c, 1.0) is RoutingDecision.IGNORE
    copy = _forward(algo, msg, a, b)
    assert copy.routing_state["tokens"] == 1 and msg.msg_id not in a.buffer


def test_without_hint_the_last_copy_follows_encounters():
    a, b, d = _node(2, 0.0), _node(3, 20.0), _node(99, 30.0)
    algo = _algo_with([a, b, d], {2: [b], 3: [a], 99: []})
    msg = _msg(tokens=1)
    a.store_message(msg)
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE
    algo.on_tick(2.0, {2: [b], 3: [a, d], 99: [b]})
    algo.on_tick(40.0, {2: [b], 3: [a], 99: []})
    copy = _forward(algo, msg, a, b, now=40.0)
    assert copy.routing_state["tokens"] == 1 and msg.msg_id not in a.buffer


def test_contact_next_to_the_destination_gets_a_copy():
    a, b, d = _node(2, 0.0), _node(3, 20.0), _node(99, 30.0)
    algo = _algo_with([a, b, d], {2: [b], 3: [a, d], 99: [b]})
    msg = _msg(tokens=1)
    a.store_message(msg)
    copy = _forward(algo, msg, a, b)
    assert copy.routing_state["tokens"] == 0 and algo.stats["island"] == 1


def test_source_escalates_to_more_copies_then_flooding():
    src, relay, d = _node(1, 0.0), _node(2, 20.0), _node(99, 900.0)
    algo = _algo_with([src, relay, d], {1: [relay], 2: [src], 99: []})
    msg = _msg(tokens=0)
    src.store_message(msg)
    algo.decide(msg, src, relay, 61.0)
    assert msg.routing_state["tokens"] == 12 and msg.routing_state["escalation"] == 1
    copy = _forward(algo, msg, src, relay, now=181.0)
    assert copy.routing_state["escalation"] == 2 and copy.routing_state["tokens"] == 1
    assert algo.stats["escalations"] == 2 and algo.stats["flood"] == 1


def test_delivery_purges_every_copy_and_returns_the_destination_position():
    src, relay, other, d = _node(1, 0.0), _node(2, 20.0), _node(3, 40.0), _node(99, 60.0)
    ticks = {1: [relay], 2: [src, other], 3: [relay, d], 99: [other]}
    algo = _algo_with([src, relay, other, d], ticks)
    msg = _msg(creation_time=4.0, tokens=1)
    relay.store_message(msg)
    other.store_message(_msg(creation_time=4.0, tokens=1))
    algo.on_tick(10.0, ticks)
    algo.on_delivered(msg, other)
    algo.on_tick(11.0, ticks)
    assert not relay.buffer and not other.buffer
    algo.on_tick(15.0, ticks)
    assert 99 not in src.known_positions
    algo.on_tick(16.0, ticks)
    assert src.known_positions[99] == (Position(60.0, 0.0), 1.0) and algo.stats["ack_hints"] == 1


def test_carriers_policy_only_fixes_nodes_carrying_a_hinted_message():
    a, b = _node(2, 0.0), _node(3, 20.0)
    a.store_message(_msg(Position(400.0, 0.0), 1.0, tokens=1))
    algo = _algo_with([a, b], {2: [b], 3: [a]}, gps_policy="carriers", gps_current_ma=36.0)
    assert abs(a.battery_mah - 99.7) < 1e-9 and b.battery_mah == 100.0
    assert algo.stats["gps_fixes"] == 1


def test_small_festival_delivers_with_hints():
    config = SimulationConfig(
        duration_s=900.0, num_festivaliers=60, random_seed=3,
        area=AreaConfig(width_m=120.0, height_m=120.0),
        traffic=TrafficConfig(messages_per_hour_range=(4.0, 8.0), reply_probability=0.9, followup_probability=0.6),
    )
    algo = GeoSprayFocusRouting()
    report = run_simulation(config, routing_algorithm=algo)
    assert report.messages_delivered > 0
    assert algo.stats["hinted"] > 0 and algo.stats["ack_hints"] > 0
