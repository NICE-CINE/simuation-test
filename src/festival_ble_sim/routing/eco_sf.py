from __future__ import annotations
import heapq
import math
import random
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_COPIES = "copies"
_GIVE = "_give"
_Views = Dict[int, Dict[int, float]]


def _rank(item: Tuple[int, Tuple[float, float, float]]) -> float:
    return item[1][2]


class _NodeState:
    __slots__ = ("interval", "end", "tx_at", "heard", "epoch", "neighbors", "utility")

    def __init__(self) -> None:
        self.interval = 0.0
        self.end = 0.0
        self.tx_at = 0.0
        self.heard = 0
        self.epoch = 0
        # sender id -> (last heard, entry expiry, sender's digest epoch)
        self.neighbors: Dict[int, Tuple[float, float, int]] = {}
        # dest id -> (u, last update, rank); see EcoSfRouting._set_u
        self.utility: Dict[int, Tuple[float, float, float]] = {}


class EcoSfRouting(RoutingAlgorithm):
    # Network-level reduction of ECO-SF (docs/ECO-SF.md). Beacons are not
    # simulated as BLE frames: a Trickle-timed beacon is "heard" by every
    # active node in the sender's range that tick, and the Bloom digests are
    # read as exact sets. What the Trickle timer does model is discovery:
    # a pair can only open a connection once one side has heard the other.
    def __init__(
        self,
        seed: int = 0,
        i_min_s: float = 2.0,
        i_max_s: float = 30.0,
        i_max_mid_s: float = 60.0,
        i_max_low_s: float = 120.0,
        trickle_k: int = 1,
        l0: int = 8,
        l_max: int = 16,
        n_ref: float = 10.0,
        density_window_s: float = 60.0,
        alpha: float = 0.5,
        beta: float = 0.25,
        gamma_per_min: float = 0.98,
        delta: float = 0.1,
        utility_table_size: int = 64,
        utility_exchange_size: int = 32,
        dest_bloom_threshold: float = 0.05,
        connect_cooldown_s: float = 20.0,
        late_after_s: float = 600.0,
        battery_mid_pct: float = 0.50,
        battery_relay_pct: float = 0.20,
        battery_silent_pct: float = 0.10,
    ) -> None:
        if l_max < 2:
            raise ValueError("l_max must be >= 2")
        if i_max_s < i_min_s:
            raise ValueError("i_max_s must be >= i_min_s")
        self._rng = random.Random(seed)
        self._i_min = i_min_s
        self._i_max = i_max_s
        self._i_max_mid = i_max_mid_s
        self._i_max_low = i_max_low_s
        self._k = trickle_k
        self._l0 = l0
        self._l_max = l_max
        self._n_ref = n_ref
        self._density_window = density_window_s
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma_per_min
        self._ln_gamma = math.log(gamma_per_min)
        self._delta = delta
        self._table_size = utility_table_size
        self._exchange_size = utility_exchange_size
        self._bloom_threshold = dest_bloom_threshold
        self._cooldown = connect_cooldown_s
        self._late_after = late_after_s
        self._battery_mid = battery_mid_pct
        self._battery_relay = battery_relay_pct
        self._battery_silent = battery_silent_pct
        self._nodes: Dict[int, "BaseNode"] = {}
        self._states: Dict[int, _NodeState] = {}
        # Cooldown clock per pair, pruned every cooldown period. The exchanged
        # utility views and refusals only matter within one tick, so they are
        # dropped at each on_tick instead of piling up for every pair ever met.
        self._last_connect: Dict[Tuple[int, int], float] = {}
        self._last_prune = 0.0
        self._connections: Dict[Tuple[int, int], Tuple[float, _Views]] = {}
        self._refused: Dict[Tuple[int, int], float] = {}
        # Signed ACKs gossip epidemically in the spec; modelled as an instant,
        # reliable network-wide purge, like every other purge in this repo.
        self._delivered: Set[int] = set()
        self._now = 0.0
        self.stats = {"beacons": 0, "trickle_resets": 0, "connections": 0, "spray": 0, "focus": 0}

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        self._nodes = nodes

    @staticmethod
    def _battery_pct(node: "BaseNode") -> float:
        initial = node.initial_battery_mah
        if initial == math.inf or initial <= 0:
            return 1.0
        return node.battery_mah / initial

    def _node_i_max(self, node: "BaseNode") -> float:
        pct = self._battery_pct(node)
        if pct < self._battery_relay:
            return self._i_max_low
        if pct < self._battery_mid:
            return self._i_max_mid
        return self._i_max

    def _state(self, node_id: int, now: float) -> _NodeState:
        state = self._states.get(node_id)
        if state is None:
            state = self._states[node_id] = _NodeState()
            self._start_interval(state, now, self._i_min)
        return state

    def _start_interval(self, state: _NodeState, now: float, interval: float) -> None:
        state.interval = interval
        state.end = now + interval
        state.tx_at = now + self._rng.uniform(interval / 2, interval)
        state.heard = 0

    def _reset(self, state: _NodeState, now: float) -> None:
        # RFC 6206: an inconsistency while already at Imin changes nothing,
        # otherwise a busy neighbourhood would restart the interval forever.
        if state.interval > self._i_min:
            self._start_interval(state, now, self._i_min)
            self.stats["trickle_resets"] += 1

    def _buffer_changed(self, node_id: int, now: float, wake_radio: bool = True) -> None:
        state = self._state(node_id, now)
        state.epoch += 1
        if wake_radio:
            self._reset(state, now)

    def _u(self, state: _NodeState, dest: int, now: float) -> float:
        entry = state.utility.get(dest)
        if entry is None:
            return 0.0
        u, last, _ = entry
        return u * self._gamma ** (max(0.0, now - last) / 60.0)

    def _set_u(self, state: _NodeState, dest: int, u: float, now: float) -> None:
        # Every entry ages by the same factor, so ordering by aged utility is
        # ordering by ln(u) - last/60 * ln(gamma): computed once here instead
        # of re-aging the whole table on each eviction (a dense crowd evicts
        # on nearly every beacon heard).
        if dest not in state.utility and len(state.utility) >= self._table_size:
            del state.utility[min(state.utility.items(), key=_rank)[0]]
        state.utility[dest] = (u, now, math.log(u) - now / 60.0 * self._ln_gamma)

    def _top_utilities(self, state: _NodeState, now: float) -> Dict[int, float]:
        top = heapq.nlargest(self._exchange_size, state.utility.items(), key=lambda kv: (kv[1][2], kv[0]))
        return {d: self._u(state, d, now) for d, _ in top}

    def _hear(self, receiver_id: int, sender: "BaseNode", now: float) -> None:
        receiver = self._state(receiver_id, now)
        sender_state = self._state(sender.id, now)
        entry = receiver.neighbors.get(sender.id)
        receiver.neighbors[sender.id] = (now, now + 3 * self._node_i_max(sender), sender_state.epoch)
        if entry is None or now > entry[1]:
            u = self._u(receiver, sender.id, now)
            self._set_u(receiver, sender.id, u + (1 - u) * self._alpha, now)
            self._reset(receiver, now)
        elif entry[2] != sender_state.epoch:
            self._reset(receiver, now)
        else:
            receiver.heard += 1

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        self._connections.clear()
        self._refused.clear()
        if now - self._last_prune >= self._cooldown:
            self._last_connect = {k: t for k, t in self._last_connect.items() if now - t < self._cooldown}
            self._last_prune = now
        for node_id, neighbors in neighbors_by_node.items():
            node = self._nodes.get(node_id)
            if node is None:
                continue
            state = self._state(node_id, now)
            for mid, message in list(node.buffer.items()):
                if mid in self._delivered:
                    del node.buffer[mid]
                    self._buffer_changed(node_id, now)
                elif _COPIES not in message.routing_state:
                    message.routing_state[_COPIES] = self._initial_copies(state, now)
                    self._buffer_changed(node_id, now)
            if now >= state.tx_at:
                state.tx_at = math.inf
                silent = self._battery_pct(node) < self._battery_silent and not any(
                    m.src_id == node_id for m in node.buffer.values()
                )
                if state.heard < self._k and not silent:
                    self.stats["beacons"] += 1
                    for neighbor in neighbors:
                        if neighbor.is_active:
                            self._hear(neighbor.id, node, now)
            if now >= state.end:
                self._start_interval(state, now, min(2 * state.interval, self._node_i_max(node)))

    def _initial_copies(self, state: _NodeState, now: float) -> int:
        density = sum(1 for heard, _, _ in state.neighbors.values() if now - heard <= self._density_window)
        copies = math.ceil(self._l0 * math.sqrt(self._n_ref / max(density, 1)))
        return min(self._l_max, max(2, copies))

    def _discovered(self, a: int, b: int, now: float) -> bool:
        for x, y in ((a, b), (b, a)):
            state = self._states.get(x)
            entry = state.neighbors.get(y) if state is not None else None
            if entry is not None and now <= entry[1]:
                return True
        return False

    def _should_connect(self, holder: "BaseNode", peer: "BaseNode", now: float) -> bool:
        if self._battery_pct(peer) < self._battery_silent:
            return False
        if not self._discovered(holder.id, peer.id, now):
            return False
        peer_state = self._state(peer.id, now)
        for message in holder.buffer.values():
            if message.dst_id == peer.id:
                return True
            if (
                message.msg_id not in self._delivered
                and now - message.creation_time <= self._late_after
                and not peer.has_message(message.msg_id)
                and self._u(peer_state, message.dst_id, now) > self._bloom_threshold
            ):
                return True
        return False

    def _connection(self, holder: "BaseNode", peer: "BaseNode", now: float) -> Optional[_Views]:
        key = (min(holder.id, peer.id), max(holder.id, peer.id))
        existing = self._connections.get(key)
        if existing is not None and existing[0] == now:
            return existing[1]
        last = self._last_connect.get(key)
        if last is not None and now - last < self._cooldown:
            return None
        if self._refused.get((holder.id, peer.id)) == now:
            return None
        if not self._should_connect(holder, peer, now):
            self._refused[(holder.id, peer.id)] = now
            return None
        holder_state, peer_state = self._state(holder.id, now), self._state(peer.id, now)
        views = {holder.id: self._top_utilities(holder_state, now), peer.id: self._top_utilities(peer_state, now)}
        self._transitive(holder_state, holder.id, peer.id, views[peer.id], now)
        self._transitive(peer_state, peer.id, holder.id, views[holder.id], now)
        self._connections[key] = (now, views)
        self._last_connect[key] = now
        self.stats["connections"] += 1
        return views

    def _transitive(self, state: _NodeState, me: int, peer: int, peer_view: Dict[int, float], now: float) -> None:
        u_me_peer = self._u(state, peer, now)
        if u_me_peer <= 0.0:
            return
        for dest, u_peer_dest in peer_view.items():
            if dest == me:
                continue
            candidate = u_peer_dest * u_me_peer * self._beta
            if candidate > self._u(state, dest, now):
                self._set_u(state, dest, candidate, now)

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if message.msg_id in self._delivered:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        # Past late_after_s a copy only waits for the destination itself,
        # which the engine delivers without asking decide().
        if now - message.creation_time > self._late_after:
            return RoutingDecision.IGNORE
        if self._battery_pct(contact) < self._battery_relay:
            return RoutingDecision.IGNORE
        views = self._connection(holder, contact, now)
        if views is None:
            return RoutingDecision.IGNORE
        dst = message.dst_id
        u_peer = views[contact.id].get(dst, 0.0)
        u_me = self._u(self._state(holder.id, now), dst, now)
        copies = message.routing_state.get(_COPIES, 1)
        if copies > 1:
            w = min(0.75, max(0.25, u_peer / max(u_peer + u_me, 1e-3)))
            message.routing_state[_GIVE] = max(1, math.floor(copies * w))
            return RoutingDecision.FORWARD
        if u_peer > u_me + self._delta:
            message.routing_state[_GIVE] = 1
            return RoutingDecision.FORWARD
        return RoutingDecision.IGNORE

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        give = message.routing_state.pop(_GIVE, 1)
        forwarded_copy.routing_state.pop(_GIVE, None)
        forwarded_copy.routing_state[_COPIES] = give
        left = message.routing_state.get(_COPIES, 1) - give
        now = self._now
        if left >= 1:
            message.routing_state[_COPIES] = left
            self.stats["spray"] += 1
        else:
            holder.buffer.pop(message.msg_id, None)
            self._buffer_changed(holder.id, now)
            self.stats["focus"] += 1
        self._buffer_changed(contact.id, now, wake_radio=now - message.creation_time <= self._late_after)

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        self._delivered.add(message.msg_id)

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        if not node.buffer:
            return None
        for mid, message in node.buffer.items():
            if mid in self._delivered or message.is_expired(now):
                return mid
        state = self._state(node.id, now)
        others = [m for m in node.buffer.values() if m.src_id != node.id]
        pool = others or list(node.buffer.values())

        def priority(m: Message) -> float:
            remaining = max(0.0, 1.0 - (now - m.creation_time) / m.ttl_s)
            own = 2.0 if m.src_id == node.id else 1.0
            return (self._u(state, m.dst_id, now) + 0.05) * remaining * own

        return min(pool, key=priority).msg_id
