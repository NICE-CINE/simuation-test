from festival_ble_sim.config import SimulationConfig, TrafficConfig
from festival_ble_sim.simulation import run_simulation


def test_run_simulation_smoke():
    config = SimulationConfig(
        duration_s=120.0,
        num_festivaliers=10,
        random_seed=7,
        traffic=TrafficConfig(mean_interval_s=2.0, payload_size_range_bytes=(20, 100), message_ttl_s=600.0),
    )
    report = run_simulation(config)
    assert report.messages_created > 0
    assert 0.0 <= report.delivery_ratio <= 1.0
    assert report.total_transmissions >= 0
    assert report.total_energy_consumed_mah >= 0.0
