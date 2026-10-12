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
            return RoutingDecision.FORWARD
        if message.routing_state.get(_REACHED_BEACON, False):
            # Infrastructure (backhaul + future beacon<->phone contacts)
            # will handle wide distribution; stop epidemic phone-to-phone
            # flooding once the message is infrastructure-carried.
            return RoutingDecision.IGNORE
        return RoutingDecision.FORWARD

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        # Here, not in decide(): the engine can still drop the copy after a
        # FORWARD (link budget, packet loss), and an unsent copy must not
        # stop the phone-to-phone flooding.
        if getattr(contact, "is_beacon", False):
            message.routing_state[_REACHED_BEACON] = True
            forwarded_copy.routing_state[_REACHED_BEACON] = True
