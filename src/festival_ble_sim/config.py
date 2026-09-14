from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AreaConfig:
    width_m: float = 500.0
    height_m: float = 500.0


@dataclass(frozen=True)
class BleConfig:
    phone_range_m: float = 30.0
    beacon_range_m: float = 60.0
    # Declared per spec but not yet consumed: BLE transfers are currently
    # modeled as instantaneous regardless of payload size or this rate.
    transfer_rate_bytes_per_s: float = 10_000.0
    contact_check_interval_s: float = 1.0


@dataclass(frozen=True)
class MobilityConfig:
    speed_min_mps: float = 0.5
    speed_max_mps: float = 1.4
    pause_probability: float = 0.3
    pause_duration_range_s: Tuple[float, float] = (10.0, 60.0)
    tick_interval_s: float = 1.0


@dataclass(frozen=True)
class TrafficConfig:
    mean_interval_s: float = 5.0
    payload_size_range_bytes: Tuple[int, int] = (20, 512)
    message_ttl_s: float = 1800.0


@dataclass(frozen=True)
class EnergyConfig:
    initial_battery_mah: float = 2000.0
    tx_cost_mah_per_event: float = 0.02
    tx_cost_mah_per_byte: float = 1e-4
    rx_cost_mah_per_event: float = 0.01
    rx_cost_mah_per_byte: float = 5e-5


@dataclass(frozen=True)
class BeaconConfig:
    count: int = 0
    placement: str = "grid"
    manual_positions: Optional[List[Tuple[float, float]]] = None
    unlimited_power: bool = True


@dataclass
class SimulationConfig:
    duration_s: float = 3600.0
    num_festivaliers: int = 200
    node_buffer_capacity: int = 100
    random_seed: Optional[int] = 42
    area: AreaConfig = field(default_factory=AreaConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    mobility: MobilityConfig = field(default_factory=MobilityConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    beacons: BeaconConfig = field(default_factory=BeaconConfig)

    def __post_init__(self) -> None:
        if self.area.width_m <= 0 or self.area.height_m <= 0:
            raise ValueError("area dimensions must be positive")
        if self.num_festivaliers < 2:
            raise ValueError("num_festivaliers must be at least 2 (need src and dst)")
        if self.node_buffer_capacity <= 0:
            raise ValueError("node_buffer_capacity must be positive")
        lo, hi = self.traffic.payload_size_range_bytes
        if lo <= 0 or hi < lo:
            raise ValueError("payload_size_range_bytes must satisfy 0 < lo <= hi")
