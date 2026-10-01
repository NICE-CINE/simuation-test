from __future__ import annotations
import random
from typing import Optional, Tuple
from ..config import AreaConfig, MobilityConfig, PointOfInterest
from ..models import Position
from .base import MobilityModel
from .random_waypoint import move_towards


class PoiMobility(MobilityModel):
    def __init__(self, config: MobilityConfig, rng: Optional[random.Random] = None) -> None:
        if not config.points_of_interest:
            raise ValueError("PoiMobility requires at least one point of interest in MobilityConfig")
        self._weights = [max(0.0, poi.weight) for poi in config.points_of_interest]
        if sum(self._weights) <= 0:
            raise ValueError("at least one point of interest must have a positive weight")
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
        poi = self._rng.choices(self._config.points_of_interest, weights=self._weights, k=1)[0]
        offset_x = self._rng.uniform(-poi.radius_m, poi.radius_m)
        offset_y = self._rng.uniform(-poi.radius_m, poi.radius_m)
        self._target = Position(
            x=min(max(poi.x + offset_x, 0.0), area.width_m),
            y=min(max(poi.y + offset_y, 0.0), area.height_m),
        )
        self._speed_mps = self._rng.uniform(self._config.speed_min_mps, self._config.speed_max_mps)

    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        self._elapsed_s += dt
        if self._target is None:
            self._pick_new_target(area)
            return current

        if self._elapsed_s < self._pause_until:
            return current

        if self._pause_until > 0.0:
            self._pause_until = 0.0
            self._pick_new_target(area)
            return current

        if current.distance_to(self._target) < 1.0:
            if self._rng.random() < self._config.pause_probability:
                lo, hi = self._config.pause_duration_range_s
                self._pause_until = self._elapsed_s + self._rng.uniform(lo, hi)
                return current
            self._pick_new_target(area)

        return move_towards(current, self._target, self._speed_mps, dt)


def default_festival_pois(area: AreaConfig) -> Tuple[PointOfInterest, ...]:
    w, h = area.width_m, area.height_m
    r = min(w, h)
    return (
        PointOfInterest(x=0.25 * w, y=0.75 * h, radius_m=0.15 * r, weight=4.0),  # main stage
        PointOfInterest(x=0.80 * w, y=0.70 * h, radius_m=0.10 * r, weight=2.0),  # second stage
        PointOfInterest(x=0.55 * w, y=0.35 * h, radius_m=0.12 * r, weight=3.0),  # bars / food court
        PointOfInterest(x=0.50 * w, y=0.05 * h, radius_m=0.08 * r, weight=1.0),  # entrance / toilets
    )
