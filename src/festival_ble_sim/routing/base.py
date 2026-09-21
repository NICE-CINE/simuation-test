from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING
from ..models import Message

if TYPE_CHECKING:
    from ..nodes import BaseNode


class RoutingDecision(Enum):
    FORWARD = auto()
    IGNORE = auto()


class RoutingAlgorithm(ABC):
    @abstractmethod
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        # >>> POINT D'INJECTION : tes propres algos de routage
        # (Spray & Wait, PRoPHET, scoring base sur les bornes...)
        ...

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        pass

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        # Called right after `forwarded_copy` has been created (independent
        # routing_state dict) and stored in `contact`'s buffer. Lets an
        # algorithm split per-copy state asymmetrically between the holder's
        # remaining copy and the newly forwarded one (e.g. Spray & Wait).
        pass
