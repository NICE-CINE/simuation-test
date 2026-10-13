from __future__ import annotations
from array import array
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Set, Tuple

_DELIVERED = 1
_BACKHAUL = 2
_NO_MESSAGE = -1


class CompactEventLog:
    # Columnar stand-in for a list of event dicts: a flooding algorithm logs
    # tens of millions of relays, which as dicts costs ~10 GB of RAM. Iterating
    # rebuilds the exact dicts network.py appended.
    def __init__(self) -> None:
        self._time = array("d")
        self._from = array("i")
        self._to = array("i")
        self._msg = array("i")
        self._hops = array("h")
        self._flags = array("b")
        self._messages: Dict[int, Tuple[int, int, float]] = {}
        self._delivered: Set[int] = set()

    @property
    def messages(self) -> Dict[int, Tuple[int, int, float]]:
        return self._messages

    @property
    def delivered_messages(self) -> Set[int]:
        return self._delivered

    def rows(self) -> Iterator[Tuple[float, int, int, int, int, int]]:
        # (time, from, to, flags, hops, msg) without building a dict per event.
        return zip(self._time, self._from, self._to, self._flags, self._hops, self._msg)

    def append(self, event: Dict[str, Any]) -> None:
        msg = event.get("msg", _NO_MESSAGE)
        if msg != _NO_MESSAGE and msg not in self._messages:
            self._messages[msg] = (event["src"], event["dst"], event["created"])
        self._time.append(event["time"])
        self._from.append(event["from"])
        self._to.append(event["to"])
        self._msg.append(msg)
        self._hops.append(event.get("hops", 0))
        self._flags.append((_DELIVERED if event["delivered"] else 0) | (_BACKHAUL if event.get("backhaul") else 0))
        if event["delivered"] and msg != _NO_MESSAGE:
            self._delivered.add(msg)

    def __len__(self) -> int:
        return len(self._time)

    def __getitem__(self, index: int) -> Dict[str, Any]:
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        flags = self._flags[index]
        event: Dict[str, Any] = {
            "time": self._time[index], "from": self._from[index], "to": self._to[index],
            "delivered": bool(flags & _DELIVERED),
        }
        msg = self._msg[index]
        if msg != _NO_MESSAGE:
            src, dst, created = self._messages[msg]
            event.update(msg=msg, hops=self._hops[index], src=src, dst=dst, created=created)
        if flags & _BACKHAUL:
            event["backhaul"] = True
        return event

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        for index in range(len(self)):
            yield self[index]


@dataclass
class SimulationHistory:
    # Plain data container: no rendering logic here (see viz/replay.py),
    # kept dependency-free so simulation.py/network.py recording it doesn't
    # pull in anything beyond this file.
    area_width_m: float
    area_height_m: float
    tick_interval_s: float
    # 1 = one snapshot per mobility tick; N keeps one tick out of N (the first included).
    snapshot_every_ticks: int = 1
    beacon_positions: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    # (time, {node_id: (x, y)}) per recorded tick, mobile nodes only.
    position_snapshots: List[Tuple[float, Dict[int, Tuple[float, float]]]] = field(default_factory=list)
    # {"time", "from", "to", "delivered"} per relay/delivery event.
    events: Any = field(default_factory=CompactEventLog)
