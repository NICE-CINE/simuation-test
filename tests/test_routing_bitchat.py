from __future__ import annotations
import pytest
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.bitchat import BitchatRouting
from test_routing_managed_flood import _engine, _line, _msg, _node, _run


def _flood_copy(msg_id=1, dst_id=99):
    msg = _msg(msg_id=msg_id, src_id=1, dst_id=dst_id, hops=1)
    msg.routing_state.update(role="flood", attempt=0, base=0, ingress=1)
    return msg


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        BitchatRouting(spool_window_s=0.0)
    with pytest.raises(ValueError):
        BitchatRouting(max_send_attempts=0)


def test_dedup_forgets_after_max_age():
    algo = BitchatRouting(dedup_max_age_s=300.0)
    algo._remember(2, (1, 0), 0.0)
    algo._now = 300.0
    assert algo.in_cache(2, 1, 0)
    algo._now = 301.0
    assert not algo.in_cache(2, 1, 0)
    assert algo._remember(2, (1, 0), 301.0) == 301.0


def test_reachable_destination_gets_the_flood_along_a_line():
    nodes = _line(4)
    nodes[1].store_message(_msg(src_id=1, dst_id=4))
    assert _run(nodes, BitchatRouting(), until=6.5).messages_delivered == 1


def test_relay_linked_to_destination_sends_to_it_only():
    nodes = {2: _node(2), 3: _node(3, x=10.0), 4: _node(4, x=-10.0)}
    algo = BitchatRouting()
    algo.on_simulation_start(nodes)
    algo.on_tick(1.0, {2: [nodes[3], nodes[4]], 3: [nodes[2]], 4: [nodes[2]]})
    msg = _flood_copy(dst_id=3)
    nodes[2].store_message(msg)
    algo._remember(2, (1, 0), 1.0)
    assert algo.decide(msg, nodes[2], nodes[4], now=1.0) is RoutingDecision.IGNORE


def test_unreachable_destination_queues_and_deposits_to_couriers_that_spray():
    nodes = _line(3)
    nodes[1].store_message(_msg(src_id=1, dst_id=99))
    _run(nodes, BitchatRouting(), until=4.5)
    assert nodes[1].buffer[1].routing_state.get("role") is None
    assert nodes[2].buffer[1].routing_state["role"] == "courier"
    assert nodes[2].buffer[1].routing_state["copies"] == 2
    assert nodes[3].buffer[1].routing_state["copies"] == 2


@pytest.mark.parametrize("order", [(1, 2, 3), (1, 3, 2), (2, 3, 1), (3, 2, 1)])
def test_courier_deposit_prefers_friends(order):
    x = {1: 0.0, 2: 10.0, 3: -12.0}
    nodes = {i: _node(i, x=x[i]) for i in order}
    nodes[1].friends, nodes[3].friends = {3}, {1}
    nodes[1].store_message(_msg(src_id=1, dst_id=99))
    _run(nodes, BitchatRouting(max_couriers_per_message=1), until=3.5)
    assert nodes[3].buffer[1].routing_state["tier"] == "favorite"
    assert 1 not in nodes[2].buffer


def test_source_floods_once_destination_becomes_reachable():
    nodes = _line(3)
    nodes[3].is_active = False
    nodes[1].store_message(_msg(src_id=1, dst_id=3))
    algo = BitchatRouting(max_couriers_per_message=0)
    env, metrics = _engine(nodes, algo)
    env.run(until=10.5)
    assert 1 not in nodes[2].buffer
    nodes[3].is_active = True
    env.run(until=20.5)
    assert metrics.build_report([], 0).messages_delivered == 1


@pytest.mark.parametrize("wake_at, relayed", [(10.0, True), (70.0, False)])
def test_isolated_relay_spools_for_the_spool_window(wake_at, relayed):
    nodes = {2: _node(2), 5: _node(5, x=10.0)}
    nodes[5].is_active = False
    nodes[2].store_message(_flood_copy())
    env, _ = _engine(nodes, BitchatRouting())
    env.run(until=wake_at)
    nodes[5].is_active = True
    env.run(until=wake_at + 10.5)
    assert (1 in nodes[5].buffer) is relayed
