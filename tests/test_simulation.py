import random
import pytest
from festival_ble_sim.config import AreaConfig, EnergyConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.simulation import draw_charge_fraction, run_simulation


def test_run_simulation_smoke():
    config = SimulationConfig(
        duration_s=300.0,
        num_festivaliers=15,
        random_seed=7,
        area=AreaConfig(width_m=60.0, height_m=60.0),
        traffic=TrafficConfig(
            messages_per_hour_range=(1800.0, 3600.0), payload_size_range_bytes=(20, 100), message_ttl_s=600.0
        ),
    )
    report = run_simulation(config)
    assert report.messages_created > 0
    assert report.messages_delivered > 0
    assert 0.0 <= report.delivery_ratio <= 1.0
    assert report.total_transmissions >= 0
    assert report.total_energy_consumed_mah >= 0.0


def test_idle_phones_drain_background_radio_current():
    config = SimulationConfig(
        duration_s=3600.0,
        num_festivaliers=2,
        traffic=TrafficConfig(messages_per_hour_range=(0.0, 0.0)),
        energy=EnergyConfig(background_current_ma=3.0, phone_current_ma=2.0),
    )
    report = run_simulation(config)
    assert report.total_transmissions == 0
    assert abs(report.avg_energy_consumed_mah - 5.0) < 0.01
    assert abs(report.avg_mesh_energy_consumed_mah - 3.0) < 0.01
    assert report.avg_algo_energy_consumed_mah == 0.0


def test_random_initial_charge_is_seeded_and_kills_only_low_phones():
    def run(charge_bins, seed=3):
        return run_simulation(SimulationConfig(
            duration_s=3600.0, cooldown_s=0.0, num_festivaliers=40, random_seed=seed,
            traffic=TrafficConfig(messages_per_hour_range=(0.0, 0.0)),
            # 100 mA for 1 h out of 150 mAh: a phone dies iff it starts below 2/3.
            energy=EnergyConfig(
                battery_capacity_mah=150.0, initial_charge_bins=charge_bins,
                background_current_ma=50.0, phone_current_ma=50.0,
            ),
        ))
    assert run(((1.0, 1.0, 1.0),)).dead_node_count == 0
    random_charge = run(((1.0, 0.5, 1.0),))
    replay = random.Random("3-charge")
    starts_mah = [150.0 * draw_charge_fraction(((1.0, 0.5, 1.0),), [1.0], replay) for _ in range(40)]
    assert all(abs(start - 100.0) > 0.1 for start in starts_mah)
    assert random_charge.dead_node_count == sum(start < 100.0 for start in starts_mah)
    assert 0 < random_charge.dead_node_count < 40
    assert run(((1.0, 0.5, 1.0),)).dead_node_count == random_charge.dead_node_count
    # A dead phone only spent the charge it arrived with, not the full capacity.
    assert random_charge.avg_energy_consumed_mah < 100.0


def test_cooldown_lets_late_messages_arrive_without_counting_new_ones():
    from festival_ble_sim.config import TrafficConfig
    base = dict(
        duration_s=300.0, num_festivaliers=20, random_seed=4,
        area=AreaConfig(width_m=100.0, height_m=100.0),
        traffic=TrafficConfig(messages_per_hour_range=(20.0, 40.0)),
    )
    cut = run_simulation(SimulationConfig(**base))
    drained = run_simulation(SimulationConfig(cooldown_s=600.0, **base))
    assert drained.messages_created == cut.messages_created
    assert drained.messages_delivered > cut.messages_delivered


def test_negative_cooldown_is_rejected():
    with pytest.raises(ValueError):
        SimulationConfig(cooldown_s=-1.0)


def test_festival_charge_bins_shares():
    from festival_ble_sim.presets import FESTIVAL_CHARGE_BINS
    rng = random.Random(0)
    weights = [share for share, _, _ in FESTIVAL_CHARGE_BINS]
    draws = [draw_charge_fraction(FESTIVAL_CHARGE_BINS, weights, rng) for _ in range(20000)]
    assert min(draws) >= 0.05 and max(draws) <= 1.0
    for (share, lo, hi) in FESTIVAL_CHARGE_BINS:
        observed = sum(lo <= d < hi or d == hi == 1.0 for d in draws) / len(draws)
        assert observed == pytest.approx(share, abs=0.015)
    assert draw_charge_fraction(((1.0, 1.0, 1.0),), [1.0], rng) == 1.0


def test_warmup_moves_people_but_measures_and_bills_nothing():
    from festival_ble_sim.config import TrafficConfig
    base = dict(
        duration_s=60.0, num_festivaliers=20, random_seed=4, area=AreaConfig(width_m=100.0, height_m=100.0),
        traffic=TrafficConfig(messages_per_hour_range=(20.0, 40.0)),
    )
    cold = run_simulation(SimulationConfig(**base))
    warm = run_simulation(SimulationConfig(warmup_s=600.0, **base))
    assert SimulationConfig(warmup_s=600.0, **base).total_s == 660.0
    # Same measured length: the warm-up adds no energy and no messages of its own.
    assert warm.avg_energy_consumed_mah == pytest.approx(cold.avg_energy_consumed_mah, rel=0.05)
    assert 0 < warm.messages_created < 3 * cold.messages_created + 10


def test_dead_phone_owner_keeps_walking_until_they_leave():
    import simpy
    from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility
    from festival_ble_sim.nodes import MobileNode
    from festival_ble_sim.simulation import _mobile_process
    from festival_ble_sim.spatial import SpatialGrid
    config = SimulationConfig(area=AreaConfig(width_m=100.0, height_m=100.0))
    node = MobileNode(1, RandomWaypointMobility(config.mobility, random.Random(1)), 10.0, 10, 100.0, config.area)
    node.consume_energy(1000.0)
    assert node.battery_depleted and not node.is_active
    grid = SpatialGrid(100.0, 100.0, cell_size_m=10.0)
    grid.insert(node)
    env = simpy.Environment()
    env.process(_mobile_process(env, node, config, grid))
    start = node.position
    env.run(until=60.0)
    assert node.position != start
    node.on_site = False
    gone = node.position
    env.run(until=120.0)
    assert node.position == gone
