from festival_ble_sim.config import AreaConfig, EnergyConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.simulation import run_simulation


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
        energy=EnergyConfig(background_current_ma=3.0),
    )
    report = run_simulation(config)
    assert report.total_transmissions == 0
    assert abs(report.avg_energy_consumed_mah - 3.0) < 0.01
