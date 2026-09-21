from __future__ import annotations
from typing import TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode


class SprayAndWaitRouting(RoutingAlgorithm):
    def __init__(self, initial_copies: int = 8) -> None:
        if initial_copies < 2:
            raise ValueError("initial_copies must be >= 2")
        self._initial_copies = initial_copies

    def _copies_left(self, message: Message) -> int:
        return message.routing_state.get("copies_left", self._initial_copies)

    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        # Wait phase: only direct delivery to the destination remains
        # possible (handled by the engine before decide() is ever called).
        if self._copies_left(message) <= 1:
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        n = self._copies_left(message)
        holder_share = n // 2
        contact_share = n - holder_share
        message.routing_state["copies_left"] = holder_share
        forwarded_copy.routing_state["copies_left"] = contact_share
