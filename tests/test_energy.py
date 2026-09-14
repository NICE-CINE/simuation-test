import pytest
from festival_ble_sim.config import EnergyConfig
from festival_ble_sim.energy import EnergyModel


def test_cost_of_tx():
    config = EnergyConfig(tx_cost_mah_per_event=0.02, tx_cost_mah_per_byte=0.0001)
    model = EnergyModel(config)
    assert model.cost_of_tx(100) == pytest.approx(0.02 + 100 * 0.0001)


def test_cost_of_rx():
    config = EnergyConfig(rx_cost_mah_per_event=0.01, rx_cost_mah_per_byte=0.00005)
    model = EnergyModel(config)
    assert model.cost_of_rx(200) == pytest.approx(0.01 + 200 * 0.00005)
