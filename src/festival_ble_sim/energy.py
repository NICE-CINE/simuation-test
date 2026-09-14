from __future__ import annotations
from .config import EnergyConfig


class EnergyModel:
    def __init__(self, config: EnergyConfig) -> None:
        self._config = config

    def cost_of_tx(self, size_bytes: int) -> float:
        return self._config.tx_cost_mah_per_event + size_bytes * self._config.tx_cost_mah_per_byte

    def cost_of_rx(self, size_bytes: int) -> float:
        return self._config.rx_cost_mah_per_event + size_bytes * self._config.rx_cost_mah_per_byte
