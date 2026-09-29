import pytest
from festival_ble_sim.beacons import place_beacons
from festival_ble_sim.config import AreaConfig, BeaconConfig


def test_zero_beacons_returns_empty_list():
    assert place_beacons(AreaConfig(), BeaconConfig(count=0)) == []


def test_grid_placement_returns_requested_count_within_bounds():
    area = AreaConfig(width_m=100.0, height_m=100.0)
    positions = place_beacons(area, BeaconConfig(count=4, placement="grid"))
    assert len(positions) == 4
    for p in positions:
        assert 0.0 < p.x < area.width_m
        assert 0.0 < p.y < area.height_m


def test_manual_placement_converts_tuples():
    area = AreaConfig()
    positions = place_beacons(
        area, BeaconConfig(count=2, placement="manual", manual_positions=[(10.0, 20.0), (30.0, 40.0)])
    )
    assert positions[0].x == 10.0 and positions[0].y == 20.0
    assert positions[1].x == 30.0 and positions[1].y == 40.0


def test_manual_placement_without_positions_raises():
    with pytest.raises(ValueError):
        place_beacons(AreaConfig(), BeaconConfig(count=2, placement="manual", manual_positions=None))


def test_unknown_placement_mode_raises():
    with pytest.raises(ValueError):
        place_beacons(AreaConfig(), BeaconConfig(count=2, placement="bogus"))
