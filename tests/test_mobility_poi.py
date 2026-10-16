import random
import pytest
from festival_ble_sim.config import AreaConfig, MobilityConfig, PointOfInterest
from festival_ble_sim.mobility.poi import PoiMobility


def _config(**overrides):
    defaults = dict(
        speed_min_mps=1.0,
        speed_max_mps=3.0,
        pause_probability=0.0,
        pause_duration_range_s=(1.0, 2.0),
        tick_interval_s=1.0,
        points_of_interest=(PointOfInterest(x=50.0, y=50.0, radius_m=5.0, weight=1.0),),
    )
    defaults.update(overrides)
    return MobilityConfig(**defaults)


def test_requires_at_least_one_point_of_interest():
    with pytest.raises(ValueError):
        PoiMobility(MobilityConfig(points_of_interest=()), rng=random.Random(1))


def test_initial_position_within_area_bounds():
    area = AreaConfig(width_m=100.0, height_m=100.0)
    mobility = PoiMobility(_config(), rng=random.Random(1))
    for _ in range(50):
        pos = mobility.initial_position(area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m


def test_step_keeps_position_within_area_bounds():
    area = AreaConfig(width_m=100.0, height_m=100.0)
    mobility = PoiMobility(_config(), rng=random.Random(2))
    pos = mobility.initial_position(area)
    for _ in range(500):
        pos = mobility.step(pos, dt=1.0, area=area)
        assert 0.0 <= pos.x <= area.width_m
        assert 0.0 <= pos.y <= area.height_m


def test_agent_converges_towards_the_single_point_of_interest():
    area = AreaConfig(width_m=200.0, height_m=200.0)
    config = _config(points_of_interest=(PointOfInterest(x=100.0, y=100.0, radius_m=2.0, weight=1.0),))
    mobility = PoiMobility(config, rng=random.Random(3))
    pos = mobility.initial_position(area)
    start_distance = pos.distance_to(_poi_position(config))
    for _ in range(200):
        pos = mobility.step(pos, dt=1.0, area=area)
    end_distance = pos.distance_to(_poi_position(config))
    assert end_distance < start_distance


def test_only_positive_weight_pois_are_ever_reachable_target():
    area = AreaConfig(width_m=200.0, height_m=200.0)
    near_poi = PointOfInterest(x=10.0, y=10.0, radius_m=1.0, weight=0.0)
    far_poi = PointOfInterest(x=190.0, y=190.0, radius_m=1.0, weight=1.0)
    config = _config(points_of_interest=(near_poi, far_poi), speed_min_mps=50.0, speed_max_mps=50.0)
    mobility = PoiMobility(config, rng=random.Random(4))
    pos = mobility.initial_position(area)
    for _ in range(20):
        pos = mobility.step(pos, dt=1.0, area=area)
    assert pos.distance_to(_poi_position(config, index=1)) < pos.distance_to(_poi_position(config, index=0))


def _poi_position(config, index=0):
    from festival_ble_sim.models import Position

    poi = config.points_of_interest[index]
    return Position(poi.x, poi.y)


def test_background_probability_defaults_to_none_and_keeps_old_behaviour():
    assert MobilityConfig().background_probability is None


def test_full_background_probability_spreads_targets_over_the_whole_area():
    area = AreaConfig(width_m=200.0, height_m=200.0)
    config = _config(background_probability=1.0)
    mobility = PoiMobility(config, rng=random.Random(4))
    xs = [mobility.initial_position(area).x for _ in range(200)]
    assert max(xs) - min(xs) > 100.0


def test_zero_background_probability_confines_initial_positions_to_points_of_interest():
    area = AreaConfig(width_m=200.0, height_m=200.0)
    config = _config(background_probability=0.0)
    mobility = PoiMobility(config, rng=random.Random(5))
    for _ in range(100):
        pos = mobility.initial_position(area)
        assert abs(pos.x - 50.0) <= 5.0 and abs(pos.y - 50.0) <= 5.0


def test_background_probability_must_be_a_probability():
    with pytest.raises(ValueError):
        PoiMobility(_config(background_probability=1.5), rng=random.Random(1))


_STAGES = (PointOfInterest(x=20.0, y=20.0, radius_m=5.0), PointOfInterest(x=180.0, y=180.0, radius_m=5.0))


def _share_at_first_stage(model, area, draws=2000):
    return sum(model._poi_position(area).x < 100.0 for _ in range(draws)) / draws


def test_schedule_draws_the_crowd_to_the_stage_that_plays():
    from festival_ble_sim.config import ScheduleConfig
    area = AreaConfig(width_m=200.0, height_m=200.0)
    model = PoiMobility(_config(points_of_interest=_STAGES, schedule=ScheduleConfig(set_s=100.0)), random.Random(1))
    now = [50.0]
    model.set_clock(lambda: now[0])
    assert _share_at_first_stage(model, area) > 0.7
    now[0] = 150.0
    assert _share_at_first_stage(model, area) < 0.3


def test_a_set_starting_cuts_pauses():
    from festival_ble_sim.config import ScheduleConfig
    area = AreaConfig(width_m=200.0, height_m=200.0)
    config = _config(
        points_of_interest=_STAGES, pause_probability=1.0, pause_duration_range_s=(10000.0, 10000.0),
        schedule=ScheduleConfig(set_s=100.0, rush_probability=1.0),
    )
    model = PoiMobility(config, random.Random(1))
    now = [0.0]
    model.set_clock(lambda: now[0])
    position = model.initial_position(area)
    for _ in range(99):
        now[0] += 1.0
        position = model.step(position, 1.0, area)
    assert model._elapsed_s < model._pause_until
    now[0] = 101.0
    model.step(position, 1.0, area)
    assert model._pause_until == 0.0


def test_schedule_must_name_existing_stages():
    from festival_ble_sim.config import ScheduleConfig, SimulationConfig
    with pytest.raises(ValueError):
        SimulationConfig(mobility=_config(schedule=ScheduleConfig(stages=(0, 1))))
