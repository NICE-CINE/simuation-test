from __future__ import annotations
import random
from collections import deque
from typing import Deque, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_TOKENS = "tokens"
_LAST_PROGRESS = "last_progress"
_STUCK_REPLICATED = "stuck_replicated"
_FORWARD_REASON = "_forward_reason"
_MAX_RANK = 255


class BubbleFRouting(RoutingAlgorithm):
    # Like DasfVRouting, one shared instance observes every node, so the
    # SOCIAL exchange (familiar/community Bloom filters, ranks) is read off
    # exact per-node sets instead of simulating the wire format: no Bloom
    # false positives, no falsified ranks/Blooms (rankCap and plausibility
    # checks are adversarial protections with nothing to defend against here).
    def __init__(
        self,
        l_base: int = 8,
        t_meet_s: float = 30.0,
        t_fam_s: float = 1200.0,
        lambda_add: float = 0.6,
        gamma_merge: float = 0.6,
        c_max: int = 300,
        window_s: float = 1800.0,
        n_windows: int = 4,
        rank_refresh_s: float = 300.0,
        delta_g: int = 2,
        delta_l: int = 1,
        t_stuck_s: float = 1800.0,
        two_hop_freshness_s: float = 5.0,
        observation_interval_s: float = 10.0,
        admission_threshold: float = 0.8,
        epoch_s: Optional[float] = None,
        group_size_range: Tuple[int, int] = (2, 8),
        no_friend_fraction: float = 0.2,
        seed: int = 0,
        friend_bootstrap: bool = True,
        simple_detection: bool = True,
        two_hop_relay: bool = True,
        stuck_replication: bool = True,
    ) -> None:
        if l_base < 1:
            raise ValueError("l_base must be >= 1")
        if window_s <= 0 or n_windows < 1:
            raise ValueError("window_s must be > 0 and n_windows >= 1")
        if not 2 <= group_size_range[0] <= group_size_range[1]:
            raise ValueError("group_size_range must satisfy 2 <= lo <= hi")
        if not 0.0 <= no_friend_fraction <= 1.0:
            raise ValueError("no_friend_fraction must be in [0, 1]")
        self._l_base = l_base
        self._t_meet_s = t_meet_s
        self._t_fam_s = t_fam_s
        self._lambda_add = lambda_add
        self._gamma_merge = gamma_merge
        self._c_max = c_max
        self._window_s = window_s
        self._n_windows = n_windows
        self._rank_refresh_s = rank_refresh_s
        self._delta_g = delta_g
        self._delta_l = delta_l
        self._t_stuck_s = t_stuck_s
        self._two_hop_freshness_s = two_hop_freshness_s
        self._observation_interval_s = observation_interval_s
        self._admission_threshold = admission_threshold
        self._epoch_s = epoch_s
        self._group_size_range = group_size_range
        self._no_friend_fraction = no_friend_fraction
        self._seed = seed
        self._friend_bootstrap = friend_bootstrap
        self._simple_detection = simple_detection
        self._two_hop_relay = two_hop_relay
        self._stuck_replication = stuck_replication

        # Ground-truth friend groups (the QR graph), kept even when
        # friend_bootstrap is off so community quality can still be scored.
        self._groups: Dict[int, Set[int]] = {}
        self._friends: Dict[int, Set[int]] = {}
        self._community: Dict[int, Set[int]] = {}
        self._familiar: Dict[int, Set[int]] = {}
        self._contact_dur: Dict[int, Dict[int, float]] = {}
        self._epoch: Dict[int, int] = {}
        self._last_observation: Optional[float] = None
        # Per-tick sightings from decide(), for the 2-hop relay only: social
        # state is sampled every observation_interval_s in on_tick(), too
        # coarse for a "neighbour right now" check.
        self._last_seen: Dict[int, Dict[int, float]] = {}

        self._window_id: Dict[int, int] = {}
        self._meet_dur: Dict[int, Dict[int, float]] = {}
        self._met: Dict[int, Set[int]] = {}
        self._met_in_c: Dict[int, Set[int]] = {}
        self._window_history: Dict[int, Deque[Tuple[int, int]]] = {}
        self._rank_cache: Dict[int, Tuple[float, int, int]] = {}

        self._delivered_ids: Set[int] = set()
        self._now = 0.0
        self.stuck_replications = 0
        self.relays_by_node: Dict[int, int] = {}

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        rng = random.Random(self._seed)
        people = sorted(node_id for node_id, node in nodes.items() if not getattr(node, "is_beacon", False))
        rng.shuffle(people)
        start = round(self._no_friend_fraction * len(people))
        while start < len(people):
            size = rng.randint(*self._group_size_range)
            group = set(people[start:start + size])
            start += size
            if len(group) < 2:
                break
            for member in group:
                self._groups[member] = group
                if self._friend_bootstrap:
                    self._friends[member] = group - {member}

    def _community_of(self, node_id: int) -> Set[int]:
        community = self._community.get(node_id)
        if community is None:
            community = {node_id} | self._friends.get(node_id, set())
            self._community[node_id] = community
        return community

    def _ensure_epoch(self, node_id: int, now: float) -> None:
        if self._epoch_s is None:
            return
        epoch = int(now // self._epoch_s)
        previous = self._epoch.get(node_id)
        self._epoch[node_id] = epoch
        if previous is None or previous == epoch:
            return
        # Friends' next-epoch NIDs are recomputable from their IK_pub; every
        # other member is unlinkable and lost. Windows (ranks) are counts,
        # not identities, so they survive.
        self._community[node_id] = {node_id} | self._friends.get(node_id, set())
        self._familiar.pop(node_id, None)
        self._contact_dur.pop(node_id, None)

    def _add_to_community(self, node_id: int, other_id: int) -> None:
        community = self._community_of(node_id)
        if len(community) < self._c_max:
            community.add(other_id)

    def _roll_windows(self, node_id: int, now: float) -> None:
        window_id = int(now // self._window_s)
        previous = self._window_id.get(node_id)
        self._window_id[node_id] = window_id
        if previous is None or previous == window_id:
            return
        history = self._window_history.setdefault(node_id, deque(maxlen=self._n_windows))
        history.append((len(self._met.get(node_id, ())), len(self._met_in_c.get(node_id, ()))))
        for _ in range(min(window_id - previous - 1, self._n_windows)):
            history.append((0, 0))
        self._meet_dur.pop(node_id, None)
        self._met.pop(node_id, None)
        self._met_in_c.pop(node_id, None)

    def _ranks(self, node_id: int, now: float) -> Tuple[int, int]:
        cached = self._rank_cache.get(node_id)
        if cached is not None and now - cached[0] < self._rank_refresh_s:
            return cached[1], cached[2]
        self._roll_windows(node_id, now)
        history = self._window_history.get(node_id, ())
        # The window in progress counts pro rata of its elapsed time, floored
        # at one refresh period so a just-opened window doesn't extrapolate
        # a handful of meetings into a huge rank.
        elapsed = (now - self._window_id[node_id] * self._window_s) / self._window_s
        weight = len(history) + max(elapsed, self._rank_refresh_s / self._window_s)
        met_global = sum(g for g, _ in history) + len(self._met.get(node_id, ()))
        met_local = sum(c for _, c in history) + len(self._met_in_c.get(node_id, ()))
        global_rank = min(_MAX_RANK, round(met_global / weight))
        local_rank = min(_MAX_RANK, round(met_local / weight))
        self._rank_cache[node_id] = (now, global_rank, local_rank)
        return global_rank, local_rank

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        last = self._last_observation
        if last is not None and now - last < self._observation_interval_s:
            return
        dt = now - (last if last is not None else 0.0)
        self._last_observation = now
        for node_id, neighbors in neighbors_by_node.items():
            for neighbor in neighbors:
                if neighbor.is_active:
                    self._observe(node_id, neighbor.id, dt, now)

    def _observe(self, a: int, b: int, dt: float, now: float) -> None:
        self._ensure_epoch(a, now)
        self._roll_windows(a, now)
        community = self._community_of(a)

        meet_dur = self._meet_dur.setdefault(a, {})
        meet_dur[b] = meet_dur.get(b, 0.0) + dt
        met = self._met.setdefault(a, set())
        if b not in met and meet_dur[b] >= self._t_meet_s:
            met.add(b)
            if b in community:
                self._met_in_c.setdefault(a, set()).add(b)

        contact_dur = self._contact_dur.setdefault(a, {})
        contact_dur[b] = contact_dur.get(b, 0.0) + dt
        familiar = self._familiar.setdefault(a, set())
        if b not in familiar and contact_dur[b] >= self._t_fam_s:
            familiar.add(b)
            if self._simple_detection:
                self._add_to_community(a, b)

        if self._simple_detection:
            self._social_exchange(a, b, now)

    def _social_exchange(self, a: int, b: int, now: float) -> None:
        self._ensure_epoch(b, now)
        community = self._community_of(a)
        peer_familiar = self._familiar.get(b)
        if b not in community and peer_familiar:
            if len(community & peer_familiar) / len(peer_familiar) >= self._lambda_add:
                self._add_to_community(a, b)
        if b not in community:
            return
        peer_community = self._community_of(b)
        newcomers = peer_community - community
        if not newcomers:
            return
        inter = len(peer_community) - len(newcomers)
        union = len(community) + len(newcomers)
        if inter < self._gamma_merge * union:
            return
        # MERGE_REQ: fill up to c_max, members already familiar to me first.
        familiar = self._familiar.get(a, set())
        room = self._c_max - len(community)
        for member in sorted(newcomers, key=lambda m: m not in familiar)[:max(room, 0)]:
            community.add(member)

    def _recently_seen(self, node_id: int, other_id: int, now: float) -> bool:
        t = self._last_seen.get(node_id, {}).get(other_id)
        return t is not None and (now - t) <= self._two_hop_freshness_s

    def _admits(self, contact: "BaseNode", dst: int) -> bool:
        if len(contact.buffer) < self._admission_threshold * contact.buffer_capacity:
            return True
        return dst in self._community_of(contact.id)

    def _is_stuck(self, message: Message, now: float) -> bool:
        return (
            message.routing_state[_TOKENS] == 1
            and now - message.routing_state[_LAST_PROGRESS] > self._t_stuck_s
        )

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if message.msg_id in self._delivered_ids:
            holder.buffer.pop(message.msg_id, None)
            return RoutingDecision.IGNORE

        self._now = now
        self._last_seen.setdefault(holder.id, {})[contact.id] = now
        self._last_seen.setdefault(contact.id, {})[holder.id] = now

        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE

        state = message.routing_state
        state.setdefault(_TOKENS, self._l_base)
        state.setdefault(_LAST_PROGRESS, message.creation_time)

        dst = message.dst_id
        self._ensure_epoch(holder.id, now)
        self._ensure_epoch(contact.id, now)
        if not self._admits(contact, dst):
            return RoutingDecision.IGNORE

        if self._two_hop_relay and self._recently_seen(contact.id, dst, now):
            return self._forward(state, "two_hop")

        holder_in = dst in self._community_of(holder.id)
        contact_in = dst in self._community_of(contact.id)
        if holder_in:
            if contact_in and self._ranks(contact.id, now)[1] > self._ranks(holder.id, now)[1] + self._delta_l:
                return self._forward(state, "bubble")
            return RoutingDecision.IGNORE
        if contact_in:
            return self._forward(state, "bubble")
        if self._ranks(contact.id, now)[0] > self._ranks(holder.id, now)[0] + self._delta_g:
            return self._forward(state, "rank")

        if (
            self._stuck_replication
            and not state.get(_STUCK_REPLICATED, False)
            and self._is_stuck(message, now)
            and contact.id not in self._community_of(holder.id)
        ):
            return self._forward(state, "stuck_replicate")
        return RoutingDecision.IGNORE

    @staticmethod
    def _forward(state: Dict, reason: str) -> RoutingDecision:
        state[_FORWARD_REASON] = reason
        return RoutingDecision.FORWARD

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        self._delivered_ids.add(message.msg_id)

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        reason = message.routing_state.pop(_FORWARD_REASON, "bubble")
        forwarded_copy.routing_state.pop(_FORWARD_REASON, None)
        tokens = message.routing_state.get(_TOKENS, 1)
        now = self._now
        forwarded_copy.routing_state[_LAST_PROGRESS] = now
        self.relays_by_node[holder.id] = self.relays_by_node.get(holder.id, 0) + 1

        if reason == "stuck_replicate":
            # Holder keeps its token: at most one diversification per copy,
            # so the total stays <= 2 * l_base.
            forwarded_copy.routing_state[_TOKENS] = 1
            forwarded_copy.routing_state[_STUCK_REPLICATED] = True
            message.routing_state[_STUCK_REPLICATED] = True
            self.stuck_replications += 1
            return

        if tokens <= 1:
            forwarded_copy.routing_state[_TOKENS] = 1
            holder.buffer.pop(message.msg_id, None)
            return

        contact_share = 1 if reason == "two_hop" else tokens // 2
        forwarded_copy.routing_state[_TOKENS] = contact_share
        message.routing_state[_TOKENS] = tokens - contact_share
        message.routing_state[_LAST_PROGRESS] = now

    def community_jaccard(self) -> float:
        scores = []
        for node_id, group in self._groups.items():
            community = self._community_of(node_id)
            scores.append(len(community & group) / len(community | group))
        return sum(scores) / len(scores) if scores else 0.0
