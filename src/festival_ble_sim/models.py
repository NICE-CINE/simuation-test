from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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
    # Bluetooth Mesh network-layer TTL: decremented (here, compared against
    # accumulated hops) on every relay, independent of the time-based ttl_s
    # above. None = unlimited hops (this field's real-world default is
    # unbounded; TrafficConfig.message_ttl_hops is what actually caps it).
    ttl_hops: Optional[int] = None

    def is_expired(self, now: float) -> bool:
        return (now - self.creation_time) > self.ttl_s

    def hop_limit_reached(self) -> bool:
        return self.ttl_hops is not None and self.hops >= self.ttl_hops
