from __future__ import annotations
import math
import random
from typing import Optional
from ..config import AreaConfig, MobilityConfig
from ..models import Position
from .base import MobilityModel


def move_towards(current: Position, target: Position, speed_mps: float, dt: float) -> Position:
    dx = target.x - current.x
    dy = target.y - current.y
    dist = math.hypot(dx, dy)
    if dist == 0:
        return Position(current.x, current.y)
    step_len = min(speed_mps * dt, dist)
    return Position(current.x + dx / dist * step_len, current.y + dy / dist * step_len)


class RandomWaypointMobility(MobilityModel):
    def __init__(self, config: MobilityConfig, rng: Optional[random.Random] = None) -> None:
        self._config = config
        self._rng = rng or random.Random()
        self._target: Optional[Position] = None
        self._speed_mps: float = 0.0
        self._pause_until: float = 0.0
        self._elapsed_s: float = 0.0

    def initial_position(self, area: AreaConfig) -> Position:
        return Position(
            x=self._rng.uniform(0.0, area.width_m),
            y=self._rng.uniform(0.0, area.height_m),
        )

    def _pick_new_target(self, area: AreaConfig) -> None:
        self._target = Position(
            x=self._rng.uniform(0.0, area.width_m),
            y=self._rng.uniform(0.0, area.height_m),
        )
        self._speed_mps = self._rng.uniform(self._config.speed_min_mps, self._config.speed_max_mps)

    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        self._elapsed_s += dt
        if self._target is None:
            self._pick_new_target(area)

        if self._elapsed_s < self._pause_until:
            return current

        if current.distance_to(self._target) < 1.0:
            if self._rng.random() < self._config.pause_probability:
                lo, hi = self._config.pause_duration_range_s
                self._pause_until = self._elapsed_s + self._rng.uniform(lo, hi)
                return current
            self._pick_new_target(area)

        return move_towards(current, self._target, self._speed_mps, dt)
