from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AreaConfig:
    width_m: float = 1500.0
    height_m: float = 1500.0


@dataclass(frozen=True)
class BleConfig:
    phone_range_m: float = 30.0
    beacon_range_m: float = 60.0
    # Bytes exchangeable per tick per link (sender<->contact): real effective
    # GATT throughput in a dense opportunistic-mesh deployment, well below
    # BLE's raw PHY rate once ATT/connection overhead and 2.4GHz contention
    # from thousands of nearby devices are accounted for.
    transfer_rate_bytes_per_s: float = 10_000.0
    contact_check_interval_s: float = 1.0
    # Simultaneous GATT-central connections a phone can realistically hold
    # per tick (iPhone/Android chipsets typically sustain ~4-8). None = no cap.
    max_concurrent_links: Optional[int] = 6
    packet_loss_base_probability: float = 0.01
    packet_loss_congestion_coefficient: float = 0.02
    packet_loss_max_probability: float = 0.30


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
    num_festivaliers: int = 10000
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
        if self.ble.transfer_rate_bytes_per_s <= 0:
            raise ValueError("transfer_rate_bytes_per_s must be positive")
        if self.ble.max_concurrent_links is not None and self.ble.max_concurrent_links < 1:
            raise ValueError("max_concurrent_links must be None or >= 1")
        for prob in (
            self.ble.packet_loss_base_probability,
            self.ble.packet_loss_congestion_coefficient,
            self.ble.packet_loss_max_probability,
        ):
            if prob < 0:
                raise ValueError("packet loss probabilities/coefficients must be >= 0")
        if self.ble.packet_loss_base_probability > 1 or self.ble.packet_loss_max_probability > 1:
            raise ValueError("packet loss probabilities must be <= 1")
        if self.ble.packet_loss_base_probability > self.ble.packet_loss_max_probability:
            raise ValueError("packet_loss_base_probability must be <= packet_loss_max_probability")
