from __future__ import annotations
from dataclasses import replace
import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode, BeaconNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.dasfv import DasfVRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, battery_mah=100.0):
    return BaseNode(
        node_id=node_id, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=battery_mah
    )


def _msg(msg_id=1, src_id=1, dst_id=99, ttl_s=100.0):
    return Message(msg_id=msg_id, src_id=src_id, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=ttl_s)


def _meet(algo, a, b, now):
    algo.on_tick(now, {a.id: [b], b.id: [a]})


def _make_mule(algo, node):
    algo._prev_window_contacts[node.id] = {5, 6, 7}
    algo._prev2_window_contacts[node.id] = {1, 2, 3}
    algo._speed[node.id] = 1.0


def test_ignores_when_contact_already_has_message():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    holder.store_message(msg)
    contact.store_message(_msg())
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_contact_that_learned_the_ack_is_skipped():
    algo = DasfVRouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    contact.learn_ack(msg.msg_id, 1000.0)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_acks_and_tables_go_through_the_engine():
    algo = DasfVRouting()
    peer = _node(2)
    peer.store_message(_msg())
    assert algo.uses_delivery_acks
    assert algo.connection_table_bytes(_node(1), peer) == 12


def test_lazy_token_budget_is_capped_at_l_max_when_holder_is_isolated():
    algo = DasfVRouting(l_base=8, k_min=2, l_max=32, d_ref=20.0)
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    holder.store_message(msg)
    algo.decide(msg, holder, contact, now=0.0)
    assert msg.routing_state["tokens"] == 32


def test_lazy_token_budget_shrinks_when_holder_is_in_a_dense_area():
    algo = DasfVRouting(l_base=8, k_min=2, l_max=32, d_ref=20.0)
    holder = _node(1)
    for i in range(20):
        _meet(algo, holder, _node(1000 + i), 0.0)
    real_contact = _node(2)
    msg = _msg()
    holder.store_message(msg)
    algo.decide(msg, holder, real_contact, now=0.0)
    assert msg.routing_state["tokens"] == 8


def test_spray_forwards_and_splits_tokens_between_holder_and_contact():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    msg.routing_state["tokens"] = 8
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.routing_state["tokens"] == 4
    assert forwarded.routing_state["tokens"] == 4


def test_spray_gives_a_smaller_token_share_to_a_mule_contact():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    _make_mule(algo, contact)
    msg = _msg()
    msg.routing_state["tokens"] = 9
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert forwarded.routing_state["tokens"] == 3
    assert msg.routing_state["tokens"] == 6


def test_two_hop_relay_forwards_even_in_wait_phase_and_moves_the_last_copy():
    algo = DasfVRouting(two_hop_freshness_s=5.0)
    holder = _node(1)
    contact = _node(2)
    dst = _node(99)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    _meet(algo, contact, dst, 0.0)
    assert algo.decide(msg, holder, contact, now=2.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.msg_id not in holder.buffer
    assert forwarded.routing_state["tokens"] == 1


def test_two_hop_relay_keeps_holders_spare_copies_when_it_has_more_than_one():
    algo = DasfVRouting(two_hop_freshness_s=5.0)
    holder = _node(1)
    contact = _node(2)
    dst = _node(99)
    msg = _msg()
    msg.routing_state["tokens"] = 5
    holder.store_message(msg)
    _meet(algo, contact, dst, 0.0)
    assert algo.decide(msg, holder, contact, now=2.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.msg_id in holder.buffer
    assert msg.routing_state["tokens"] == 4
    assert forwarded.routing_state["tokens"] == 1


def test_neutral_contact_with_no_signal_is_ignored():
    algo = DasfVRouting(delta=0.1)
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_focus_moves_single_copy_to_a_materially_better_carrier():
    algo = DasfVRouting(delta=0.1, two_hop_freshness_s=5.0)
    holder = _node(1)
    contact = _node(2)
    dst = _node(99)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    # Contact met the destination long enough ago that the 2-hop freshness
    # window has expired, but its PRoPHET utility (30 s aging) has barely decayed.
    _meet(algo, contact, dst, 0.0)
    assert algo.decide(msg, holder, contact, now=10.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.msg_id not in holder.buffer
    assert forwarded.routing_state["tokens"] == 1


def test_low_battery_holder_relaxes_focus_hysteresis_to_evacuate():
    algo = DasfVRouting(delta=0.1, battery_evac_pct=0.30, two_hop_freshness_s=5.0)
    holder = _node(1)
    holder.battery_mah = 20.0
    contact = _node(2)
    contact.battery_mah = 30.0  # below mule_min_battery_pct: isolates this from the mule branch
    dst = _node(99)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    # A tiny, long-decayed utility edge for contact: not enough to clear the
    # normal DELTA hysteresis, but the evacuating holder accepts any edge.
    _meet(algo, contact, dst, 0.0)
    assert algo.decide(msg, holder, contact, now=5000.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.msg_id not in holder.buffer  # focus branch: a move, not a mule replication


def test_healthy_battery_holder_keeps_the_same_tiny_edge_ignored():
    algo = DasfVRouting(delta=0.1, battery_evac_pct=0.30, two_hop_freshness_s=5.0)
    holder = _node(1)
    contact = _node(2)
    contact.battery_mah = 30.0  # below mule_min_battery_pct: isolates this from the mule branch
    dst = _node(99)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    _meet(algo, contact, dst, 0.0)
    assert algo.decide(msg, holder, contact, now=5000.0) is RoutingDecision.IGNORE


def test_refuses_to_forward_to_a_critically_low_battery_contact():
    algo = DasfVRouting(battery_low_pct=0.15)
    holder = _node(1)
    contact = _node(2)
    contact.battery_mah = 10.0
    msg = _msg()
    msg.routing_state["tokens"] = 8
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_cold_start_replicates_once_to_a_mule_when_utility_is_near_zero():
    algo = DasfVRouting(eps=0.01)
    holder = _node(1)
    contact = _node(2)
    _make_mule(algo, contact)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD
    forwarded = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    algo.on_forward(msg, holder, contact, forwarded)
    assert msg.msg_id in holder.buffer
    assert msg.routing_state.get("mule_replicated") is True
    assert forwarded.routing_state["tokens"] == 1
    assert forwarded.routing_state.get("mule_replicated") is True


def test_cold_start_replication_does_not_repeat_once_flagged():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    _make_mule(algo, contact)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    msg.routing_state["mule_replicated"] = True
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_engine_integration_spray_splits_tokens_between_holder_and_contact():
    sender = BaseNode(node_id=1, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    contact = BaseNode(node_id=2, position=Position(5.0, 0.0), radio_range_m=20.0, buffer_capacity=10, battery_mah=100.0)
    grid = SpatialGrid(100.0, 100.0, cell_size_m=20.0)
    grid.insert(sender)
    grid.insert(contact)
    msg = _msg()
    msg.routing_state["tokens"] = 8
    sender.store_message(msg)
    metrics = MetricsCollector()
    energy_model = EnergyModel(EnergyConfig())
    algo = DasfVRouting()
    process_node_contacts(now=1.0, sender=sender, grid=grid, routing_algorithm=algo, energy_model=energy_model, metrics=metrics)
    assert sender.buffer[1].routing_state["tokens"] == 4
    assert contact.buffer[1].routing_state["tokens"] == 4


def test_transitive_utility_update_is_not_mistaken_for_a_real_sighting():
    algo = DasfVRouting(enable_transitivity=True, two_hop_freshness_s=5.0)
    a, b, c = _node(1), _node(2), _node(3)
    _meet(algo, b, c, 0.0)
    _meet(algo, a, b, 1.0)
    assert algo._decayed(a.id, c.id, 1.0) > 0.0
    assert not algo._recently_seen(a.id, c.id, 1.0)
    assert algo._density(a.id, 1.0) == 1


def test_density_counts_every_on_tick_neighbour_not_only_those_decide_sees():
    algo = DasfVRouting(l_base=8, k_min=2, l_max=32, d_ref=20.0)
    holder = _node(1)
    algo.on_tick(0.0, {holder.id: [_node(1000 + i) for i in range(20)]})
    msg = _msg()
    holder.store_message(msg)
    algo.decide(msg, holder, _node(2), now=0.0)
    assert msg.routing_state["tokens"] == 8


def test_a_contact_spanning_several_ticks_is_one_encounter():
    algo = DasfVRouting(p_encounter_init=0.5)
    a, b = _node(1), _node(2)
    for t in (0.0, 1.0, 2.0):
        _meet(algo, a, b, t)
    assert algo._predictability[a.id][b.id] == pytest.approx(0.5)
    algo.on_tick(5.0, {})  # apart for a tick
    _meet(algo, a, b, 10.0)
    assert algo._predictability[a.id][b.id] > 0.5


def test_stable_neighbourhood_has_no_turnover_right_after_a_window_rotation():
    algo = DasfVRouting(window_rotation_s=5.0)
    node = _node(1)
    neighbours = [_node(10 + i) for i in range(5)]
    for t in (0.0, 5.0):
        for n in neighbours:
            _meet(algo, node, n, t)
    # First tick of a fresh window: only one neighbour re-seen so far.
    _meet(algo, node, neighbours[0], 10.0)
    assert algo._turnover(node.id) == 0.0


def test_turnover_is_unknown_after_a_gap_in_observations():
    algo = DasfVRouting(window_rotation_s=5.0)
    node = _node(1)
    for i in range(5):
        _meet(algo, node, _node(10 + i), 0.0)
    for i in range(5):
        _meet(algo, node, _node(20 + i), 5.0)
    _meet(algo, node, _node(30), 5000.0)
    assert algo._turnover(node.id) == 0.0


def test_a_beacon_is_never_a_mule():
    algo = DasfVRouting()
    beacon = BeaconNode(node_id=5, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=50)
    _make_mule(algo, beacon)
    assert not algo._is_mule(beacon)


def test_a_stationary_phone_is_not_a_mule_even_with_high_turnover():
    algo = DasfVRouting(window_rotation_s=5.0)
    phone = _node(1)
    for t in (0.0, 5.0, 10.0):
        _meet(algo, phone, _node(100 + int(t)), t)
    algo._prev_window_contacts[phone.id] = {5, 6, 7}
    algo._prev2_window_contacts[phone.id] = {1, 2, 3}
    assert not algo._is_mule(phone)


def test_a_walking_phone_with_high_turnover_is_a_mule():
    algo = DasfVRouting(window_rotation_s=5.0, mule_min_speed_mps=0.3)
    phone = _node(1)
    for t, x in ((0.0, 0.0), (5.0, 6.0)):
        phone.position = Position(x, 0.0)
        _meet(algo, phone, _node(100 + int(t)), t)
    algo._prev_window_contacts[phone.id] = {5, 6, 7}
    algo._prev2_window_contacts[phone.id] = {1, 2, 3}
    assert algo._is_mule(phone)


def test_sightings_older_than_the_windows_are_forgotten():
    algo = DasfVRouting()
    a, b, c = _node(1), _node(2), _node(3)
    _meet(algo, a, b, 0.0)
    algo.on_tick(1.0, {})
    _meet(algo, a, c, 30.0)
    assert algo._last_seen[a.id] == {c.id: 30.0}
    assert b.id not in algo._last_seen
    assert algo._density(a.id, 30.0) == 1
