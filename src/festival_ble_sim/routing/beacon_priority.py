from __future__ import annotations
from typing import TYPE_CHECKING
from ..models import Message
from .base import RoutingAlgorithm, RoutingDecision

if TYPE_CHECKING:
    from ..nodes import BaseNode

_REACHED_BEACON = "reached_beacon"


class BeaconPriorityRouting(RoutingAlgorithm):
    # Duck-types on `is_beacon` (set on BaseNode/BeaconNode in nodes.py)
    # rather than isinstance(contact, BeaconNode), so this package keeps its
    # zero-runtime-coupling-to-nodes.py convention.
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        if contact.has_message(message.msg_id):
            return RoutingDecision.IGNORE
        if getattr(contact, "is_beacon", False):
            # Mutating holder's own message here is safe: network.py copies
            # routing_state into the forwarded copy right after this call
            # returns FORWARD, so the flag propagates to both sides.
            message.routing_state[_REACHED_BEACON] = True
            return RoutingDecision.FORWARD
        if message.routing_state.get(_REACHED_BEACON, False):
            # Infrastructure (backhaul + future beacon<->phone contacts)
            # will handle wide distribution; stop epidemic phone-to-phone
            # flooding once the message is infrastructure-carried.
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD
