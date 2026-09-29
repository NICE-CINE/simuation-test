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
