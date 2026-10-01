from __future__ import annotations
import pytest
import random
from festival_ble_sim.config import SimulationConfig, SocialConfig
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode, BeaconNode
from festival_ble_sim.routing.base import RoutingDecision
from festival_ble_sim.routing.bubble_f import BubbleFRouting
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.social import assign_friend_groups


def _node(node_id, capacity=50):
    return BaseNode(
        node_id=node_id, position=Position(0.0, 0.0), radio_range_m=20.0, buffer_capacity=capacity, battery_mah=100.0
    )


def _people(n, group_size_range=(2, 8)):
    nodes = {i: _node(i) for i in range(1, n + 1)}
    config = SocialConfig(group_size_range=group_size_range, no_friend_fraction=0.0)
    for node_id, friends in assign_friend_groups(list(nodes), config, random.Random(1)).items():
        nodes[node_id].friends = friends
    return nodes


def _msg(msg_id=1, src_id=1, dst_id=99, ttl_s=100000.0):
    return Message(msg_id=msg_id, src_id=src_id, dst_id=dst_id, size_bytes=10, creation_time=0.0, ttl_s=ttl_s)


def _set_ranks(algo, node_id, global_rank, local_rank, now=0.0):
    algo._rank_cache[node_id] = (now, global_rank, local_rank)


def _decide_and_forward(algo, msg, holder, contact, now):
    decision = algo.decide(msg, holder, contact, now)
    if decision is RoutingDecision.FORWARD:
        copy = Message(**{**msg.__dict__, "routing_state": dict(msg.routing_state)})
        contact.store_message(copy)
        algo.on_forward(msg, holder, contact, copy)
        return decision, copy
    return decision, None


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        BubbleFRouting(l_base=0)


def test_friend_groups_come_from_shared_graph_and_skip_beacons():
    algo = BubbleFRouting()
    nodes = _people(100)
    nodes[200] = BeaconNode(node_id=200, position=Position(0.0, 0.0), radio_range_m=50.0, buffer_capacity=50)
    algo.on_simulation_start(nodes)
    assert 200 not in algo._groups
    for member, group in algo._groups.items():
        assert member in group
        assert 2 <= len(group) <= 8
        assert algo._community_of(member) == group
        assert group == nodes[member].friends | {member}


def test_disabling_friend_bootstrap_starts_from_singleton_communities():
    algo = BubbleFRouting(friend_bootstrap=False)
    algo.on_simulation_start(_people(10))
    assert algo._groups
    assert algo._community_of(1) == {1}


def test_ignores_when_contact_already_has_message():
    algo = BubbleFRouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    contact.store_message(_msg())
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_purges_copy_once_message_is_delivered_elsewhere():
    algo = BubbleFRouting()
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    algo.on_delivered(msg, holder)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    assert msg.msg_id not in holder.buffer


def test_entering_the_bubble_splits_tokens():
    algo = BubbleFRouting(l_base=8)
    algo._community[2] = {2, 99}
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    decision, copy = _decide_and_forward(algo, msg, holder, contact, now=10.0)
    assert decision is RoutingDecision.FORWARD
    assert msg.routing_state["tokens"] == 4
    assert copy.routing_state["tokens"] == 4
    assert msg.routing_state["last_progress"] == 10.0


def test_inside_bubble_only_forwards_to_more_locally_central_member():
    algo = BubbleFRouting(delta_l=1)
    algo._community[1] = {1, 99}
    algo._community[2] = {2, 99}
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    _set_ranks(algo, 1, 0, 3)
    _set_ranks(algo, 2, 50, 4)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    _set_ranks(algo, 2, 0, 5)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD


def test_inside_bubble_never_forwards_outside_it_even_to_a_hub():
    algo = BubbleFRouting()
    algo._community[1] = {1, 99}
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    _set_ranks(algo, 2, 200, 200)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE


def test_outside_bubble_climbs_global_rank():
    algo = BubbleFRouting(delta_g=2)
    holder, contact = _node(1), _node(2)
    msg = _msg()
    holder.store_message(msg)
    _set_ranks(algo, 1, 10, 0)
    _set_ranks(algo, 2, 12, 0)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    _set_ranks(algo, 2, 13, 0)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD


def test_last_token_is_moved_not_copied():
    algo = BubbleFRouting()
    algo._community[2] = {2, 99}
    holder, contact = _node(1), _node(2)
    msg = _msg()
    msg.routing_state["tokens"] = 1
    holder.store_message(msg)
    _, copy = _decide_and_forward(algo, msg, holder, contact, now=0.0)
    assert msg.msg_id not in holder.buffer
    assert copy.routing_state["tokens"] == 1


def test_two_hop_relay_gives_one_token():
    algo = BubbleFRouting()
    holder, contact, dst = _node(1), _node(2), _node(99)
    algo.decide(_msg(msg_id=50), contact, dst, now=10.0)
    msg = _msg()
    holder.store_message(msg)
    _, copy = _decide_and_forward(algo, msg, holder, contact, now=12.0)
    assert copy.routing_state["tokens"] == 1
    assert msg.routing_state["tokens"] == 7


def test_two_hop_relay_can_be_disabled():
    algo = BubbleFRouting(two_hop_relay=False)
    holder, contact, dst = _node(1), _node(2), _node(99)
    algo.decide(_msg(msg_id=50), contact, dst, now=10.0)
    msg = _msg()
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=12.0) is RoutingDecision.IGNORE


def test_stuck_message_replicates_once_to_non_community_member():
    algo = BubbleFRouting(t_stuck_s=100.0)
    holder, contact, other = _node(1), _node(2), _node(3)
    msg = _msg()
    msg.routing_state.update(tokens=1, last_progress=0.0)
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=50.0) is RoutingDecision.IGNORE
    decision, copy = _decide_and_forward(algo, msg, holder, contact, now=200.0)
    assert decision is RoutingDecision.FORWARD
    assert msg.msg_id in holder.buffer
    assert msg.routing_state["tokens"] == 1
    assert msg.routing_state["stuck_replicated"] is True
    assert copy.routing_state["stuck_replicated"] is True
    assert algo.stuck_replications == 1
    assert algo.decide(msg, holder, other, now=300.0) is RoutingDecision.IGNORE


def test_stuck_message_is_not_replicated_to_own_community():
    algo = BubbleFRouting(t_stuck_s=100.0)
    algo._community[1] = {1, 2}
    holder, contact = _node(1), _node(2)
    msg = _msg()
    msg.routing_state.update(tokens=1, last_progress=0.0)
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=200.0) is RoutingDecision.IGNORE


def test_full_contact_only_admits_messages_for_its_own_bubble():
    algo = BubbleFRouting(admission_threshold=0.8)
    holder, contact = _node(1), _node(2, capacity=10)
    for i in range(8):
        contact.store_message(_msg(msg_id=100 + i))
    algo._community[2] = {2}
    _set_ranks(algo, 2, 200, 0)
    msg = _msg()
    holder.store_message(msg)
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.IGNORE
    algo._community[2] = {2, 99}
    assert algo.decide(msg, holder, contact, now=0.0) is RoutingDecision.FORWARD


def test_long_contact_makes_node_familiar_and_community_member():
    algo = BubbleFRouting(t_fam_s=60.0, observation_interval_s=10.0)
    a, b = _node(1), _node(2)
    for t in range(10, 80, 10):
        algo.on_tick(float(t), {1: [b], 2: [a]})
    assert 2 in algo._familiar[1]
    assert 2 in algo._community_of(1)


def test_overlap_rule_adds_peer_sharing_familiars_with_my_community():
    algo = BubbleFRouting(lambda_add=0.6)
    algo._community[1] = {1, 10, 11}
    algo._familiar[2] = {10, 11, 50}
    algo._social_exchange(1, 2, now=0.0)
    assert 2 in algo._community_of(1)


def test_merge_imports_peer_community_when_overlap_is_large():
    algo = BubbleFRouting(gamma_merge=0.6)
    algo._community[1] = {1, 2, 10, 11, 12}
    algo._community[2] = {1, 2, 10, 11, 12, 13}
    algo._social_exchange(1, 2, now=0.0)
    assert 13 in algo._community_of(1)


def test_merge_is_capped_at_c_max():
    algo = BubbleFRouting(gamma_merge=0.0, c_max=4)
    algo._community[1] = {1, 2}
    algo._community[2] = {2, 20, 21, 22, 23}
    algo._social_exchange(1, 2, now=0.0)
    assert len(algo._community_of(1)) == 4


def test_global_rank_counts_distinct_meetings_per_window():
    algo = BubbleFRouting(t_meet_s=30.0, window_s=100.0, observation_interval_s=10.0, rank_refresh_s=10.0)
    others = [_node(i) for i in range(2, 6)]
    for t in range(10, 101, 10):
        algo.on_tick(float(t), {1: others})
    global_rank, local_rank = algo._ranks(1, 100.0)
    assert global_rank == 4
    assert local_rank == 0


def test_epoch_change_keeps_friends_and_drops_other_members():
    algo = BubbleFRouting(epoch_s=1000.0)
    algo.on_simulation_start(_people(2, group_size_range=(2, 2)))
    algo._ensure_epoch(1, 0.0)
    algo._community_of(1).add(42)
    algo._familiar[1] = {42}
    algo._ensure_epoch(1, 1500.0)
    assert algo._community_of(1) == {1, 2}
    assert 1 not in algo._familiar


def test_community_jaccard_is_one_right_after_bootstrap():
    algo = BubbleFRouting()
    algo.on_simulation_start(_people(20))
    assert algo.community_jaccard() == 1.0


def test_runs_end_to_end_in_a_small_simulation():
    config = SimulationConfig(duration_s=300.0, num_festivaliers=40, random_seed=3)
    algo = BubbleFRouting(t_fam_s=60.0, window_s=120.0, t_stuck_s=60.0)
    report = run_simulation(config, routing_algorithm=algo)
    assert report.delivery_ratio >= 0.0
    assert algo._contact_dur
