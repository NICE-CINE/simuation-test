from __future__ import annotations
import math
import random
from typing import List, Optional, Tuple, TYPE_CHECKING
from ..config import AreaConfig, MobilityConfig
from ..models import Position
from .base import MobilityModel
from .poi import PoiMobility
from .random_waypoint import move_towards

if TYPE_CHECKING:
    from ..nodes import BaseNode

_WITH, _AWAY, _RETURN, _SEARCH = "with", "away", "return", "search"


class GroupMobility(MobilityModel):
    # Friends move together (reference point group mobility): the group's
    # lowest id leads with PoiMobility, the others keep a fixed offset
    # around it. A member sometimes leaves on its own, for a short trip (bar,
    # toilets) or a long one (another stage). Nobody can call or text (the
    # cellular network is saturated), so before leaving they agree on a
    # rendezvous: here, at the end of the trip. The leader goes back there
    # and waits up to rendezvous_max_wait_s; a member who misses it searches
    # the POIs until it sees the group. Deliberately independent of the
    # simulated mesh, so every algorithm sees the same movements at a seed.
    # Without a group (friendless, or binding never happens) it is PoiMobility.
    def __init__(self, config: MobilityConfig, rng: Optional[random.Random] = None) -> None:
        self._config = config
        self._group = config.group
        self._rng = rng or random.Random()
        self._solo = PoiMobility(config, rng=self._rng)
        self._elapsed_s = 0.0
        self._leader: Optional["BaseNode"] = None
        self._offset = (0.0, 0.0)
        self._state = _WITH
        self._trip: Optional[PoiMobility] = None
        self._meeting: Optional[Position] = None
        self._meeting_at = 0.0
        self._search_target: Optional[Position] = None
        self._speed_mps = self._rng.uniform(config.speed_min_mps, config.speed_max_mps)
        # Leader side: (time, place, member) rendezvous still to keep.
        self._rendezvous: List[Tuple[float, Position, "GroupMobility"]] = []

    def initial_position(self, area: AreaConfig) -> Position:
        return self._solo.initial_position(area)

    def join_group(self, leader: "BaseNode") -> Optional[Position]:
        angle = self._rng.uniform(0.0, 2.0 * math.pi)
        radius = self._group.radius_m * math.sqrt(self._rng.random())
        self._offset = (radius * math.cos(angle), radius * math.sin(angle))
        self._leader = leader
        return self._slot()

    @property
    def is_with_group(self) -> bool:
        return self._leader is None or self._state == _WITH

    def _slot(self) -> Position:
        p = self._leader.position
        return Position(p.x + self._offset[0], p.y + self._offset[1])

    def _sees_group(self, current: Position) -> bool:
        reach = self._group.visual_range_m
        return current.distance_squared_to(self._leader.position) <= reach * reach

    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        self._elapsed_s += dt
        if self._leader is None:
            return self._lead(current, dt, area)
        if self._state == _WITH:
            trip = self._maybe_leave(dt)
            if trip is None:
                return move_towards(current, self._slot(), self._config.speed_max_mps, dt)
            self._state, self._trip = _AWAY, trip
            self._trip.step(current, dt, area)
            return current
        if self._state == _AWAY:
            if self._elapsed_s < self._meeting_at:
                return self._trip.step(current, dt, area)
            self._state = _RETURN
        if self._sees_group(current):
            self._state, self._trip, self._search_target = _WITH, None, None
            return move_towards(current, self._slot(), self._config.speed_max_mps, dt)
        if self._state == _RETURN:
            if self._elapsed_s <= self._meeting_at + self._group.rendezvous_max_wait_s:
                return move_towards(current, self._meeting, self._speed_mps, dt)
            self._state = _SEARCH
        if self._search_target is None or current.distance_to(self._search_target) < 1.0:
            self._search_target = self._solo.crowd_position(area)
        return move_towards(current, self._search_target, self._speed_mps, dt)

    def _maybe_leave(self, dt: float) -> Optional[PoiMobility]:
        g = self._group
        draw = self._rng.random()
        short_p = g.short_trips_per_hour * dt / 3600.0
        long_p = g.long_trips_per_hour * dt / 3600.0
        if draw < short_p:
            duration = self._rng.uniform(*g.short_trip_s)
        elif draw < short_p + long_p:
            duration = self._rng.uniform(*g.long_trip_s)
        else:
            return None
        # "On se retrouve ici" at the end of the trip.
        self._meeting = self._leader.position
        self._meeting_at = self._elapsed_s + duration
        leader_model = getattr(self._leader, "mobility", None)
        if isinstance(leader_model, GroupMobility):
            leader_model._rendezvous.append((self._meeting_at, self._meeting, self))
        return PoiMobility(self._config, rng=self._rng)

    def _lead(self, current: Position, dt: float, area: AreaConfig) -> Position:
        # Keep the earliest rendezvous that is due and not yet over: go there
        # and wait; until then (or after) behave like any POI visitor.
        wait = self._group.rendezvous_max_wait_s
        self._rendezvous = [
            r for r in self._rendezvous
            if self._elapsed_s <= r[0] + wait and not r[2].is_with_group
        ]
        due = [r for r in self._rendezvous if r[0] <= self._elapsed_s]
        if not due:
            return self._solo.step(current, dt, area)
        _, place, _ = min(due, key=lambda r: r[0])
        return move_towards(current, place, self._config.speed_max_mps, dt)
