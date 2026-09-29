from __future__ import annotations
from typing import Dict, Tuple, TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_Pair = Tuple[int, int]


class ProphetRouting(RoutingAlgorithm):
    # Single shared instance per run (see simulation.py), so the delivery
    # predictability table can safely live as instance state here instead
    # of on BaseNode.
    def __init__(
        self,
        p_encounter_init: float = 0.75,
        gamma: float = 0.999,
        beta: float = 0.25,
        forwarding_threshold: float = 0.0,
        enable_transitivity: bool = False,
    ) -> None:
        self._p_encounter_init = p_encounter_init
        self._gamma = gamma
        self._beta = beta
        self._forwarding_threshold = forwarding_threshold
        self._enable_transitivity = enable_transitivity
        self._predictability: Dict[_Pair, float] = {}
        self._last_seen: Dict[_Pair, float] = {}

    def _decayed(self, pair: _Pair, now: float) -> float:
        p = self._predictability.get(pair, 0.0)
        if p == 0.0:
            return 0.0
        last = self._last_seen.get(pair, now)
        return p * (self._gamma ** max(0.0, now - last))

    def _touch_encounter(self, a: int, b: int, now: float) -> None:
        if self._last_seen.get((a, b)) == now:
            return  # already updated for this (holder, contact) pair this tick
        for pair in ((a, b), (b, a)):
            p_old = self._decayed(pair, now)
            self._predictability[pair] = p_old + (1 - p_old) * self._p_encounter_init
            self._last_seen[pair] = now
        if self._enable_transitivity:
            self._apply_transitivity(a, b, now)

    def _apply_transitivity(self, a: int, b: int, now: float) -> None:
        p_ab = self._decayed((a, b), now)
        for (src, dst) in list(self._predictability.keys()):
            if src != b or dst in (a, b):
                continue
            p_bc = self._decayed((b, dst), now)
            pair = (a, dst)
            p_old = self._decayed(pair, now)
            self._predictability[pair] = p_old + (1 - p_old) * p_ab * p_bc * self._beta
            self._last_seen[pair] = now
        for (src, dst) in list(self._predictability.keys()):
            if src != a or dst in (a, b):
                continue
            p_ac = self._decayed((a, dst), now)
            pair = (b, dst)
            p_old = self._decayed(pair, now)
            self._predictability[pair] = p_old + (1 - p_old) * p_ab * p_ac * self._beta
            self._last_seen[pair] = now

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        self._touch_encounter(holder.id, contact.id, now)
        p_contact = self._decayed((contact.id, message.dst_id), now)
        p_holder = self._decayed((holder.id, message.dst_id), now)
        if (p_contact - p_holder) > self._forwarding_threshold:
            return RoutingDecision.FORWARD
        return RoutingDecision.IGNORE
