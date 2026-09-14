from __future__ import annotations
import math
from typing import List
from .config import AreaConfig, BeaconConfig
from .models import Position


def place_beacons(area: AreaConfig, beacons: BeaconConfig) -> List[Position]:
    if beacons.count <= 0:
        return []
    if beacons.placement == "manual":
        if not beacons.manual_positions:
            raise ValueError("beacons.manual_positions must be set when placement='manual'")
        return [Position(x, y) for x, y in beacons.manual_positions]
    if beacons.placement == "grid":
        return _place_grid(area, beacons.count)
    raise ValueError(f"unknown beacon placement mode: {beacons.placement!r}")


def _place_grid(area: AreaConfig, count: int) -> List[Position]:
    # >>> POINT D'INJECTION : remplace cette grille reguliere par un
    # placement strategique (entrees, scenes, points de forte densite...)
    cols = max(1, math.floor(math.sqrt(count)))
    rows = max(1, math.ceil(count / cols))
    dx = area.width_m / (cols + 1)
    dy = area.height_m / (rows + 1)
    positions: List[Position] = []
    for row in range(rows):
        for col in range(cols):
            if len(positions) >= count:
                return positions
            positions.append(Position(x=(col + 1) * dx, y=(row + 1) * dy))
    return positions
