from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Dict, List, Optional, TYPE_CHECKING
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

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        pass

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        # Every in-range pair this tick, whether or not anything is sent:
        # decide() alone only sees contacts where the holder has a message,
        # which undersamples contact-history-driven algorithms.
        pass

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        pass

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        # Called right after `forwarded_copy` has been created (independent
        # routing_state dict) and stored in `contact`'s buffer. Lets an
        # algorithm split per-copy state asymmetrically between the holder's
        # remaining copy and the newly forwarded one (e.g. Spray & Wait).
        pass

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        # Called when a forwarded copy lands in a full buffer. None (or an id
        # not in the buffer) keeps BaseNode's default FIFO eviction.
        return None
