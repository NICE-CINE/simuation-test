from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AreaConfig:
    # Mid-size festival site (~0.35 km^2: two stages, bars/food court,
    # entrance), not a free-roaming square kilometer.
    width_m: float = 700.0
    height_m: float = 500.0


@dataclass(frozen=True)
class RadioParams:
    # Log-distance path-loss model (same shape as the classic BLE/Wi-Fi
    # indoor propagation model): received power decays by
    # `10 * path_loss_exponent` dB per decade of distance beyond
    # `reference_distance_m`, where it's calibrated to `reference_loss_db`.
    tx_power_dbm: float
    path_loss_exponent: float
    reference_distance_m: float
    reference_loss_db: float
    receiver_sensitivity_dbm: float
    # Log-normal shadow fading: standard deviation (dB) of a zero-mean
    # Gaussian added on top of the deterministic path loss, representing
    # bodies/obstacles randomly blocking the link — without it, received
    # power is a pure function of distance and "in range" collapses to a
    # fixed circle. 0.0 = no shadowing (deterministic, prior behavior).
    shadowing_std_db: float = 0.0


# Defaults: -90 dBm sensitivity and exponent=2.7 (crowded/obstructed
# festival ground, denser than free space's 2.0) are typical BLE figures;
# tx_power is picked per node type below so the resulting max range lines
# up with this simulator's previous fixed-radius defaults (~30m / ~60m).
# shadowing_std_db=4.0 is a middle-of-the-road figure for short-range
# obstructed/crowd shadowing reported in BLE/indoor propagation literature.
def _default_phone_radio() -> RadioParams:
    return RadioParams(
        tx_power_dbm=-10.0,
        path_loss_exponent=2.7,
        reference_distance_m=1.0,
        reference_loss_db=40.0,
        receiver_sensitivity_dbm=-90.0,
        shadowing_std_db=4.0,
    )


def _default_beacon_radio() -> RadioParams:
    return RadioParams(
        tx_power_dbm=-2.0,
        path_loss_exponent=2.7,
        reference_distance_m=1.0,
        reference_loss_db=40.0,
        receiver_sensitivity_dbm=-90.0,
        shadowing_std_db=4.0,
    )


@dataclass(frozen=True)
class BleConfig:
    phone_radio: RadioParams = field(default_factory=_default_phone_radio)
    beacon_radio: RadioParams = field(default_factory=_default_beacon_radio)
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
    # Extra loss probability for links near the edge of radio range: fades
    # linearly from 0 at signal_margin_cutoff_db (or above) to
    # weak_signal_max_probability at a 0 dB margin (received power at the
    # receiver sensitivity floor), on top of the congestion-based loss above.
    signal_margin_cutoff_db: float = 6.0
    weak_signal_max_probability: float = 0.30
    packet_loss_max_probability: float = 0.30
    # CSMA-style channel sensing: before transmitting, a node estimates
    # how many other nodes within its own radio range also have something
    # to send this tick, and backs off (skips this tick, retries next one,
    # no energy spent, no loss counted) with a probability that grows with
    # that count — this is what keeps a real BLE mesh from having every
    # node blast a relay at once.
    relay_backoff_coefficient: float = 0.05
    relay_backoff_max_probability: float = 0.5
    # Even after backoff, a receiver can still be hit by two senders that
    # can't hear each other (hidden-terminal collision): extra loss
    # probability per other transmitter within the RECEIVER's own range,
    # on top of (not instead of) congestion/weak-signal loss.
    collision_loss_coefficient: float = 0.03
    collision_loss_max_probability: float = 0.4


@dataclass(frozen=True)
class PointOfInterest:
    x: float
    y: float
    radius_m: float
    weight: float = 1.0


@dataclass(frozen=True)
class MobilityConfig:
    # Walking through a crowd is slower than free walking (~1.4 m/s), and
    # festivaliers spend most of their time standing still: a pause is a
    # concert set, a queue at the bar or a break (5 to 45 min).
    speed_min_mps: float = 0.3
    speed_max_mps: float = 1.2
    pause_probability: float = 0.7
    pause_duration_range_s: Tuple[float, float] = (300.0, 2700.0)
    tick_interval_s: float = 1.0
    # Only consumed by mobility.poi.PoiMobility (opt-in via mobility_factory);
    # RandomWaypointMobility ignores this field entirely.
    points_of_interest: Tuple[PointOfInterest, ...] = ()


@dataclass(frozen=True)
class TrafficConfig:
    # Each festivalier is assigned their own fixed rate, drawn uniformly
    # from this range once at simulation start: total network traffic
    # emerges from num_festivaliers x (each person's own rate) rather than
    # a single network-wide average, so it scales realistically with
    # population size without needing to be tuned per run.
    # Mean 2 msg/h: most people text a few times per hour ("t'es ou ?"),
    # some never do.
    messages_per_hour_range: Tuple[float, float] = (0.0, 4.0)
    payload_size_range_bytes: Tuple[int, int] = (20, 512)
    message_ttl_s: float = 1800.0
    # Bluetooth Mesh network-layer TTL, in hops rather than seconds: caps
    # how many times a message can be relayed regardless of how long it's
    # been alive, bounding flood radius the way real mesh deployments do
    # (typical default TTL values are single digits). None = unlimited.
    message_ttl_hops: Optional[int] = 8
    # People text their friends, not strangers: destinations are drawn from
    # the sender's SocialConfig group, and friendless people send nothing.
    # False restores a uniformly random destination among active nodes.
    friends_only: bool = True
    # Conversations: probability that a delivered message gets a reply from
    # its destination, after a delay drawn from reply_delay_range_s. Replies
    # can themselves be replied to. 0.0 = no replies (previous behavior).
    reply_probability: float = 0.0
    reply_delay_range_s: Tuple[float, float] = (20.0, 180.0)
    # Bursts: after each spontaneous message, the sender writes again to the
    # same destination with this probability (geometric chain), after a
    # delay drawn from followup_delay_range_s. 0.0 = off (previous behavior).
    followup_probability: float = 0.0
    followup_delay_range_s: Tuple[float, float] = (10.0, 120.0)


@dataclass(frozen=True)
class SocialConfig:
    # Friend groups (the QR-code graph) shared by traffic and bubble_f.
    group_size_range: Tuple[int, int] = (2, 8)
    no_friend_fraction: float = 0.2


@dataclass(frozen=True)
class GpsConfig:
    # Phone GPS error, resampled on every read. Typical outdoor smartphone
    # accuracy; 0.0 gives exact positions. Beacons always read exact.
    noise_std_m: float = 5.0
    # Probability that a fix attempt yields nothing (indoors, cold start,
    # crowd). Drawn only when > 0, so runs without it are unchanged.
    fix_failure_probability: float = 0.0


@dataclass(frozen=True)
class EnergyConfig:
    # ~4500 mAh phone arriving about two thirds charged.
    initial_battery_mah: float = 3000.0
    tx_cost_mah_per_event: float = 0.02
    tx_cost_mah_per_byte: float = 1e-4
    rx_cost_mah_per_event: float = 0.01
    rx_cost_mah_per_byte: float = 5e-5
    # Average current of BLE scanning + advertising, paid every second a
    # phone is active whether or not it sends anything. Starting guess, to
    # recalibrate on real devices.
    background_current_ma: float = 2.0


@dataclass(frozen=True)
class BeaconConfig:
    count: int = 0
    placement: str = "grid"
    manual_positions: Optional[List[Tuple[float, float]]] = None
    unlimited_power: bool = True
    # The WiFi/wired backhaul between beacons is a separate backbone, not a
    # BLE link, but it isn't literally instant or lossless either. Each tick
    # a message is still pending backhaul delivery, it's attempted with
    # probability contact_check_interval_s/backhaul_latency_s (so latencies
    # well below one tick round up to "always attempt", preserving the
    # previous quasi-instant behavior by default) and, if attempted, still
    # subject to backhaul_loss_probability before the source retries next tick.
    backhaul_latency_s: float = 0.05
    backhaul_loss_probability: float = 0.0


@dataclass(frozen=True)
class ChurnConfig:
    # Off by default: every mobile node is active for the full run, as
    # before. When enabled, each mobile node samples an arrival time
    # uniformly from arrival_window_s and a session length uniformly from
    # session_duration_range_s, and is only is_active (participates in BLE,
    # eligible as traffic src/dst) between arrival and arrival+session —
    # modeling a crowd that trickles in/out over the event rather than
    # being fully present for the whole simulated duration.
    enabled: bool = False
    # Arrivals spread over the first 30 min of the run, stays of 30 min
    # to 3 h (a couple of sets up to the whole evening).
    arrival_window_s: Tuple[float, float] = (0.0, 1800.0)
    session_duration_range_s: Tuple[float, float] = (1800.0, 10800.0)


@dataclass
class SimulationConfig:
    duration_s: float = 3600.0
    num_festivaliers: int = 4000
    node_buffer_capacity: int = 100
    random_seed: Optional[int] = 42
    area: AreaConfig = field(default_factory=AreaConfig)
    ble: BleConfig = field(default_factory=BleConfig)
    mobility: MobilityConfig = field(default_factory=MobilityConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    beacons: BeaconConfig = field(default_factory=BeaconConfig)
    churn: ChurnConfig = field(default_factory=ChurnConfig)
    social: SocialConfig = field(default_factory=SocialConfig)
    gps: GpsConfig = field(default_factory=GpsConfig)

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
        rate_lo, rate_hi = self.traffic.messages_per_hour_range
        if rate_lo < 0 or rate_hi < rate_lo:
            raise ValueError("messages_per_hour_range must satisfy 0 <= lo <= hi")
        if self.traffic.message_ttl_hops is not None and self.traffic.message_ttl_hops < 1:
            raise ValueError("message_ttl_hops must be None or >= 1")
        if not 0.0 <= self.traffic.reply_probability < 1.0:
            raise ValueError("reply_probability must be in [0, 1)")
        if not 0.0 <= self.traffic.followup_probability < 1.0:
            raise ValueError("followup_probability must be in [0, 1)")
        followup_lo, followup_hi = self.traffic.followup_delay_range_s
        if followup_lo < 0 or followup_hi < followup_lo:
            raise ValueError("followup_delay_range_s must satisfy 0 <= lo <= hi")
        if self.energy.background_current_ma < 0:
            raise ValueError("background_current_ma must be >= 0")
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
        if self.ble.signal_margin_cutoff_db <= 0:
            raise ValueError("signal_margin_cutoff_db must be positive")
        if not (0.0 <= self.ble.weak_signal_max_probability <= 1.0):
            raise ValueError("weak_signal_max_probability must be within [0, 1]")
        if self.ble.relay_backoff_coefficient < 0:
            raise ValueError("relay_backoff_coefficient must be >= 0")
        if not (0.0 <= self.ble.relay_backoff_max_probability <= 1.0):
            raise ValueError("relay_backoff_max_probability must be within [0, 1]")
        if self.ble.collision_loss_coefficient < 0:
            raise ValueError("collision_loss_coefficient must be >= 0")
        if not (0.0 <= self.ble.collision_loss_max_probability <= 1.0):
            raise ValueError("collision_loss_max_probability must be within [0, 1]")
        if self.beacons.backhaul_latency_s <= 0:
            raise ValueError("backhaul_latency_s must be positive")
        if not (0.0 <= self.beacons.backhaul_loss_probability <= 1.0):
            raise ValueError("backhaul_loss_probability must be within [0, 1]")
        arrival_lo, arrival_hi = self.churn.arrival_window_s
        if arrival_lo < 0 or arrival_hi < arrival_lo:
            raise ValueError("arrival_window_s must satisfy 0 <= lo <= hi")
        session_lo, session_hi = self.churn.session_duration_range_s
        if session_lo <= 0 or session_hi < session_lo:
            raise ValueError("session_duration_range_s must satisfy 0 < lo <= hi")
        group_lo, group_hi = self.social.group_size_range
        if not 2 <= group_lo <= group_hi:
            raise ValueError("group_size_range must satisfy 2 <= lo <= hi")
        if not (0.0 <= self.social.no_friend_fraction <= 1.0):
            raise ValueError("no_friend_fraction must be within [0, 1]")
        if self.gps.noise_std_m < 0:
            raise ValueError("gps noise_std_m must be >= 0")
        if not 0.0 <= self.gps.fix_failure_probability < 1.0:
            raise ValueError("gps fix_failure_probability must be in [0, 1)")
        for radio in (self.ble.phone_radio, self.ble.beacon_radio):
            if radio.path_loss_exponent <= 0:
                raise ValueError("path_loss_exponent must be positive")
            if radio.reference_distance_m <= 0:
                raise ValueError("reference_distance_m must be positive")
            if radio.shadowing_std_db < 0:
                raise ValueError("shadowing_std_db must be >= 0")
