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
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode") -> RoutingDecision:
        # >>> POINT D'INJECTION : tes propres algos de routage
        # (Spray & Wait, PRoPHET, scoring base sur les bornes...)
        ...

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        pass
