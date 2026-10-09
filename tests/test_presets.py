import random
import pytest
from festival_ble_sim.config import AreaConfig
from festival_ble_sim.mobility.poi import PoiMobility
from festival_ble_sim.presets import (
    SITE_PRESETS,
    crowd_mobility_config,
    dense_zone_pois,
    site_area,
)


def test_presets_cover_the_four_sizes():
    assert set(SITE_PRESETS) == {"small", "medium", "large", "extra-large"}
    assert [SITE_PRESETS[n].num_festivaliers for n in ("small", "medium", "large", "extra-large")] == [
        4000, 10000, 30000, 60000,
    ]


@pytest.mark.parametrize("name", sorted(SITE_PRESETS))
def test_every_preset_gives_about_three_square_meters_per_person(name):
    preset = SITE_PRESETS[name]
    area = site_area(name)
    assert (area.width_m, area.height_m) == (preset.width_m, preset.height_m)
    m2_per_person = area.width_m * area.height_m / preset.num_festivaliers
    assert m2_per_person == pytest.approx(3.0, rel=0.02)
    assert area.width_m / area.height_m == pytest.approx(1.4, rel=0.02)


def test_unknown_size_is_rejected():
    with pytest.raises(KeyError):
        site_area("gigantic")


@pytest.mark.parametrize("name", sorted(SITE_PRESETS))
def test_dense_zone_covers_the_requested_fraction_of_the_site(name):
    area = site_area(name)
    pois = dense_zone_pois(area, area_fraction=0.15)
    covered = sum((2 * p.radius_m) ** 2 for p in pois)
    assert covered == pytest.approx(0.15 * area.width_m * area.height_m, rel=1e-6)


@pytest.mark.parametrize("name", sorted(SITE_PRESETS))
def test_dense_zone_squares_stay_inside_the_site_and_do_not_overlap(name):
    area = site_area(name)
    pois = dense_zone_pois(area)
    for p in pois:
        assert p.x - p.radius_m >= -1e-9 and p.x + p.radius_m <= area.width_m + 1e-9
        assert p.y - p.radius_m >= -1e-9 and p.y + p.radius_m <= area.height_m + 1e-9
    for i, a in enumerate(pois):
        for b in pois[i + 1:]:
            assert abs(a.x - b.x) >= a.radius_m + b.radius_m or abs(a.y - b.y) >= a.radius_m + b.radius_m


def test_dense_zone_keeps_the_festival_layout_weights():
    pois = dense_zone_pois(site_area("small"))
    assert [p.weight for p in pois] == [4.0, 2.0, 3.0, 1.0]


def test_crowd_background_probability_accounts_for_background_visits_to_the_dense_zone():
    config = crowd_mobility_config(site_area("small"), dense_area_fraction=0.15, dense_population_share=0.70)
    # share = (1 - bg) + bg * fraction  =>  bg = (1 - share) / (1 - fraction)
    assert config.background_probability == pytest.approx(0.30 / 0.85)


def test_crowd_mobility_config_keeps_default_movement_parameters():
    area = site_area("small")
    config = crowd_mobility_config(area)
    assert config.points_of_interest == dense_zone_pois(area)
    assert config.pause_probability == 0.7


def test_simulated_crowd_puts_about_seventy_percent_in_the_dense_zone():
    area = site_area("small")
    config = crowd_mobility_config(area)
    squares = [(p.x - p.radius_m, p.x + p.radius_m, p.y - p.radius_m, p.y + p.radius_m) for p in config.points_of_interest]

    def in_dense_zone(pos):
        return any(x0 <= pos.x <= x1 and y0 <= pos.y <= y1 for x0, x1, y0, y1 in squares)

    agents = []
    for i in range(300):
        model = PoiMobility(config, rng=random.Random(i))
        agents.append([model, model.initial_position(area)])

    inside = total = 0
    for t in range(6000):
        for agent in agents:
            agent[1] = agent[0].step(agent[1], 1.0, area)
        if t >= 2000 and t % 100 == 0:
            for _, pos in agents:
                total += 1
                inside += in_dense_zone(pos)
    # People in transit between POIs are mostly outside the dense zone, so the
    # measured share lands a few points under the 70 % of the target choice.
    assert inside / total == pytest.approx(0.70, abs=0.08)


def test_resolve_cli_args_is_idempotent_with_a_size():
    import argparse
    from festival_ble_sim.presets import resolve_cli_args

    args = argparse.Namespace(size="small", num_festivaliers=None, mobility=None)
    resolve_cli_args(args, 200, ValueError)
    resolve_cli_args(args, 200, ValueError)
    assert (args.num_festivaliers, args.mobility) == (4000, "poi")


def test_resolve_cli_args_applies_script_defaults_without_size():
    import argparse
    from festival_ble_sim.presets import resolve_cli_args

    args = argparse.Namespace(size=None, num_festivaliers=None, mobility=None)
    resolve_cli_args(args, 200, ValueError)
    assert (args.num_festivaliers, args.mobility) == (200, "random_waypoint")
