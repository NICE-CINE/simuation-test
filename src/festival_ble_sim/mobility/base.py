from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING
from ..config import AreaConfig
from ..models import Position

if TYPE_CHECKING:
    from ..nodes import BaseNode


class MobilityModel(ABC):
    @abstractmethod
    def initial_position(self, area: AreaConfig) -> Position:
        ...

    @abstractmethod
    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        # >>> POINT D'INJECTION : logique spatiale/mathematique perso
        # (attraction vers une scene, densite de foule, zones interdites...)
        ...

    def join_group(self, node: "BaseNode", members: List["BaseNode"]) -> Optional[Position]:
        # Called once friend groups are known, on every member of a group
        # (members sorted by id, node among them); a returned position is
        # where the member starts.
        return None
