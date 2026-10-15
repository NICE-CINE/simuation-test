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
    # Bytes each radio can send + receive per tick, shared by all its links
    # (network_engine tracks it per node for the whole tick): the ~37 kB/s
    # Nearby measured over Bluetooth Classic between two phones alone
    # (docs/energie/consommation.md). A crowd lowers it through the
    # channel load below, not through this figure.
    transfer_rate_bytes_per_s: float = 37_000.0
    contact_check_interval_s: float = 1.0
    # Simultaneous GATT-central connections a phone can realistically hold
    # per tick (iPhone/Android chipsets typically sustain ~4-8). None = no cap.
    max_concurrent_links: Optional[int] = 6
    # A pair must stay in range this long before its connection carries
    # anything: Nearby measured ~7 s from discovery to connection
    # (docs/energie/consommation.md). 0 = usable on the first tick.
    connection_setup_s: float = 7.0
    # An established connection with no data either way for this long is
    # closed, freeing both slots (estimated, not measured).
    connection_idle_timeout_s: float = 30.0
    # Residual per-packet error on any link.
    packet_loss_base_probability: float = 0.01
    # Extra per-packet error for links near the edge of radio range: fades
    # linearly from 0 at signal_margin_cutoff_db (or above) to
    # weak_signal_max_probability at a 0 dB margin (received power at the
    # receiver sensitivity floor).
    signal_margin_cutoff_db: float = 6.0
    weak_signal_max_probability: float = 0.30
    # Collisions: a neighbor transmitting a share u of its airtime lands on a
    # packet's channel with probability ~u / channels. Data goes over
    # connections on Bluetooth Classic's 79 hopping channels, connectionless
    # control broadcasts over BLE's 3 advertising channels. On a connection
    # a lost packet is resent (airtime and energy), a broadcast is just lost.
    data_channels: int = 79
    advertising_channels: int = 3
    # One message id in a summary vector (what a node holds, sent over each
    # connection so the peer doesn't resend it).
    summary_id_bytes: int = 4


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
    # Also PoiMobility-only. None keeps the original behaviour (uniform start,
    # POI-only targets); a probability makes initial positions and each new
    # target uniform over the whole area with that probability, POI otherwise.
    background_probability: Optional[float] = None


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
    # Sources and derivations: docs/energie/consommation.md (Nice Mesh radio
    # bench, 12 Oct 2026: Nearby Connections P2P_CLUSTER on an Honor 8X and
    # a Galaxy A56).
    battery_capacity_mah: float = 4500.0
    # (share of phones, lo, hi): each phone picks a bin by share, then starts
    # at uniform(lo, hi) x capacity, from a "<seed>-charge" RNG. The default
    # single fixed bin = everyone exactly full.
    initial_charge_bins: Tuple[Tuple[float, float, float], ...] = ((1.0, 1.0, 1.0),)
    # Measured incremental cost over "Nearby active": TX 0.25-0.6 uJ/bit,
    # RX 0.07-0.16 uJ/bit (mid-range values). Per event: ~5 ms of airtime at
    # the measured +21 mA (TX) / +12 mA (RX) — the per-event term itself
    # was not measured.
    tx_cost_mah_per_event: float = 2.9e-5
    tx_cost_mah_per_byte: float = 2.4e-7
    rx_cost_mah_per_event: float = 1.7e-5
    rx_cost_mah_per_byte: float = 6.3e-8
    # Being reachable: "Nearby active, connected, no traffic" measured at
    # +29 to +34 mA over the phone's own idle.
    background_current_ma: float = 31.0
    # The phone's own draw, mesh off: 38 mA measured screen-off idle (mean
    # of 27 and 49) + screen on 20 % of the time at +218 mA (screen-on
    # overhead measured 13 Oct over screen off, mean of both phones and three
    # app screens; the 20 % share is an estimate). 0 = count only the mesh.
    phone_current_ma: float = 82.0
    # Opening a connection: ~7 s of discovery (BleConfig.connection_setup_s)
    # at the measured "BLE advertising + scan" overhead (+18 / +11 mA, mean
    # 14.5), on both phones.
    connection_setup_mah: float = 7.0 * 14.5 / 3600.0
    # Each connection held beyond the first, per phone (background_current_ma
    # was measured with one): estimated, not measured.
    extra_connection_current_ma: float = 3.0


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
    # Measured window: only messages created during [0, duration_s) count in
    # the report. The run then goes on for cooldown_s more seconds (traffic
    # included, so the load stays steady) to let those messages arrive.
    # message_ttl_s is the exact bound; 0 keeps the old cut-off at duration_s.
    duration_s: float = 3600.0
    cooldown_s: float = 0.0
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
        if self.cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")
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
        if self.energy.background_current_ma < 0 or self.energy.phone_current_ma < 0:
            raise ValueError("background_current_ma and phone_current_ma must be >= 0")
        if self.energy.connection_setup_mah < 0 or self.energy.extra_connection_current_ma < 0:
            raise ValueError("connection_setup_mah and extra_connection_current_ma must be >= 0")
        if self.energy.battery_capacity_mah <= 0:
            raise ValueError("battery_capacity_mah must be positive")
        if not self.energy.initial_charge_bins:
            raise ValueError("initial_charge_bins must not be empty")
        for share, charge_lo, charge_hi in self.energy.initial_charge_bins:
            if share <= 0 or not 0.0 < charge_lo <= charge_hi <= 1.0:
                raise ValueError("initial_charge_bins entries must satisfy share > 0 and 0 < lo <= hi <= 1")
        if self.ble.transfer_rate_bytes_per_s <= 0:
            raise ValueError("transfer_rate_bytes_per_s must be positive")
        if self.ble.max_concurrent_links is not None and self.ble.max_concurrent_links < 1:
            raise ValueError("max_concurrent_links must be None or >= 1")
        if self.ble.connection_setup_s < 0 or self.ble.connection_idle_timeout_s <= 0:
            raise ValueError("connection_setup_s must be >= 0 and connection_idle_timeout_s > 0")
        if not 0.0 <= self.ble.packet_loss_base_probability <= 1.0:
            raise ValueError("packet_loss_base_probability must be within [0, 1]")
        if self.ble.signal_margin_cutoff_db <= 0:
            raise ValueError("signal_margin_cutoff_db must be positive")
        if not (0.0 <= self.ble.weak_signal_max_probability <= 1.0):
            raise ValueError("weak_signal_max_probability must be within [0, 1]")
        if self.ble.data_channels < 1 or self.ble.advertising_channels < 1:
            raise ValueError("data_channels and advertising_channels must be >= 1")
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
