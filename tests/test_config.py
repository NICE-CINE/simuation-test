import pytest
from festival_ble_sim.config import BeaconConfig, BleConfig, RadioParams, SimulationConfig, AreaConfig, TrafficConfig


def test_default_message_ttl_hops_is_eight():
    assert TrafficConfig().message_ttl_hops == 8


def test_rejects_non_positive_message_ttl_hops():
    with pytest.raises(ValueError):
        SimulationConfig(traffic=TrafficConfig(message_ttl_hops=0))


def test_accepts_none_message_ttl_hops_as_unlimited():
    config = SimulationConfig(traffic=TrafficConfig(message_ttl_hops=None))
    assert config.traffic.message_ttl_hops is None


def test_rejects_non_positive_backhaul_latency():
    with pytest.raises(ValueError):
        SimulationConfig(beacons=BeaconConfig(backhaul_latency_s=0.0))


def test_rejects_backhaul_loss_probability_outside_unit_range():
    with pytest.raises(ValueError):
        SimulationConfig(beacons=BeaconConfig(backhaul_loss_probability=1.5))


def test_default_config_is_valid():
    config = SimulationConfig()
    assert config.num_festivaliers > 0
    assert config.area.width_m == 700.0


def test_rejects_non_positive_area():
    with pytest.raises(ValueError):
        SimulationConfig(area=AreaConfig(width_m=0.0, height_m=100.0))


def test_rejects_too_few_festivaliers():
    with pytest.raises(ValueError):
        SimulationConfig(num_festivaliers=1)


def test_rejects_invalid_payload_range():
    with pytest.raises(ValueError):
        SimulationConfig(traffic=TrafficConfig(payload_size_range_bytes=(100, 10)))


def test_rejects_non_positive_buffer_capacity():
    with pytest.raises(ValueError):
        SimulationConfig(node_buffer_capacity=0)


def _radio(**overrides) -> RadioParams:
    defaults = dict(
        tx_power_dbm=0.0, path_loss_exponent=2.7, reference_distance_m=1.0,
        reference_loss_db=40.0, receiver_sensitivity_dbm=-90.0,
    )
    defaults.update(overrides)
    return RadioParams(**defaults)


def test_rejects_non_positive_path_loss_exponent():
    with pytest.raises(ValueError):
        SimulationConfig(ble=BleConfig(phone_radio=_radio(path_loss_exponent=0.0)))


def test_rejects_non_positive_reference_distance():
    with pytest.raises(ValueError):
        SimulationConfig(ble=BleConfig(beacon_radio=_radio(reference_distance_m=0.0)))


def test_rejects_non_positive_signal_margin_cutoff():
    with pytest.raises(ValueError):
        SimulationConfig(ble=BleConfig(signal_margin_cutoff_db=0.0))


def test_rejects_weak_signal_probability_outside_unit_range():
    with pytest.raises(ValueError):
        SimulationConfig(ble=BleConfig(weak_signal_max_probability=1.5))
