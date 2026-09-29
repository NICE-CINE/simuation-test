from __future__ import annotations
from dataclasses import replace
import pytest
from festival_ble_sim.config import AreaConfig, SimulationConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.gossip_a import GossipARouting
from festival_ble_sim.simulation import run_simulation


def _node(node_id, buffer_capacity=50):
    return BaseNode(
        node_id=node_id, position=Position(0.0, 0.0), radio_range_m=20.0,
        buffer_capacity=buffer_capacity, battery_mah=100.0,
    )


def _msg(msg_id=1, dst_id=99, hops=0, size_bytes=10):
    return Message(
        msg_id=msg_id, src_id=1, dst_id=dst_id, size_bytes=size_bytes, creation_time=0.0, ttl_s=1000.0, hops=hops
    )


def _forward(algo, msg, holder, contact):
    copy = replace(msg, hops=msg.hops + 1, routing_state=dict(msg.routing_state))
    contact.store_message(copy)
    algo.on_forward(msg, holder, contact, copy)
    return copy


def _make_dense(algo, node_id, n_neighbors, now):
    for i in range(n_neighbors):
        algo._record_encounter(node_id, 1000 + i, now)


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        GossipARouting(p_min=0.0)
    with pytest.raises(ValueError):
        GossipARouting(c=0.0)
    with pytest.raises(ValueError):
        GossipARouting(h_max=0)


def test_first_k_flood_hops_are_always_forwarded():
    algo = GossipARouting(k_flood=2)
    holder = _node(1)
    _make_dense(algo, holder.id, 200, now=0.0)
    for hops in (0, 1):
        assert algo.forward_probability(_msg(hops=hops), holder, now=0.0) == 1.0


def test_probability_is_one_in_sparse_area():
    algo = GossipARouting(c=4.0, k_flood=0)
    holder = _node(1)
    _make_dense(algo, holder.id, 2, now=0.0)
    assert algo.forward_probability(_msg(hops=3), holder, now=0.0) == 1.0


def test_probability_is_c_over_density_in_dense_area():
    algo = GossipARouting(c=4.0, p_min=0.05, k_flood=0)
    holder = _node(1)
    _make_dense(algo, holder.id, 20, now=0.0)
    assert algo.forward_probability(_msg(hops=3), holder, now=0.0) == pytest.approx(0.2)


def test_probability_is_floored_at_p_min():
    algo = GossipARouting(c=4.0, p_min=0.05, k_flood=0)
    holder = _node(1)
    _make_dense(algo, holder.id, 500, now=0.0)
    assert algo.forward_probability(_msg(hops=3), holder, now=0.0) == pytest.approx(0.05)


def test_constant_p_ablation_ignores_density():
    algo = GossipARouting(k_flood=0, adaptive=False)
    holder = _node(1)
    _make_dense(algo, holder.id, 500, now=0.0)
    assert algo.forward_probability(_msg(hops=3), holder, now=0.0) == 1.0


def test_density_is_smoothed_by_ewma():
    algo = GossipARouting(density_ewma_alpha=0.5, density_window_s=10.0)
    _make_dense(algo, 1, 10, now=0.0)
    assert algo.density(1, now=0.0) == pytest.approx(10.0)
    assert algo.density(1, now=20.0) == pytest.approx(5.0)  # all sightings stale -> raw 0


def test_probability_is_zero_at_h_max():
    algo = GossipARouting(h_max=15)
    assert algo.forward_probability(_msg(hops=15), _node(1), now=0.0) == 0.0


def test_ignores_contact_already_holding_message_and_counts_it_as_holder():
    algo = GossipARouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    contact.store_message(_msg())
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    assert algo.replication(holder.id, msg.msg_id, now=0.0) == 1
    assert algo.replication(contact.id, msg.msg_id, now=0.0) == 1


def test_message_seen_at_k_sup_neighbours_is_suppressed():
    algo = GossipARouting(k_flood=0, k_sup=3, suppression_window_s=60.0)
    holder = _node(1)
    msg = _msg(hops=3)
    holder.store_message(msg)
    for peer_id in (10, 11, 12):
        peer = _node(peer_id)
        peer.store_message(_msg(hops=3))
        algo.decide(msg, holder, peer, now=0.0)
    assert algo.forward_probability(msg, holder, now=10.0) == 0.0
    assert algo.forward_probability(msg, holder, now=100.0) > 0.0  # holders aged out of the window


def test_suppression_can_be_disabled_for_ablation():
    algo = GossipARouting(k_flood=0, k_sup=1, suppression=False)
    holder, peer = _node(1), _node(2)
    msg = _msg(hops=3)
    holder.store_message(msg)
    peer.store_message(_msg(hops=3))
    algo.decide(msg, holder, peer, now=0.0)
    assert algo.forward_probability(msg, holder, now=0.0) == 1.0


def test_refused_draw_sticks_for_the_rest_of_the_session():
    algo = GossipARouting(c=1.0, p_min=0.05, k_flood=0, session_cooldown_s=60.0, seed=3)
    holder = _node(1)
    _make_dense(algo, holder.id, 1000, now=0.0)
    contact = _node(2)
    msg = _msg(hops=3)
    holder.store_message(msg)
    decisions = [algo.decide(msg, holder, contact, now=float(t)) for t in range(30)]
    assert len(set(decisions)) == 1


def test_draw_is_per_peer():
    algo = GossipARouting(c=1.0, p_min=0.5, k_flood=0, seed=0)
    holder = _node(1)
    _make_dense(algo, holder.id, 1000, now=0.0)
    msg = _msg(hops=3)
    holder.store_message(msg)
    decisions = {algo.decide(msg, holder, _node(10 + i), now=0.0) for i in range(40)}
    assert decisions == {RoutingDecision.FORWARD, RoutingDecision.IGNORE}


def test_session_byte_budget_caps_forwarding_to_one_peer():
    algo = GossipARouting(session_budget_bytes=25, max_bundles_per_peer_per_session=None)
    holder, contact = _node(1), _node(2)
    msgs = [_msg(msg_id=i) for i in range(1, 4)]
    for m in msgs:
        holder.store_message(m)
    sent = 0
    for m in msgs:
        if algo.decide(m, holder, contact, now=0.0) is RoutingDecision.FORWARD:
            _forward(algo, m, holder, contact)
            sent += 1
    assert sent == 2


def test_bundle_limit_per_peer_resets_after_cooldown():
    algo = GossipARouting(session_budget_bytes=None, max_bundles_per_peer_per_session=1, session_cooldown_s=60.0)
    holder, contact = _node(1), _node(2)
    m1, m2 = _msg(msg_id=1), _msg(msg_id=2)
    holder.store_message(m1)
    holder.store_message(m2)
    assert algo.decide(m1, holder, contact, now=0.0) is RoutingDecision.FORWARD
    _forward(algo, m1, holder, contact)
    assert algo.decide(m2, holder, contact, now=1.0) is RoutingDecision.IGNORE
    assert algo.decide(m2, holder, contact, now=61.0) is RoutingDecision.FORWARD


def test_delivery_mints_purge_token_and_drops_holder_copy():
    algo = GossipARouting()
    holder = _node(1)
    msg = _msg(dst_id=99)
    holder.store_message(msg)
    algo.on_delivered(msg, holder)
    assert msg.msg_id not in holder.buffer
    assert algo.knows_purge(99, msg.msg_id)
    assert algo.knows_purge(holder.id, msg.msg_id)


def test_purge_tokens_spread_epidemically_and_purge_copies_on_contact():
    algo = GossipARouting()
    a, b, c = _node(1), _node(2), _node(3)
    msg = _msg(dst_id=99)
    a.store_message(msg)
    b.store_message(_msg(dst_id=99))
    algo.on_delivered(msg, c)  # c learnt the token; a and b still hold copies
    other = _msg(msg_id=2)
    c.store_message(other)
    algo.decide(other, c, b, now=0.0)
    assert msg.msg_id not in b.buffer
    assert algo.knows_purge(b.id, msg.msg_id)
    assert algo.decide(a.buffer[msg.msg_id], a, b, now=1.0) is RoutingDecision.IGNORE
    assert msg.msg_id not in a.buffer


def test_node_holding_purge_token_refuses_the_message():
    algo = GossipARouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    algo._add_purges(contact, [msg.msg_id])
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    assert msg.msg_id not in holder.buffer


def test_purge_token_store_is_capped_oldest_first():
    algo = GossipARouting(max_purge_tokens=2)
    node = _node(1)
    algo._add_purges(node, [1, 2, 3])
    assert not algo.knows_purge(1, 1)
    assert algo.knows_purge(1, 3)


def test_eviction_prefers_purged_then_most_replicated_then_farthest():
    algo = GossipARouting()
    node = _node(1)
    node.store_message(_msg(msg_id=1, hops=5))
    node.store_message(_msg(msg_id=2, hops=1))
    node.store_message(_msg(msg_id=3, hops=2))
    for peer in (10, 11):
        algo._note_holder(node.id, 2, peer, now=0.0)
    assert algo.choose_eviction(node, now=0.0) == 2
    algo._purges[node.id] = {3: None}
    assert algo.choose_eviction(node, now=0.0) == 3


def test_eviction_falls_back_to_fifo_when_disabled():
    algo = GossipARouting(replicated_first_eviction=False)
    node = _node(1)
    node.store_message(_msg())
    assert algo.choose_eviction(node, now=0.0) is None


def test_bloom_false_positive_rate_matches_spec_order_of_magnitude():
    algo = GossipARouting()
    assert algo._bloom_false_positive(0) == 0.0
    assert 0.01 < algo._bloom_false_positive(500) < 0.03


def test_end_to_end_run_delivers_messages():
    config = SimulationConfig(
        duration_s=300.0, num_festivaliers=40, random_seed=7, area=AreaConfig(width_m=100.0, height_m=100.0)
    )
    report = run_simulation(config, routing_algorithm=GossipARouting())
    assert 0.0 <= report.delivery_ratio <= 1.0
    assert report.messages_delivered > 0
