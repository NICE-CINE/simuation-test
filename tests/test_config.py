import pytest
from festival_ble_sim.config import SimulationConfig, AreaConfig, TrafficConfig


def test_default_config_is_valid():
    config = SimulationConfig()
    assert config.num_festivaliers > 0
    assert config.area.width_m == 500.0


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
