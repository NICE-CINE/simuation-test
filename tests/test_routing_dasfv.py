from __future__ import annotations
from dataclasses import replace
import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.models import Message, Position
from festival_ble_sim.network import process_node_contacts
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.dasfv import DasfVRouting
from festival_ble_sim.spatial import SpatialGrid


def _node(node_id, battery_mah=100.0):
    return BaseNode(
        node_id=node_id, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=battery_mah
    )


def _msg(msg_id=1, src_id=1, dst_id=99, ttl_s=100.0):
    return Message(msg_id=msg_id, src_id=src_id, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=ttl_s)


def test_ignores_when_contact_already_has_message():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    holder.store_message(msg)
    contact.store_message(_msg())
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_purges_stale_copy_once_message_is_delivered_elsewhere():
    algo = DasfVRouting()
    holder = _node(1)
    contact = _node(2)
    msg = _msg()
    holder.store_message(msg)
    algo._delivered_ids.add(msg.msg_id)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    assert msg.msg_id not in holder.buffer


def test_on_delivered_marks_message_as_globally_delivered():
    algo = DasfVRouting()
    holder = _node(1)
    msg = _msg(dst_id=1)
    algo.on_delivered(msg, holder)
    assert msg.msg_id in algo._delivered_ids


def test_lazy_token_budget_is_dense_default_when_holder_has_no_recent_contacts():
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
        algo.decide(_msg(msg_id=100 + i), holder, _node(1000 + i), now=0.0)
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
    algo._window_contacts[contact.id] = {5, 6, 7}
    algo._prev_window_contacts[contact.id] = {1, 2, 3}
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
    algo.decide(_msg(msg_id=2, src_id=2, dst_id=1), contact, dst, now=0.0)
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
    algo.decide(_msg(msg_id=2, src_id=2, dst_id=1), contact, dst, now=0.0)
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
    algo.decide(_msg(msg_id=2, src_id=2, dst_id=99), contact, dst, now=0.0)
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
    algo.decide(_msg(msg_id=2, src_id=2, dst_id=99), contact, dst, now=0.0)
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
    algo.decide(_msg(msg_id=2, src_id=2, dst_id=99), contact, dst, now=0.0)
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
    algo._window_contacts[contact.id] = {5, 6, 7}
    algo._prev_window_contacts[contact.id] = {1, 2, 3}
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
    algo._window_contacts[contact.id] = {5, 6, 7}
    algo._prev_window_contacts[contact.id] = {1, 2, 3}
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
