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


def test_default_per_byte_costs_match_the_measured_bench_ranges():
    # docs/energie/consommation.md: TX 0.25-0.6 uJ/bit, RX 0.07-0.16 uJ/bit, phones at ~3.84-4.04 V.
    energy = EnergyConfig()
    for per_byte, (lo, hi) in ((energy.tx_cost_mah_per_byte, (0.25, 0.6)), (energy.rx_cost_mah_per_byte, (0.07, 0.16))):
        uj_per_bit = per_byte * 3.6 * 3.94 * 1e6 / 8
        assert lo <= uj_per_bit <= hi
