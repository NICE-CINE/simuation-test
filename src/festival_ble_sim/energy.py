from __future__ import annotations
from .config import EnergyConfig


class EnergyModel:
    def __init__(self, config: EnergyConfig) -> None:
        self._config = config

    def cost_of_tx(self, size_bytes: int) -> float:
        return self._config.tx_cost_mah_per_event + size_bytes * self._config.tx_cost_mah_per_byte

    def cost_of_rx(self, size_bytes: int) -> float:
        return self._config.rx_cost_mah_per_event + size_bytes * self._config.rx_cost_mah_per_byte

    def connection_setup_cost(self) -> float:
        return self._config.connection_setup_mah

    def connection_holding_cost(self, connections: int, dt_s: float) -> float:
        return max(0, connections - 1) * self._config.extra_connection_current_ma * dt_s / 3600.0
