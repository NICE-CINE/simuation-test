from __future__ import annotations
import itertools
import random
import simpy
from festival_ble_sim.config import AreaConfig, MobilityConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.metrics import MetricsCollector
from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility
from festival_ble_sim.models import Message, Position
from festival_ble_sim.nodes import BaseNode, MobileNode
from festival_ble_sim.routing.tide_g import TIDE_G2_KWARGS, TideGRouting
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.traffic import followup_process


def _node(node_id, x):
    return BaseNode(
        node_id=node_id, position=Position(x, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=100.0
    )


def _mobile(node_id):
    return MobileNode(node_id, RandomWaypointMobility(MobilityConfig(), rng=random.Random(node_id)), 20.0, 50, 100.0, AreaConfig())


def _msg(dst_position=None, dst_position_time=None, msg_id=1, creation_time=0.0):
    return Message(
        msg_id=msg_id, src_id=1, dst_id=99, size_bytes=10, creation_time=creation_time, ttl_s=7200.0,
        dst_position=dst_position, dst_position_time=dst_position_time,
    )


def _algo_with(nodes, neighbors, **kwargs):
    # election=False: every node is a relay and takes an exact fix on the
    # first tick (GPS is noiseless outside a full simulation).
    algo = TideGRouting(max_syncs_per_minute=None, election=False, hint_cell_m=0.0, **kwargs)
    algo.on_simulation_start({n.id: n for n in nodes})
    algo.on_tick(1.0, neighbors)
    return algo


def _pair_with_destination(**kwargs):
    src, relay, dst = _node(1, 0.0), _node(2, 20.0), _node(99, 500.0)
    algo = _algo_with([src, relay, dst], {1: [relay], 2: [src], 99: []}, **kwargs)
    return algo, src, relay, dst


def test_ack_hint_reaches_the_source_after_the_return_trip():
    algo, src, relay, dst = _pair_with_destination(ack_hint=True)
    algo.on_tick(10.0, {1: [relay], 2: [src], 99: []})
    algo.on_delivered(_msg(creation_time=4.0), relay)
    algo.on_tick(15.0, {1: [relay], 2: [src], 99: []})
    assert 99 not in src.known_positions
    algo.on_tick(16.0, {1: [relay], 2: [src], 99: []})
    assert src.known_positions[99] == (Position(500.0, 0.0), 1.0)
    assert algo.hint_stats["ack_hints_sent"] == algo.hint_stats["ack_hints_received"] == 1


def test_ack_hint_is_off_by_default():
    algo, src, relay, dst = _pair_with_destination()
    algo.on_tick(10.0, {1: [relay], 2: [src], 99: []})
    algo.on_delivered(_msg(creation_time=4.0), relay)
    algo.on_tick(100.0, {1: [relay], 2: [src], 99: []})
    assert 99 not in src.known_positions


def test_hint_is_dropped_after_geo_giveup():
    algo = TideGRouting(geo_giveup_s=180.0)
    msg = _msg(Position(0.0, 0.0), 0.0)
    assert algo._hint(msg, 179.0) is not None
    assert algo._hint(msg, 181.0) is None


def test_fresh_hint_shrinks_only_the_first_spray():
    algo, src, relay, dst = _pair_with_destination(hint_scaled_tokens=True)
    msg = _msg(Position(500.0, 0.0), 1.0)
    src.store_message(msg)
    algo.decide(msg, src, relay, 1.0)
    assert msg.routing_state["tokens"] == 2 and msg.routing_state["l0"] == 16
    assert algo.hint_stats["scaled_tokens"] == 1


def test_stale_hint_keeps_the_full_tide_budget():
    algo, src, relay, dst = _pair_with_destination(hint_scaled_tokens=True)
    msg = _msg(Position(500.0, 0.0), 0.0, creation_time=400.0)
    src.store_message(msg)
    algo.decide(msg, src, relay, 400.0)
    assert msg.routing_state["tokens"] == msg.routing_state["l0"] == 16
    assert algo.hint_stats["scaled_tokens"] == 0


def test_relay_merges_a_fresher_hint_from_its_buffer():
    algo, src, relay, dst = _pair_with_destination(relay_hint_merge=True)
    relay.store_message(_msg(Position(450.0, 0.0), 50.0, msg_id=2))
    msg = _msg(Position(100.0, 0.0), 0.0)
    relay.store_message(msg)
    algo.decide(msg, relay, src, 60.0)
    assert msg.dst_position == Position(450.0, 0.0) and msg.dst_position_time == 50.0
    assert algo.hint_stats["merged_hints"] == 1


def test_relay_merge_is_off_by_default():
    algo, src, relay, dst = _pair_with_destination()
    relay.store_message(_msg(Position(450.0, 0.0), 50.0, msg_id=2))
    msg = _msg(Position(100.0, 0.0), 0.0)
    relay.store_message(msg)
    algo.decide(msg, relay, src, 60.0)
    assert msg.dst_position_time == 0.0


def test_send_fix_is_charged_only_without_a_fresh_periodic_fix():
    algo, src, relay, dst = _pair_with_destination(
        charge_message_fixes=True, gps_current_ma=36.0, gps_for_relays=False
    )
    msg = _msg()
    src.store_message(msg)
    algo.decide(msg, src, relay, 1.0)
    assert abs(src.battery_mah - 99.95) < 1e-9 and algo.hint_stats["message_fixes"] == 1

    algo, src, relay, dst = _pair_with_destination(charge_message_fixes=True, gps_current_ma=36.0)
    assert abs(src.battery_mah - 99.7) < 1e-9
    msg = _msg()
    src.store_message(msg)
    algo.decide(msg, src, relay, 1.0)
    assert abs(src.battery_mah - 99.7) < 1e-9 and algo.hint_stats["message_fixes"] == 0


def test_gps_fix_fails_with_its_probability_and_matches_gps_position_at_zero():
    a, b = _node(1, 0.0), _node(2, 0.0)
    a.gps_noise_std_m = b.gps_noise_std_m = 5.0
    a.gps_rng, b.gps_rng = random.Random(7), random.Random(7)
    assert [a.gps_fix() for _ in range(20)] == [b.gps_position() for _ in range(20)]

    a.gps_fix_failure_probability = 0.5
    failures = sum(a.gps_fix() is None for _ in range(2000))
    assert 900 < failures < 1100


def test_followups_add_messages_without_changing_runs_where_they_are_off():
    def run(**traffic):
        config = SimulationConfig(
            duration_s=600.0, num_festivaliers=40, random_seed=5,
            area=AreaConfig(width_m=150.0, height_m=150.0),
            traffic=TrafficConfig(messages_per_hour_range=(4.0, 8.0), **traffic),
        )
        return run_simulation(config)

    assert run(followup_probability=0.6).messages_created > run().messages_created


def test_followup_chain_stops_once_the_destination_is_gone():
    env = simpy.Environment()
    src, dst = _mobile(1), _mobile(2)
    dst.is_active = False
    config = TrafficConfig(followup_probability=0.99)
    env.process(followup_process(
        env, src, 2, {1: src, 2: dst}, config, MetricsCollector(), itertools.count(1), random.Random(0)
    ))
    env.run()
    assert env.now <= config.followup_delay_range_s[1]


def test_tide_g_is_unchanged_with_every_tide_g2_flag_off():
    # Golden values from main before TIDE-G2 landed (rerun with l_max=16): any drift means a
    # default-off addition leaked into tide_g.
    config = SimulationConfig(
        duration_s=600.0, num_festivaliers=60, random_seed=3,
        area=AreaConfig(width_m=120.0, height_m=120.0),
        traffic=TrafficConfig(messages_per_hour_range=(4.0, 8.0), reply_probability=0.9),
    )
    algo = TideGRouting(seed=3)
    report = run_simulation(config, routing_algorithm=algo)
    assert (report.messages_created, report.messages_delivered, report.total_transmissions) == (83, 68, 1369)
    assert {k: algo.hint_stats[k] for k in ("routed", "hinted", "delivered", "delivered_hinted", "gps_fixes")} == {
        "routed": 82, "hinted": 45, "delivered": 68, "delivered_hinted": 42, "gps_fixes": 1200,
    }


def test_small_festival_tide_g2_hints_messages_from_acks():
    config = SimulationConfig(
        duration_s=900.0, num_festivaliers=60, random_seed=3,
        area=AreaConfig(width_m=120.0, height_m=120.0),
        traffic=TrafficConfig(messages_per_hour_range=(4.0, 8.0), followup_probability=0.6),
    )
    algo = TideGRouting(seed=3, **TIDE_G2_KWARGS)
    report = run_simulation(config, routing_algorithm=algo)
    assert report.messages_delivered > 0
    assert algo.hint_stats["ack_hints_received"] > 0 and algo.hint_stats["hinted_by_ack"] > 0
