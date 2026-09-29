from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class SimulationHistory:
    # Plain data container: no rendering logic here (see viz/replay.py),
    # kept dependency-free so simulation.py/network.py recording it doesn't
    # pull in anything beyond this file.
    area_width_m: float
    area_height_m: float
    tick_interval_s: float
    beacon_positions: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    # (time, {node_id: (x, y)}) per mobility tick, mobile nodes only.
    position_snapshots: List[Tuple[float, Dict[int, Tuple[float, float]]]] = field(default_factory=list)
    # {"time", "from", "to", "delivered"} per relay/delivery event.
    events: List[Dict[str, Any]] = field(default_factory=list)
