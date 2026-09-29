import pytest
import simpy
from festival_ble_sim.config import (
    AreaConfig,
    ChurnConfig,
    SimulationConfig,
    TrafficConfig,
)
from festival_ble_sim.simulation import _churn_process, run_simulation
from festival_ble_sim.viz.history import SimulationHistory


class _FakeNode:
    def __init__(self):
        self.is_active = True


def test_churn_process_starts_inactive_until_arrival():
    env = simpy.Environment()
    node = _FakeNode()
    env.process(_churn_process(env, node, arrival_time_s=10.0, departure_time_s=1000.0))
    env.run(until=1.0)
    assert node.is_active is False
    env.run(until=11.0)
    assert node.is_active is True


def test_churn_process_deactivates_at_departure():
    env = simpy.Environment()
    node = _FakeNode()
    env.process(_churn_process(env, node, arrival_time_s=0.0, departure_time_s=20.0))
    env.run(until=10.0)
    assert node.is_active is True
    env.run(until=21.0)
    assert node.is_active is False


def test_churn_process_zero_arrival_never_deactivates_before_departure():
    env = simpy.Environment()
    node = _FakeNode()
    env.process(_churn_process(env, node, arrival_time_s=0.0, departure_time_s=50.0))
    for t in [1.0, 25.0, 49.0]:
        env.run(until=t)
        assert node.is_active is True


def _churn_config(**overrides):
    defaults = dict(
        duration_s=200.0,
        num_festivaliers=30,
        random_seed=11,
        area=AreaConfig(width_m=60.0, height_m=60.0),
        traffic=TrafficConfig(
            messages_per_hour_range=(1800.0, 3600.0), payload_size_range_bytes=(20, 100), message_ttl_s=600.0
        ),
        churn=ChurnConfig(
            enabled=True, arrival_window_s=(0.0, 100.0), session_duration_range_s=(20.0, 40.0)
        ),
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


def test_churn_disabled_keeps_every_node_active_all_run():
    config = SimulationConfig(
        duration_s=200.0, num_festivaliers=20, random_seed=3,
        area=AreaConfig(width_m=60.0, height_m=60.0), churn=ChurnConfig(enabled=False),
    )
    history = SimulationHistory(area_width_m=60.0, area_height_m=60.0, tick_interval_s=config.mobility.tick_interval_s)
    run_simulation(config, history=history)
    for _, positions in history.position_snapshots:
        assert len(positions) == config.num_festivaliers


def test_churn_enabled_population_present_varies_over_time():
    config = _churn_config()
    history = SimulationHistory(area_width_m=60.0, area_height_m=60.0, tick_interval_s=config.mobility.tick_interval_s)
    run_simulation(config, history=history)
    frame_sizes = [len(positions) for _, positions in history.position_snapshots]
    # With arrivals spread across the first 100s and short (20-40s) sessions
    # inside a 200s run, the active count should never reach all 30 at once
    # and should return toward empty by the end.
    assert min(frame_sizes) < max(frame_sizes)
    assert max(frame_sizes) < config.num_festivaliers
    assert frame_sizes[-1] < max(frame_sizes)


def test_churn_departures_are_not_counted_as_dead_from_battery():
    config = _churn_config()
    report = run_simulation(config)
    assert report.dead_node_count == 0


def test_rejects_invalid_arrival_window():
    with pytest.raises(ValueError):
        SimulationConfig(churn=ChurnConfig(arrival_window_s=(50.0, 10.0)))


def test_rejects_negative_arrival_window():
    with pytest.raises(ValueError):
        SimulationConfig(churn=ChurnConfig(arrival_window_s=(-5.0, 10.0)))


def test_rejects_invalid_session_duration_range():
    with pytest.raises(ValueError):
        SimulationConfig(churn=ChurnConfig(session_duration_range_s=(100.0, 10.0)))


def test_rejects_non_positive_session_duration():
    with pytest.raises(ValueError):
        SimulationConfig(churn=ChurnConfig(session_duration_range_s=(0.0, 10.0)))
