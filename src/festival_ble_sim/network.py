from __future__ import annotations
import math
import random
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from .config import BeaconConfig, BleConfig
from .energy import EnergyModel
from .metrics import MetricsCollector
from .models import Message
from .nodes import BaseNode, BeaconNode
from .radio import link_margin_db
from .routing.base import RoutingAlgorithm, RoutingDecision
from .spatial import SpatialGrid


def _purge_expired_messages(node: BaseNode, now: float) -> None:
    expired_ids = [mid for mid, m in node.buffer.items() if m.is_expired(now)]
    for mid in expired_ids:
        del node.buffer[mid]
    for table in (node.acked, node.outbox):
        for mid in [mid for mid, expiry in table.items() if expiry < now]:
            del table[mid]


class _Connection:
    __slots__ = ("ready_at", "last_used", "advertised", "acks_sent", "tables_sent")

    def __init__(self, ready_at: float) -> None:
        self.ready_at = ready_at
        self.last_used = ready_at
        # Per side: message ids already listed in its summary vector, and
        # acks already sent, so each tick only sends what's new.
        self.advertised: Dict[int, Set[int]] = {}
        self.acks_sent: Dict[int, Set[int]] = {}
        self.tables_sent = False


def _compute_neighbors(nodes: Dict[int, BaseNode], grid: SpatialGrid) -> Dict[int, List[BaseNode]]:
    # One grid query per active node per tick, shared by on_tick, the channel
    # load (ChannelState.next_tick) and the connections — computing this twice
    # per node per tick (as an earlier version of this file did) roughly
    # doubled SpatialGrid query cost network-wide.
    neighbors: Dict[int, List[BaseNode]] = {}
    for node_id, node in nodes.items():
        if not node.is_active:
            continue
        neighbors[node_id] = _active_nearby(node, grid)
    return neighbors


def _active_nearby(node: BaseNode, grid: SpatialGrid) -> List[BaseNode]:
    # The grid still holds dead, departed and not-yet-arrived nodes: without
    # this filter they would take link slots, inflate the channel load and show
    # up as encounters in every algorithm's on_tick. Range is mutual: every
    # BLE packet is acknowledged by the other side, so a beacon can't reach a
    # phone that can't answer it.
    return [
        n for n in grid.get_nearby(node, node.radio_range_m)
        if n.is_active and node.position.distance_squared_to(n.position) <= n.radio_range_m * n.radio_range_m
    ]


def _link_radio(ble_config: BleConfig, a: BaseNode, b: BaseNode):
    # A link is only as good as its weaker direction.
    weaker = a if a.radio_range_m <= b.radio_range_m else b
    return ble_config.beacon_radio if weaker.is_beacon else ble_config.phone_radio


def _update_connections(
    now: float,
    order: List[Any],
    neighbors_by_node: Dict[int, List[BaseNode]],
    snapshot: Dict[int, List[Message]],
    routing_algorithm: RoutingAlgorithm,
    ble_config: BleConfig,
    connections: Dict[Tuple[int, int], _Connection],
) -> Dict[int, List[BaseNode]]:
    # connections: (low id, high id) -> _Connection, kept across
    # ticks. A pair must stay in range connection_setup_s before it can carry
    # anything (discovery + connection), keeps its slot on both ends while
    # in range, and is closed after connection_idle_timeout_s without data.
    # Only nodes with something to send open new ones, via select_links.
    # Returns each node's usable (ready) links.
    nodes_by_id = dict(order)
    for key in list(connections):
        a, b = nodes_by_id[key[0]], nodes_by_id[key[1]]
        conn = connections[key]
        reach = min(a.radio_range_m, b.radio_range_m)
        if (
            not a.is_active or not b.is_active
            or a.position.distance_squared_to(b.position) > reach * reach
            or (conn.ready_at <= now and now - conn.last_used >= ble_config.connection_idle_timeout_s)
        ):
            del connections[key]
    partners: Dict[int, List[int]] = {}
    for a_id, b_id in connections:
        partners.setdefault(a_id, []).append(b_id)
        partners.setdefault(b_id, []).append(a_id)
    max_links = ble_config.max_concurrent_links
    for node_id, node in order:
        if not snapshot.get(node_id) or node_id not in neighbors_by_node:
            continue
        taken = partners.setdefault(node_id, [])
        free = len(neighbors_by_node[node_id]) if max_links is None else max_links - len(taken)
        if free <= 0:
            continue
        candidates = [
            n for n in neighbors_by_node[node_id]
            if n.id not in taken and (max_links is None or len(partners.get(n.id, ())) < max_links)
        ]
        for contact in routing_algorithm.select_links(node, candidates, free)[:free]:
            connections[(min(node_id, contact.id), max(node_id, contact.id))] = _Connection(
                now + ble_config.connection_setup_s
            )
            taken.append(contact.id)
            partners.setdefault(contact.id, []).append(node_id)
    links: Dict[int, List[BaseNode]] = {}
    for (a_id, b_id), conn in connections.items():
        if conn.ready_at <= now:
            links.setdefault(a_id, []).append(nodes_by_id[b_id])
            links.setdefault(b_id, []).append(nodes_by_id[a_id])
    return links


@dataclass
class ChannelState:
    # duty_*: the share of its airtime budget each node transmitted last
    # tick; heard_*: the summed duty of each node's neighbors, the load it
    # hears. One tick of lag keeps it causal, and only what was actually put
    # on the air counts, not what sits in a buffer. sent_*: bytes each node
    # transmits this tick, next tick's duty. Data (connections) and control
    # (connectionless broadcasts) live on different channels.
    duty_data: Dict[int, float] = field(default_factory=dict)
    duty_control: Dict[int, float] = field(default_factory=dict)
    heard_data: Dict[int, float] = field(default_factory=dict)
    heard_control: Dict[int, float] = field(default_factory=dict)
    sent_data: Dict[int, float] = field(default_factory=dict)
    sent_control: Dict[int, float] = field(default_factory=dict)

    def next_tick(self, neighbors_by_node: Dict[int, List[BaseNode]], budget: float) -> "ChannelState":
        duty_data = {k: v / budget for k, v in self.sent_data.items()}
        duty_control = {k: v / budget for k, v in self.sent_control.items()}
        return ChannelState(
            duty_data, duty_control, _heard(duty_data, neighbors_by_node), _heard(duty_control, neighbors_by_node)
        )


def _heard(duty: Dict[int, float], neighbors_by_node: Dict[int, List[BaseNode]]) -> Dict[int, float]:
    # Neighbor lists are mutual, so a transmitter's neighbors are exactly
    # the nodes that hear it: summing from the (few) transmitters' side.
    heard: Dict[int, float] = {}
    for node_id, d in duty.items():
        for n in neighbors_by_node.get(node_id, ()):
            heard[n.id] = heard.get(n.id, 0.0) + d
    return heard


def _weak_signal_loss_probability(margin_db: float, ble_config: BleConfig) -> float:
    # Fades from 0 loss at/above the cutoff margin to weak_signal_max_probability
    # right at the receiver sensitivity floor (0 dB margin): a link near the
    # edge of range drops more packets than one deep inside it, on top of
    # (not instead of) congestion-driven loss.
    cutoff = ble_config.signal_margin_cutoff_db
    if margin_db >= cutoff:
        return 0.0
    if margin_db <= 0.0:
        return ble_config.weak_signal_max_probability
    return ble_config.weak_signal_max_probability * (1.0 - margin_db / cutoff)


def _link_failure_probability(
    sender: BaseNode,
    contact: BaseNode,
    ble_config: BleConfig,
    rng: Optional[random.Random],
    heard: Optional[Dict[int, float]],
    duty: Optional[Dict[int, float]],
    channels: int,
) -> float:
    # Shadowing (see radio.RadioParams.shadowing_std_db) makes the margin a
    # stochastic per-tick sample: an unlucky fade can push the received
    # power below the sensitivity floor even inside the range used to
    # shortlist neighbors, a true outage nothing gets through.
    margin_db = link_margin_db(sender.position.distance_to(contact.position), _link_radio(ble_config, sender, contact), rng)
    if margin_db < 0.0:
        return 1.0
    # Frequency hopping: a neighbor transmitting a share u of the time lands
    # on this packet's channel with probability ~u / channels, so the packet
    # survives the whole load L the receiver hears (minus the sender's own)
    # with probability exp(-L / channels). No cap: a packed crowd saturates.
    other_load = 0.0
    if heard is not None and duty is not None:
        other_load = max(0.0, heard.get(contact.id, 0.0) - duty.get(sender.id, 0.0))
    collision = 1.0 - math.exp(-other_load / channels)
    weak_signal = _weak_signal_loss_probability(margin_db, ble_config)
    return 1.0 - (1.0 - ble_config.packet_loss_base_probability) * (1.0 - weak_signal) * (1.0 - collision)


def _radio_budget_bytes(ble_config: BleConfig) -> float:
    return ble_config.transfer_rate_bytes_per_s * ble_config.contact_check_interval_s


def _send_control_broadcast(
    sender: BaseNode,
    size: int,
    neighbors: List[BaseNode],
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    ble_config: BleConfig,
    rng: Optional[random.Random],
    channel: Optional[ChannelState],
    airtime_left: Dict[int, float],
    received: Dict[int, List[int]],
) -> bool:
    # One connectionless broadcast to every active node in range: no link
    # slot, no acknowledgment and so no retransmission, each reception is
    # lost or not. Otherwise the same rules as data, so control-heavy
    # algorithms get no free ride: the shared airtime budget, the load on
    # the advertising channels, and tx/rx energy.
    if not sender.is_active:
        return False
    budget = _radio_budget_bytes(ble_config)
    left = airtime_left.get(sender.id, budget)
    if size > left:
        return False
    airtime_left[sender.id] = left - size
    sender.consume_energy(energy_model.cost_of_tx(size))
    if channel is not None:
        channel.sent_control[sender.id] = channel.sent_control.get(sender.id, 0.0) + size
    for contact in neighbors:
        # Neighbors are listed at tick start; a battery may have died since.
        if not contact.is_active:
            continue
        contact_left = airtime_left.get(contact.id, budget)
        if size > contact_left:
            continue
        airtime_left[contact.id] = contact_left - size
        failure = _link_failure_probability(
            sender, contact, ble_config, rng,
            channel.heard_control if channel is not None else None,
            channel.duty_control if channel is not None else None,
            ble_config.advertising_channels,
        )
        if failure >= 1.0 or (rng is not None and failure > 0.0 and rng.random() < failure):
            metrics.record_packet_loss()
            continue
        contact.consume_energy(energy_model.cost_of_rx(size))
        received.setdefault(contact.id, []).append(sender.id)
    return True


def _exchange_metadata(
    a: BaseNode,
    b: BaseNode,
    conn: _Connection,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    ble_config: BleConfig,
    rng: Optional[random.Random],
    channel: Optional[ChannelState],
    airtime_left: Dict[int, float],
) -> None:
    # What decide() and has_message() read about the peer has to cross the
    # link first, every tick, before any data: each side's summary vector
    # (only ids it hasn't listed yet on this connection), the acks the peer
    # asks for (ids it advertises that this side knows were delivered), and
    # once per connection the algorithm's tables. Billed like data on the
    # same link; if it doesn't fit this tick nothing is exchanged and it is
    # retried next tick.
    acks = routing_algorithm.uses_delivery_acks
    sides = []
    total = 0.0
    for x, y in ((a, b), (b, a)):
        ids = x.buffer.keys() | x.delivered_ids
        if acks:
            ids |= x.outbox.keys()
        new_ids = ids - conn.advertised.get(x.id, set())
        acks_out: List[int] = []
        if acks and x.acked:
            sent = conn.acks_sent.get(x.id, set())
            asked = y.buffer.keys() | y.outbox.keys()
            acks_out = [mid for mid in asked if mid in x.acked and mid not in sent]
        size = ble_config.summary_id_bytes * len(new_ids) + routing_algorithm.ack_size_bytes * len(acks_out)
        if not conn.tables_sent:
            size += routing_algorithm.connection_table_bytes(x, y)
        sides.append((x, y, new_ids, acks_out, size))
        total += size
    if total == 0:
        conn.tables_sent = True
        return
    failure = _link_failure_probability(
        a, b, ble_config, rng,
        channel.heard_data if channel is not None else None,
        channel.duty_data if channel is not None else None,
        ble_config.data_channels,
    )
    if failure >= 1.0:
        return
    attempts = 1.0 / (1.0 - failure)
    budget = _radio_budget_bytes(ble_config)
    a_left, b_left = airtime_left.get(a.id, budget), airtime_left.get(b.id, budget)
    if total * attempts > min(a_left, b_left):
        return
    airtime_left[a.id] = a_left - total * attempts
    airtime_left[b.id] = b_left - total * attempts
    conn.tables_sent = True
    for x, y, new_ids, acks_out, size in sides:
        if size == 0:
            continue
        x.consume_energy(energy_model.cost_of_tx(size) * attempts)
        y.consume_energy(energy_model.cost_of_rx(size) * attempts)
        if channel is not None:
            channel.sent_data[x.id] = channel.sent_data.get(x.id, 0.0) + size * attempts
        conn.advertised.setdefault(x.id, set()).update(new_ids)
        conn.acks_sent.setdefault(x.id, set()).update(acks_out)
        for mid in acks_out:
            y.learn_ack(mid, x.acked[mid])


def process_node_contacts(
    now: float,
    sender: BaseNode,
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    messages: Optional[List[Message]] = None,
    ble_config: Optional[BleConfig] = None,
    rng: Optional[random.Random] = None,
    channel: Optional[ChannelState] = None,
    event_log: Optional[List[Dict[str, Any]]] = None,
    neighbors: Optional[List[BaseNode]] = None,
    on_delivery: Optional[Callable[[Message, BaseNode, float], None]] = None,
    airtime_left: Optional[Dict[int, float]] = None,
) -> List[int]:
    # Returns the contacts the sender put anything on the air towards:
    # network_engine reads it as connection activity.
    _purge_expired_messages(sender, now)

    if not sender.buffer or not sender.is_active:
        return []

    # Process only what sender held at tick start (or what the caller
    # passes explicitly). A message received from another node earlier
    # in this same tick must wait until next tick to be relayed further
    # — otherwise propagation speed depends on node iteration order.
    if messages is None:
        messages = list(sender.buffer.values())

    # neighbors, when given, are the links network_engine already assigned
    # (see _update_connections); otherwise this sender picks its own.
    if neighbors is None:
        neighbors = _active_nearby(sender, grid)
        if ble_config is not None and ble_config.max_concurrent_links is not None:
            neighbors = routing_algorithm.select_links(sender, neighbors, ble_config.max_concurrent_links)

    # Per radio, not per link: one node's sends and receives this tick all
    # share its airtime. network_engine passes one dict for the whole tick so
    # a receiver busy with one sender has less left for the others.
    radio_budget_bytes = None
    if ble_config is not None:
        radio_budget_bytes = _radio_budget_bytes(ble_config)
    if airtime_left is None:
        airtime_left = {}

    sent_to: List[int] = []
    for contact in neighbors:
        if not contact.is_active:
            continue

        # A connection acknowledges every packet and resends the lost ones,
        # so loss costs airtime and energy (1 / (1 - p) attempts on average)
        # instead of dropping the message; only an outage carries nothing.
        attempts = 1.0
        if ble_config is not None:
            failure = _link_failure_probability(
                sender, contact, ble_config, rng,
                channel.heard_data if channel is not None else None,
                channel.duty_data if channel is not None else None,
                ble_config.data_channels,
            )
            if failure >= 1.0:
                continue
            attempts = 1.0 / (1.0 - failure)

        for message in messages:
            if not sender.is_active:
                return sent_to
            if message.msg_id not in sender.buffer:
                continue
            if not contact.is_active:
                break

            is_delivery = contact.id == message.dst_id
            if is_delivery:
                if contact.has_message(message.msg_id):
                    continue
            else:
                # Network-layer hop TTL only caps relaying, not direct delivery:
                # a holder still carries and can hand off a hop-exhausted
                # message straight to its destination, it just stops spreading
                # it to other relays — the same "wait phase" semantics Spray &
                # Wait already uses for its last copy.
                if message.hop_limit_reached():
                    continue
                if routing_algorithm.decide(message, sender, contact, now) is not RoutingDecision.FORWARD:
                    continue

            # Budget only applies once something is actually sent: a message
            # the routing would ignore (or the contact already has) costs
            # neither airtime nor energy.
            airtime = message.size_bytes * attempts
            if radio_budget_bytes is not None:
                sender_left = airtime_left.get(sender.id, radio_budget_bytes)
                contact_left = airtime_left.get(contact.id, radio_budget_bytes)
                if airtime > min(sender_left, contact_left):
                    # Doesn't fit either radio's airtime left this tick; stays queued, retried next tick.
                    continue
                airtime_left[sender.id] = sender_left - airtime
                airtime_left[contact.id] = contact_left - airtime

            if not sent_to or sent_to[-1] != contact.id:
                sent_to.append(contact.id)
            if channel is not None:
                channel.sent_data[sender.id] = channel.sent_data.get(sender.id, 0.0) + airtime
            copy = replace(message, hops=message.hops + 1, routing_state=dict(message.routing_state))
            sender.consume_energy(energy_model.cost_of_tx(message.size_bytes) * attempts)
            contact.consume_energy(energy_model.cost_of_rx(message.size_bytes) * attempts)
            metrics.record_transmission(message)
            metrics.record_retransmission(message, airtime - message.size_bytes)
            if is_delivery:
                contact.mark_delivered(copy.msg_id)
                if routing_algorithm.uses_delivery_acks:
                    # The destination acks straight back on this connection.
                    expiry = copy.creation_time + copy.ttl_s
                    contact.acked[copy.msg_id] = expiry
                    sender.learn_ack(copy.msg_id, expiry)
                    contact.consume_energy(energy_model.cost_of_tx(routing_algorithm.ack_size_bytes))
                    sender.consume_energy(energy_model.cost_of_rx(routing_algorithm.ack_size_bytes))
                if copy.src_position is not None:
                    contact.record_known_position(copy.src_id, copy.src_position, copy.creation_time)
                metrics.record_delivery(copy, now)
                routing_algorithm.on_delivered(copy, sender)
                if on_delivery is not None:
                    on_delivery(copy, contact, now)
            else:
                contact.store_message(copy, choose_victim=lambda node: routing_algorithm.choose_eviction(node, now))
                routing_algorithm.on_forward(message, sender, contact, copy)
            if event_log is not None:
                event_log.append(_relay_event(now, sender.id, contact.id, copy, is_delivery))
    return sent_to

def _relay_event(now: float, from_id: int, to_id: int, message: Message, delivered: bool, backhaul: bool = False) -> Dict[str, Any]:
    event = {
        "time": now, "from": from_id, "to": to_id, "delivered": delivered,
        "msg": message.msg_id, "hops": message.hops,
        "src": message.src_id, "dst": message.dst_id, "created": message.creation_time,
    }
    if backhaul:
        event["backhaul"] = True
    return event


def beacon_backhaul_relay(
    now: float,
    beacon_ids: List[int],
    nodes: Dict[int, BaseNode],
    snapshot: Dict[int, List[Message]],
    metrics: MetricsCollector,
    contact_check_interval_s: float = 1.0,
    beacon_config: Optional[BeaconConfig] = None,
    rng: Optional[random.Random] = None,
    event_log: Optional[List[Dict[str, Any]]] = None,
) -> None:
    # Simulates a WiFi/wired backhaul between fixed beacons: no radio-range
    # check, no BLE bandwidth/contention, and (like the hop count it
    # deliberately never increments) no BLE mesh network-layer hop TTL
    # either — it's a separate wired backbone, not a mesh relay. It isn't
    # perfectly instant or lossless though: see BeaconConfig.backhaul_latency_s
    # / backhaul_loss_probability. Reads only the pre-tick snapshot and
    # writes into other beacons' live buffers, so a message relayed here
    # only becomes visible for further relay (BLE or backhaul) starting
    # next tick — preserving the tick-snapshot invariant. A message not yet
    # attempted (still "in flight") or lost this tick is retried
    # automatically next tick, since the source still holds it and the
    # target still doesn't.
    if len(beacon_ids) < 2:
        return

    attempt_prob = 1.0
    loss_prob = 0.0
    if beacon_config is not None:
        attempt_prob = min(1.0, contact_check_interval_s / beacon_config.backhaul_latency_s)
        loss_prob = beacon_config.backhaul_loss_probability

    for src_id in beacon_ids:
        source = nodes[src_id]
        if not source.is_active:
            continue
        for message in snapshot[src_id]:
            if message.msg_id not in source.buffer or message.is_expired(now):
                continue
            for dst_id in beacon_ids:
                if dst_id == src_id:
                    continue
                target = nodes[dst_id]
                if not target.is_active or target.has_message(message.msg_id):
                    continue
                if rng is not None and attempt_prob < 1.0 and rng.random() >= attempt_prob:
                    continue
                if rng is not None and loss_prob > 0.0 and rng.random() < loss_prob:
                    metrics.record_backhaul_loss(message)
                    continue
                relayed = replace(message, routing_state=dict(message.routing_state))
                target.store_message(relayed)
                metrics.record_backhaul_transmission(message)
                if event_log is not None:
                    event_log.append(_relay_event(now, src_id, dst_id, relayed, False, backhaul=True))


def _share_beacon_acks(beacons: List[BaseNode]) -> None:
    # The backhaul is a separate backbone: whatever one beacon learned,
    # they all know.
    merged: Dict[int, float] = {}
    for beacon in beacons:
        merged.update(beacon.acked)
    for beacon in beacons:
        for mid in merged.keys() - beacon.acked.keys():
            beacon.learn_ack(mid, merged[mid])


def network_engine(
    env,
    nodes: Dict[int, BaseNode],
    grid: SpatialGrid,
    routing_algorithm: RoutingAlgorithm,
    energy_model: EnergyModel,
    metrics: MetricsCollector,
    contact_check_interval_s: float,
    ble_config: Optional[BleConfig] = None,
    beacon_config: Optional[BeaconConfig] = None,
    rng: Optional[random.Random] = None,
    event_log: Optional[List[Dict[str, Any]]] = None,
    on_delivery: Optional[Callable[[Message, BaseNode, float], None]] = None,
):
    beacon_ids = [node_id for node_id, node in nodes.items() if isinstance(node, BeaconNode)]
    channel: Optional[ChannelState] = ChannelState() if ble_config is not None else None
    connections: Dict[Tuple[int, int], _Connection] = {}
    while True:
        yield env.timeout(contact_check_interval_s)
        now = env.now
        if routing_algorithm.uses_delivery_acks and len(beacon_ids) > 1:
            _share_beacon_acks([nodes[b] for b in beacon_ids if nodes[b].is_active])
        snapshot = {node_id: list(node.buffer.values()) for node_id, node in nodes.items()}
        beacon_backhaul_relay(
            now, beacon_ids, nodes, snapshot, metrics,
            contact_check_interval_s=contact_check_interval_s,
            beacon_config=beacon_config,
            rng=rng,
            event_log=event_log,
        )
        neighbors_by_node = _compute_neighbors(nodes, grid) if ble_config is not None else None
        broadcasts: Dict[int, int] = {}
        if neighbors_by_node is not None:
            routing_algorithm.on_tick(now, neighbors_by_node)
            broadcasts = routing_algorithm.control_broadcasts(now)
            channel = channel.next_tick(neighbors_by_node, _radio_budget_bytes(ble_config))
        airtime_left: Dict[int, float] = {}
        received: Dict[int, List[int]] = {}
        sent: List[int] = []
        # Senders compete for receivers' airtime, so a fixed order would let
        # the lowest ids (the beacons) always win it.
        order = list(nodes.items())
        if rng is not None:
            rng.shuffle(order)
        links = (
            _update_connections(now, order, neighbors_by_node, snapshot, routing_algorithm, ble_config, connections)
            if neighbors_by_node is not None else None
        )
        if links is not None:
            for (a_id, b_id), conn in connections.items():
                if conn.ready_at <= now:
                    _exchange_metadata(
                        nodes[a_id], nodes[b_id], conn, routing_algorithm, energy_model, ble_config, rng, channel,
                        airtime_left,
                    )
        for node_id, sender in order:
            # A node's control broadcast goes out at its turn, just before its
            # data: no global priority of control over data or the reverse.
            if node_id in broadcasts and sender.is_active and _send_control_broadcast(
                sender, broadcasts[node_id], neighbors_by_node.get(node_id, []), energy_model, metrics,
                ble_config, rng, channel, airtime_left, received,
            ):
                sent.append(node_id)
            sent_to = process_node_contacts(
                now, sender, grid, routing_algorithm, energy_model, metrics,
                messages=snapshot[node_id],
                ble_config=ble_config,
                rng=rng,
                channel=channel,
                event_log=event_log,
                neighbors=links.get(node_id, []) if links is not None else None,
                on_delivery=on_delivery,
                airtime_left=airtime_left,
            )
            for contact_id in sent_to:
                key = (min(node_id, contact_id), max(node_id, contact_id))
                if key in connections:
                    connections[key].last_used = now
        if broadcasts:
            routing_algorithm.on_control_received(now, received, sent)
