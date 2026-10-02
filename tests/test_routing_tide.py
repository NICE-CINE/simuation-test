from __future__ import annotations
from festival_ble_sim.config import SimulationConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.tide import TideRouting
from festival_ble_sim.simulation import run_simulation


def _node(node_id, battery_mah=100.0):
    return BaseNode(
        node_id=node_id, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=battery_mah
    )


def _msg(msg_id=1, src_id=1, dst_id=99):
    return Message(msg_id=msg_id, src_id=src_id, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=7200.0)


def _algo_with(nodes, neighbors, **kwargs):
    algo = TideRouting(max_syncs_per_minute=None, **kwargs)
    algo.on_simulation_start({n.id: n for n in nodes})
    algo.on_tick(1.0, neighbors)
    return algo


def _forward(algo, msg, holder, contact, now=1.0):
    decision = algo.decide(msg, holder, contact, now)
    if decision is RoutingDecision.FORWARD:
        copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
        contact.store_message(copy)
        algo.on_forward(msg, holder, contact, copy)
        return copy
    return None


def test_initial_tokens_shrink_with_density():
    algo = TideRouting(l_max=12)
    algo._density = {1: 10.0, 2: 40.0, 3: 1000.0}
    assert [algo._initial_tokens(i) for i in (1, 2, 3)] == [12, 6, 2]


def test_energy_factor_is_linear_between_20_and_50_percent():
    algo = TideRouting()
    assert algo._energy(_node(1, battery_mah=100.0)) == 1.0
    n = _node(2, battery_mah=100.0)
    n.battery_mah = 35.0
    assert abs(algo._energy(n) - 0.6) < 1e-9
    n.battery_mah = 10.0
    assert algo._energy(n) == 0.2


def test_member_gets_copy_only_when_it_sees_destination():
    a, b, d = _node(1), _node(2), _node(99)
    algo = _algo_with([a, b, d], {1: [b], 2: [a]})
    algo._is_relay = {1: True, 2: False, 99: False}
    algo._last_relay_seen[2] = 1.0
    msg = _msg()
    a.store_message(msg)
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE

    algo.on_tick(2.0, {1: [b], 2: [a, d], 99: [b]})
    algo._is_relay[2] = False
    copy = _forward(algo, msg, a, b, now=2.0)
    assert copy is not None and copy.routing_state["tokens"] == 0


def test_spray_splits_tokens_then_source_keeps_shadow_copy():
    a, b, c = _node(1), _node(2), _node(3)
    algo = _algo_with([a, b, c], {1: [b, c], 2: [a], 3: [a]}, election=False)
    msg = _msg()
    a.store_message(msg)
    copy = _forward(algo, msg, a, b)
    assert copy is not None
    assert copy.routing_state["tokens"] + msg.routing_state["tokens"] == msg.routing_state["l0"]

    msg.routing_state["tokens"] = 1
    algo._last_met[3][99] = 1.0
    copy = _forward(algo, msg, a, c)
    assert copy is not None and copy.routing_state["tokens"] == 1
    assert msg.msg_id in a.buffer and msg.routing_state["tokens"] == 0


def test_source_reinjects_tokens_without_ack():
    a, b = _node(1), _node(2)
    algo = _algo_with([a, b], {1: [b], 2: [a]}, election=False)
    msg = _msg()
    msg.routing_state.update(tokens=0, l0=8, reinjections=0)
    a.store_message(msg)
    algo.decide(msg, a, b, now=400.0)
    assert msg.routing_state["reinjections"] == 2
    assert msg.routing_state["tokens"] == 12  # 4 + 8, capped at l_max


def test_delivered_message_is_purged():
    a, b = _node(1), _node(2)
    algo = _algo_with([a, b], {1: [b], 2: [a]})
    msg = _msg()
    a.store_message(msg)
    algo.on_delivered(msg, b)
    assert algo.decide(msg, a, b, 1.0) is RoutingDecision.IGNORE
    assert msg.msg_id not in a.buffer


def test_eviction_prefers_late_foreign_copies_and_never_own():
    node = _node(1)
    algo = TideRouting()
    own = _msg(msg_id=1, src_id=1)
    fresh = Message(msg_id=2, src_id=5, dst_id=9, size_bytes=10, creation_time=900.0, ttl_s=7200.0)
    late = Message(msg_id=3, src_id=5, dst_id=9, size_bytes=10, creation_time=0.0, ttl_s=7200.0)
    for m in (own, fresh, late):
        node.store_message(m)
    assert algo.choose_eviction(node, now=1000.0) == 3
    node.buffer.pop(3)
    node.buffer.pop(2)
    assert algo.choose_eviction(node, now=1000.0) is None


def test_runs_end_to_end():
    config = SimulationConfig(num_festivaliers=60, duration_s=600.0)
    report = run_simulation(config, routing_algorithm=TideRouting(seed=3))
    assert report.messages_delivered >= 0
