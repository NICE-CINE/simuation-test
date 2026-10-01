from __future__ import annotations
import math
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.tide_g import TideGRouting


def _node(node_id, x):
    return BaseNode(
        node_id=node_id, position=Position(x, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=100.0
    )


def _msg(dst_position=None, dst_position_time=None, src_id=1):
    return Message(
        msg_id=1, src_id=src_id, dst_id=99, size_bytes=10, creation_time=0.0, ttl_s=7200.0,
        dst_position=dst_position, dst_position_time=dst_position_time,
    )


def _algo_with(nodes, neighbors, **kwargs):
    # election=False: every node is a relay and takes an exact fix on the
    # first tick (GPS is noiseless outside a full simulation).
    algo = TideGRouting(max_syncs_per_minute=None, election=False, hint_cell_m=kwargs.pop("hint_cell_m", 0.0), **kwargs)
    algo.on_simulation_start({n.id: n for n in nodes})
    algo.on_tick(1.0, neighbors)
    return algo


def _tokens(msg, n):
    msg.routing_state.update({"tokens": n, "l0": 8, "reinjections": 3})


def _forward(algo, msg, holder, contact, now=1.0):
    if algo.decide(msg, holder, contact, now) is not RoutingDecision.FORWARD:
        return None
    copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
    contact.store_message(copy)
    algo.on_forward(msg, holder, contact, copy)
    return copy


def test_hint_is_quantized_and_its_radius_grows_with_age():
    algo = TideGRouting()
    hint = algo._hint(_msg(Position(37.0, 12.0), 0.0), 600.0)
    assert hint.position == Position(37.5, 12.5)
    assert abs(hint.radius_m - 210.0) < 1e-9
    assert abs(hint.confidence - math.exp(-1)) < 1e-9
    assert algo._hint(_msg(Position(37.0, 12.0), 0.0), 901.0) is None
    assert algo._hint(_msg(), 10.0) is None


def test_single_copy_moves_towards_the_hint_only_with_enough_progress():
    a, b, c, d = _node(2, 0.0), _node(3, 20.0), _node(4, 10.0), _node(99, 500.0)
    algo = _algo_with([a, b, c, d], {2: [b, c], 3: [a], 4: [a]})
    msg = _msg(Position(400.0, 0.0), 0.0)
    _tokens(msg, 1)
    a.store_message(msg)
    assert algo.decide(msg, a, c, 1.0) is RoutingDecision.IGNORE  # 10 m closer < 15 m
    copy = _forward(algo, msg, a, b)
    assert copy is not None and copy.routing_state["tokens"] == 1
    assert msg.msg_id not in a.buffer


def test_no_geographic_move_without_a_fresh_fix():
    a, b, d = _node(2, 0.0), _node(3, 20.0), _node(99, 500.0)
    algo = _algo_with([a, b, d], {2: [b], 3: [a]})
    del algo._fixes[3]
    msg = _msg(Position(400.0, 0.0), 0.0)
    _tokens(msg, 1)
    a.store_message(msg)
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE


def test_without_hint_tide_g_falls_back_to_tide_focus():
    a, b, d = _node(2, 0.0), _node(3, 20.0), _node(99, 500.0)
    algo = _algo_with([a, b, d], {2: [b], 3: [a]})
    msg = _msg()
    _tokens(msg, 1)
    a.store_message(msg)
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE
    algo._last_met[3][99] = 1.0
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.FORWARD


def test_zone_search_boosts_tokens_once_and_keeps_them_inside_the_disc():
    a, b, e, d = _node(2, 0.0), _node(3, 20.0), _node(4, 100.0), _node(99, 500.0)
    algo = _algo_with([a, b, e, d], {2: [b, e], 3: [a], 4: [a]})
    msg = _msg(Position(0.0, 0.0), 0.0)
    _tokens(msg, 1)
    a.store_message(msg)
    assert algo.decide(msg, a, e, 1.0) is RoutingDecision.IGNORE  # outside the disc
    assert msg.routing_state["tokens"] == 3 and msg.routing_state["zone"]
    copy = _forward(algo, msg, a, b)
    assert copy is not None and copy.routing_state["zone"]
    assert copy.routing_state["tokens"] + msg.routing_state["tokens"] == 3

    msg.routing_state["tokens"] = 1
    algo.decide(msg, a, e, 1.0)
    assert msg.routing_state["tokens"] == 1


def test_token_share_favours_the_contact_closer_to_the_hint():
    a, b, c, d = _node(2, 300.0), _node(3, 10.0), _node(4, 600.0), _node(99, 900.0)
    algo = _algo_with([a, b, c, d], {2: [b, c], 3: [a], 4: [a]})
    msg = _msg(Position(0.0, 0.0), 0.0)
    assert algo._token_share(msg, a, b, 1.0) > 0.5 > algo._token_share(msg, a, c, 1.0)
    _tokens(msg, 8)
    a.store_message(msg)
    copy = _forward(algo, msg, a, b)
    assert copy.routing_state["tokens"] > msg.routing_state["tokens"]


def test_source_refreshes_the_hint_from_a_newer_reply():
    a, b, d = _node(1, 0.0), _node(3, 20.0), _node(99, 500.0)
    algo = _algo_with([a, b, d], {1: [b], 3: [a]})
    msg = _msg(Position(400.0, 0.0), 0.0)
    a.store_message(msg)
    a.known_positions[99] = (Position(5.0, 5.0), 50.0)
    algo.decide(msg, a, b, 60.0)
    assert msg.dst_position == Position(5.0, 5.0) and msg.dst_position_time == 50.0


def test_relays_pay_for_their_gps_fixes():
    a, b = _node(2, 0.0), _node(3, 20.0)
    algo = _algo_with([a, b], {2: [b], 3: [a]}, gps_current_ma=36.0)
    assert abs(a.battery_mah - 99.7) < 1e-9 and algo.hint_stats["gps_fixes"] == 2

    a, b = _node(2, 0.0), _node(3, 20.0)
    algo = _algo_with([a, b], {2: [b], 3: [a]}, gps_for_relays=False)
    assert a.battery_mah == 100.0 and algo.hint_stats["gps_fixes"] == 0
