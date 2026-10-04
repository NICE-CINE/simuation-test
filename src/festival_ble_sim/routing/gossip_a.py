from __future__ import annotations
import math
import random
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_Pair = Tuple[int, int]


class GossipARouting(RoutingAlgorithm):
    # Single shared instance per run, like dasfv.py: per-node state (density,
    # purge tokens, seenHolders, per-peer session budgets) is keyed by node id
    # here instead of living on BaseNode. Crypto tags, PoW, SOS and the GATT
    # wire format are out of scope; the engine already models recognition of
    # the anonymous tag by delivering straight to message.dst_id. What is
    # kept is everything that changes who holds which copy: adaptive p,
    # K_FLOOD/H_MAX, per-(message, peer) draws, SUMMARY bloom false
    # positives, counter-based suppression, epidemic purge tokens, per-session
    # byte/bundle budgets and "most replicated first" eviction.
    def __init__(
        self,
        c: float = 4.0,
        p_min: float = 0.05,
        k_flood: int = 2,
        h_max: int = 15,
        k_sup: int = 3,
        suppression_window_s: float = 60.0,
        density_window_s: float = 10.0,
        density_ewma_alpha: float = 0.3,
        session_cooldown_s: float = 60.0,
        session_budget_bytes: Optional[int] = 32 * 1024,
        max_bundles_per_peer_per_session: Optional[int] = 50,
        summary_bloom_bits: int = 4096,
        summary_bloom_hashes: int = 4,
        max_purge_tokens: int = 5000,
        adaptive: bool = True,
        suppression: bool = True,
        replicated_first_eviction: bool = True,
        seed: Optional[int] = 0,
    ) -> None:
        if not 0.0 < p_min <= 1.0:
            raise ValueError("p_min must be in (0, 1]")
        if c <= 0:
            raise ValueError("c must be > 0")
        if k_flood < 0 or h_max < 1:
            raise ValueError("k_flood must be >= 0 and h_max >= 1")
        if max_purge_tokens < 1:
            raise ValueError("max_purge_tokens must be >= 1")
        self._c = c
        self._p_min = p_min
        self._k_flood = k_flood
        self._h_max = h_max
        self._k_sup = k_sup
        self._suppression_window_s = suppression_window_s
        self._density_window_s = density_window_s
        self._density_ewma_alpha = density_ewma_alpha
        self._session_cooldown_s = session_cooldown_s
        self._session_budget_bytes = session_budget_bytes
        self._max_bundles_per_peer = max_bundles_per_peer_per_session
        self._bloom_bits = summary_bloom_bits
        self._bloom_hashes = summary_bloom_hashes
        self._max_purge_tokens = max_purge_tokens
        self._adaptive = adaptive
        self._suppression = suppression
        self._replicated_first_eviction = replicated_first_eviction
        self._rng = random.Random(seed)

        self._last_seen: Dict[int, Dict[int, float]] = {}
        self._density: Dict[int, float] = {}
        self._density_tick: Dict[int, float] = {}
        # Dict used as an insertion-ordered set: the oldest token is the
        # first dropped once max_purge_tokens is hit (spec §8).
        self._purges: Dict[int, Dict[int, None]] = {}
        self._seen_holders: Dict[int, Dict[int, Dict[int, float]]] = {}
        # (holder, contact) -> [session start, bytes sent, bundles sent].
        self._sessions: Dict[_Pair, List[float]] = {}
        # (holder, contact) -> {msg_id: draw time}: a refused draw sticks for
        # the whole session, otherwise re-drawing every tick of a long
        # contact would push the effective forwarding probability to 1.
        self._refused: Dict[_Pair, Dict[int, float]] = {}
        self._synced_this_tick: Set[_Pair] = set()
        self._sync_tick: Optional[float] = None
        self._now = 0.0
        self._last_prune = 0.0
        self._ctx_holder = -1
        self._ctx_contact = -1
        self._ctx_now = -math.inf

    def _record_encounter(self, a: int, b: int, now: float) -> None:
        if self._last_seen.get(a, {}).get(b) == now:
            return
        self._last_seen.setdefault(a, {})[b] = now
        self._last_seen.setdefault(b, {})[a] = now

    def density(self, node_id: int, now: float) -> float:
        if self._density_tick.get(node_id) != now:
            seen = self._last_seen.get(node_id, {})
            stale = [peer for peer, t in seen.items() if now - t > self._density_window_s]
            for peer in stale:
                del seen[peer]
            previous = self._density.get(node_id)
            raw = float(len(seen))
            alpha = self._density_ewma_alpha
            self._density[node_id] = raw if previous is None else alpha * raw + (1 - alpha) * previous
            self._density_tick[node_id] = now
        return self._density[node_id]

    def knows_purge(self, node_id: int, msg_id: int) -> bool:
        return msg_id in self._purges.get(node_id, {})

    def _add_purges(self, node: "BaseNode", msg_ids) -> None:
        tokens = self._purges.setdefault(node.id, {})
        for msg_id in msg_ids:
            if msg_id in tokens:
                continue
            tokens[msg_id] = None
            node.buffer.pop(msg_id, None)
            self._seen_holders.get(node.id, {}).pop(msg_id, None)
        while len(tokens) > self._max_purge_tokens:
            del tokens[next(iter(tokens))]

    def _sync_purges(self, a: "BaseNode", b: "BaseNode", now: float) -> None:
        if self._sync_tick != now:
            self._sync_tick = now
            self._synced_this_tick = set()
        pair = (a.id, b.id) if a.id < b.id else (b.id, a.id)
        if pair in self._synced_this_tick:
            return
        self._synced_this_tick.add(pair)
        tokens_a = self._purges.get(a.id, {})
        tokens_b = self._purges.get(b.id, {})
        if len(tokens_a) == len(tokens_b) and tokens_a.keys() == tokens_b.keys():
            return
        missing_at_b = [m for m in tokens_a if m not in tokens_b]
        missing_at_a = [m for m in tokens_b if m not in tokens_a]
        self._add_purges(b, missing_at_b)
        self._add_purges(a, missing_at_a)

    def _note_holder(self, node_id: int, msg_id: int, peer_id: int, now: float) -> None:
        self._seen_holders.setdefault(node_id, {}).setdefault(msg_id, {})[peer_id] = now

    def replication(self, node_id: int, msg_id: int, now: float) -> int:
        holders = self._seen_holders.get(node_id, {}).get(msg_id)
        if not holders:
            return 0
        stale = [peer for peer, t in holders.items() if now - t > self._suppression_window_s]
        for peer in stale:
            del holders[peer]
        return len(holders)

    def forward_probability(self, message: Message, holder: "BaseNode", now: float) -> float:
        if message.hops >= self._h_max:
            return 0.0
        if message.hops < self._k_flood:
            return 1.0
        if self._suppression and self.replication(holder.id, message.msg_id, now) >= self._k_sup:
            return 0.0
        if not self._adaptive:
            return 1.0
        return min(1.0, max(self._p_min, self._c / max(self.density(holder.id, now), 1.0)))

    def _bloom_false_positive(self, n_items: int) -> float:
        if n_items <= 0:
            return 0.0
        k = self._bloom_hashes
        return (1.0 - math.exp(-k * n_items / self._bloom_bits)) ** k

    def _session(self, pair: _Pair, now: float) -> List[float]:
        session = self._sessions.get(pair)
        if session is None or now - session[0] >= self._session_cooldown_s:
            session = [now, 0.0, 0.0]
            self._sessions[pair] = session
            self._refused.pop(pair, None)
        return session

    def _prune(self, now: float) -> None:
        # Per-pair and per-message bookkeeping would otherwise grow with every
        # pair that ever met, which adds up over an hour at 10000 nodes.
        if now - self._last_prune < self._session_cooldown_s:
            return
        self._last_prune = now
        for pair in [p for p, s in self._sessions.items() if now - s[0] >= self._session_cooldown_s]:
            del self._sessions[pair]
            self._refused.pop(pair, None)
        horizon = now - self._suppression_window_s
        for per_msg in self._seen_holders.values():
            stale = [m for m, peers in per_msg.items() if max(peers.values(), default=-math.inf) < horizon]
            for msg_id in stale:
                del per_msg[msg_id]

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        self._now = now
        if now - self._last_prune >= self._session_cooldown_s:
            self._prune(now)
        holder_id = holder.id
        contact_id = contact.id
        # Both calls are idempotent for a given (holder, contact, now), and the
        # engine walks every buffered message for one contact in a row.
        if holder_id != self._ctx_holder or contact_id != self._ctx_contact or now != self._ctx_now:
            self._ctx_holder = holder_id
            self._ctx_contact = contact_id
            self._ctx_now = now
            self._record_encounter(holder_id, contact_id, now)
            self._sync_purges(holder, contact, now)
        msg_id = message.msg_id
        if msg_id not in holder.buffer:
            return RoutingDecision.IGNORE

        if msg_id in contact.buffer:
            seen = self._seen_holders
            seen.setdefault(holder_id, {}).setdefault(msg_id, {})[contact_id] = now
            seen.setdefault(contact_id, {}).setdefault(msg_id, {})[holder_id] = now
            return RoutingDecision.IGNORE
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE

        pair = (holder.id, contact.id)
        session = self._session(pair, now)
        if self._session_budget_bytes is not None and session[1] + message.size_bytes > self._session_budget_bytes:
            return RoutingDecision.IGNORE
        if self._max_bundles_per_peer is not None and session[2] >= self._max_bundles_per_peer:
            return RoutingDecision.IGNORE

        refused = self._refused.get(pair)
        if refused is not None and message.msg_id in refused:
            return RoutingDecision.IGNORE

        p = self.forward_probability(message, holder, now)
        # The SUMMARY bloom of the contact's buffer can wrongly claim it
        # already holds this message; gossip redundancy is meant to absorb it.
        false_positive = self._rng.random() < self._bloom_false_positive(len(contact.buffer))
        if false_positive or p <= 0.0 or self._rng.random() >= p:
            self._refused.setdefault(pair, {})[message.msg_id] = now
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        session = self._sessions.get((holder.id, contact.id))
        if session is not None:
            session[1] += message.size_bytes
            session[2] += 1
        self._note_holder(holder.id, message.msg_id, contact.id, self._now)
        self._note_holder(contact.id, message.msg_id, holder.id, self._now)

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        # The destination mints the purge token and hands it straight back in
        # the same session, so the delivering holder learns it immediately.
        tokens = self._purges.setdefault(message.dst_id, {})
        tokens[message.msg_id] = None
        while len(tokens) > self._max_purge_tokens:
            del tokens[next(iter(tokens))]
        self._add_purges(holder, [message.msg_id])

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        if not self._replicated_first_eviction or not node.buffer:
            return None
        tokens = self._purges.get(node.id, {})

        def eviction_rank(msg_id: int) -> Tuple[int, int, int, int]:
            message = node.buffer[msg_id]
            return (
                1 if msg_id in tokens else 0,
                1 if message.is_expired(now) else 0,
                self.replication(node.id, msg_id, now),
                message.hops,
            )

        return max(node.buffer, key=eviction_rank)
