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


def test_default_costs_imply_a_plausible_ble_radio_current():
    from festival_ble_sim.config import BleConfig
    energy, ble = EnergyConfig(), BleConfig()
    for per_byte in (energy.tx_cost_mah_per_byte, energy.rx_cost_mah_per_byte):
        current_ma = per_byte * ble.transfer_rate_bytes_per_s * 3600.0
        assert 1.0 <= current_ma <= 30.0
