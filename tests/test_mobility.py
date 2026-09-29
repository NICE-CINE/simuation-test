import random
import pytest
from festival_ble_sim.config import AreaConfig, MobilityConfig
from festival_ble_sim.models import Position
from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility, move_towards


def test_move_towards_advances_by_speed_times_dt_when_far():
    current = Position(0.0, 0.0)
    target = Position(100.0, 0.0)
    result = move_towards(current, target, speed_mps=2.0, dt=1.0)
    assert result.x == pytest.approx(2.0)
    assert result.y == pytest.approx(0.0)


def test_move_towards_stops_at_target_when_close():
    current = Position(0.0, 0.0)
    target = Position(1.0, 0.0)
    result = move_towards(current, target, speed_mps=10.0, dt=1.0)
    assert result.x == pytest.approx(1.0)
    assert result.y == pytest.approx(0.0)


def test_move_towards_no_movement_when_already_at_target():
    current = Position(5.0, 5.0)
    target = Position(5.0, 5.0)
    result = move_towards(current, target, speed_mps=2.0, dt=1.0)
    assert result.x == pytest.approx(5.0)
    assert result.y == pytest.approx(5.0)


def test_initial_position_within_area_bounds():
    area = AreaConfig(width_m=100.0, height_m=50.0)
    mobility = RandomWaypointMobility(MobilityConfig(), rng=random.Random(1))
    for _ in range(50):
        pos = mobility.initial_position(area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m


def test_step_keeps_position_within_area_bounds():
    area = AreaConfig(width_m=50.0, height_m=50.0)
    config = MobilityConfig(speed_min_mps=1.0, speed_max_mps=3.0, pause_probability=0.2, tick_interval_s=1.0)
    mobility = RandomWaypointMobility(config, rng=random.Random(2))
    pos = mobility.initial_position(area)
    for _ in range(500):
        pos = mobility.step(pos, dt=1.0, area=area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m
