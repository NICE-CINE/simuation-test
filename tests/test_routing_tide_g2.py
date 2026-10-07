from __future__ import annotations
import random
from festival_ble_sim.config import AreaConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.models import Position
from festival_ble_sim.nodes import BaseNode
from festival_ble_sim.simulation import run_simulation


def _node(node_id, x):
    return BaseNode(
        node_id=node_id, position=Position(x, 0.0), radio_range_m=20.0, buffer_capacity=50, battery_mah=100.0
    )


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

    off, explicit_off, on = run(), run(followup_probability=0.0), run(followup_probability=0.6)
    assert off == explicit_off
    assert on.messages_created > off.messages_created
