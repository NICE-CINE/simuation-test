from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Position:
    x: float
    y: float

    def distance_to(self, other: "Position") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class Message:
    msg_id: int
    src_id: int
    dst_id: int
    size_bytes: int
    creation_time: float
    ttl_s: float
    hops: int = 0
    routing_state: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: float) -> bool:
        return (now - self.creation_time) > self.ttl_s
