from __future__ import annotations
import math
import random
from typing import List, Optional, TYPE_CHECKING
from ..config import AreaConfig, MobilityConfig
from ..models import Position
from .base import MobilityModel
from .poi import PoiMobility
from .random_waypoint import move_towards

if TYPE_CHECKING:
    from ..nodes import BaseNode

_WITH, _AWAY, _RETURN, _SEARCH = "with", "away", "return", "search"


class _Team:
    def __init__(self, nodes: List["BaseNode"]) -> None:
        self.nodes = nodes
        self.leader: Optional["BaseNode"] = None

    def current_leader(self) -> Optional["BaseNode"]:
        # Sticky: a member arriving late doesn't take over, the first one
        # present and with the group leads until they leave the site.
        if self.leader is None or not self.leader.on_site or self.leader.mobility._state != _WITH:
            self.leader = next((n for n in self.nodes if n.on_site and n.mobility._state == _WITH), None)
        return self.leader


class GroupMobility(MobilityModel):
    # Friends move together (reference point group mobility): the first
    # member present on site leads with PoiMobility, the others keep a fixed
    # offset around it. A member sometimes leaves on its own, for a short
    # trip (bar, toilets) or a long one (another stage). Nobody can call or
    # text (the cellular network is saturated), so before leaving they agree
    # on a rendezvous: here, at the end of the trip. The leader goes back
    # there and waits up to rendezvous_max_wait_s; a member who misses it,
    # or arrives on site after the group, searches the POIs until it sees
    # the group. Deliberately independent of the simulated mesh, so every
    # algorithm sees the same movements at a seed. Without a group
    # (friendless, or binding never happens) it is PoiMobility.
    def __init__(self, config: MobilityConfig, rng: Optional[random.Random] = None) -> None:
        self._config = config
        self._group = config.group
        self._rng = rng or random.Random()
        self._solo = PoiMobility(config, rng=self._rng)
        self._elapsed_s = 0.0
        self._node: Optional["BaseNode"] = None
        self._team: Optional[_Team] = None
        self._started = False
        self._offset = (0.0, 0.0)
        self._state = _WITH
        self._trip: Optional[PoiMobility] = None
        self._meeting: Optional[Position] = None
        self._meeting_at = 0.0
        self._search_target: Optional[Position] = None
        self._speed_mps = self._rng.uniform(config.speed_min_mps, config.speed_max_mps)

    def initial_position(self, area: AreaConfig) -> Position:
        return self._solo.initial_position(area)

    def join_group(self, node: "BaseNode", members: List["BaseNode"]) -> Optional[Position]:
        owner = members[0].mobility
        if owner._team is None:
            owner._team = _Team(members)
        self._team = owner._team
        self._node = node
        if node is members[0]:
            return None
        angle = self._rng.uniform(0.0, 2.0 * math.pi)
        radius = self._group.radius_m * math.sqrt(self._rng.random())
        self._offset = (radius * math.cos(angle), radius * math.sin(angle))
        return self._slot(members[0])

    @property
    def is_with_group(self) -> bool:
        return self._team is None or self._state == _WITH

    def lost_peers(self) -> List["BaseNode"]:
        # Who this person writes to about a missed rendezvous: a lost member
        # (past its meeting time, or arrived late) writes to the group, the
        # leader writes to the lost members on the group's behalf.
        if self._team is None:
            return []
        leader = self._team.current_leader()
        if self._state in (_RETURN, _SEARCH):
            return [n for n in self._team.nodes if n is not self._node and n.on_site and n.mobility._state == _WITH]
        if leader is self._node:
            return [n for n in self._team.nodes if n.on_site and n.mobility._state in (_RETURN, _SEARCH)]
        return []

    def _slot(self, leader: "BaseNode") -> Position:
        p = leader.position
        return Position(p.x + self._offset[0], p.y + self._offset[1])

    def _sees(self, current: Position, leader: "BaseNode") -> bool:
        reach = self._group.visual_range_m
        return current.distance_squared_to(leader.position) <= reach * reach

    def step(self, current: Position, dt: float, area: AreaConfig) -> Position:
        self._elapsed_s += dt
        if self._team is None:
            return self._solo.step(current, dt, area)
        leader = self._team.current_leader()
        if leader is self._node:
            return self._lead(current, dt, area)
        if not self._started:
            self._started = True
            # On site after the group: it doesn't know where they are.
            if leader is not None and leader.mobility._elapsed_s > self._elapsed_s:
                self._state = _SEARCH
        if self._state == _WITH:
            trip = self._maybe_leave(leader, dt)
            if trip is None:
                return move_towards(current, self._slot(leader), self._config.speed_max_mps, dt)
            self._state, self._trip = _AWAY, trip
            self._trip.step(current, dt, area)
            return current
        if self._state == _AWAY:
            if self._elapsed_s < self._meeting_at:
                return self._trip.step(current, dt, area)
            self._state = _RETURN
        if leader is None or self._sees(current, leader):
            # Nobody left with the group: this member is the group now.
            self._state, self._trip, self._search_target = _WITH, None, None
            return current if leader is None else move_towards(current, self._slot(leader), self._config.speed_max_mps, dt)
        if self._state == _RETURN:
            if self._elapsed_s <= self._meeting_at + self._group.rendezvous_max_wait_s:
                return move_towards(current, self._meeting, self._speed_mps, dt)
            self._state = _SEARCH
        if self._search_target is None or current.distance_to(self._search_target) < 1.0:
            self._search_target = self._solo.crowd_position(area)
        return move_towards(current, self._search_target, self._speed_mps, dt)

    def _maybe_leave(self, leader: "BaseNode", dt: float) -> Optional[PoiMobility]:
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
        self._meeting = leader.position
        self._meeting_at = self._elapsed_s + duration
        return PoiMobility(self._config, rng=self._rng)

    def _lead(self, current: Position, dt: float, area: AreaConfig) -> Position:
        # A member heading back to its rendezvous: go there and wait (its
        # RETURN state lasts rendezvous_max_wait_s); otherwise behave like
        # any POI visitor.
        for node in self._team.nodes:
            model = node.mobility
            if node is not self._node and node.on_site and model._state == _RETURN:
                return move_towards(current, model._meeting, self._config.speed_max_mps, dt)
        return self._solo.step(current, dt, area)
