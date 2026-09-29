from __future__ import annotations
from abc import ABC, abstractmethod
from ..config import AreaConfig
from ..models import Position


class MobilityModel(ABC):
    @abstractmethod
    def initial_position(self, area: AreaConfig) -> Position:
        ...

    @abstractmethod
    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        # >>> POINT D'INJECTION : logique spatiale/mathematique perso
        # (attraction vers une scene, densite de foule, zones interdites...)
        ...
