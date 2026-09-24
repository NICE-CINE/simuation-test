from __future__ import annotations
import math
from typing import Dict, Set
from .config import AreaConfig
from .mobility.base import MobilityModel
from .models import Message, Position


class BaseNode:
    def __init__(
        self,
        node_id: int,
        position: Position,
        radio_range_m: float,
        buffer_capacity: int,
        battery_mah: float,
    ) -> None:
        self.id = node_id
        self.position = position
        self.radio_range_m = radio_range_m
        self.buffer_capacity = buffer_capacity
        self.initial_battery_mah = battery_mah
        self.battery_mah = battery_mah
        self.is_active = True
        # Distinct from is_active=False, which also covers a churned-out/
        # not-yet-arrived node (see simulation._churn_process): only this
        # flag means "died from battery depletion", so the final report's
        # dead_node_count isn't inflated by ordinary churn departures.
        self.battery_depleted = False
        self.buffer: Dict[int, Message] = {}
        self.delivered_ids: Set[int] = set()
        self.buffer_evictions = 0
        self.is_beacon = False

    def has_message(self, msg_id: int) -> bool:
        return msg_id in self.buffer or msg_id in self.delivered_ids

    def store_message(self, message: Message) -> None:
        if message.msg_id in self.buffer:
            return
        if len(self.buffer) >= self.buffer_capacity:
            oldest_id = next(iter(self.buffer))
            del self.buffer[oldest_id]
            self.buffer_evictions += 1
        self.buffer[message.msg_id] = message

    def mark_delivered(self, msg_id: int) -> None:
        self.delivered_ids.add(msg_id)
        self.buffer.pop(msg_id, None)

    def consume_energy(self, mah: float) -> None:
        if self.battery_mah == math.inf:
            return
        self.battery_mah = max(0.0, self.battery_mah - mah)
        if self.battery_mah <= 0.0:
            self.is_active = False
            self.battery_depleted = True

    @property
    def energy_consumed_mah(self) -> float:
        if self.initial_battery_mah == math.inf:
            return 0.0
        return self.initial_battery_mah - self.battery_mah


class MobileNode(BaseNode):
    def __init__(
        self,
        node_id: int,
        mobility: MobilityModel,
        radio_range_m: float,
        buffer_capacity: int,
        battery_mah: float,
        area: AreaConfig,
    ) -> None:
        position = mobility.initial_position(area)
        super().__init__(node_id, position, radio_range_m, buffer_capacity, battery_mah)
        self.mobility = mobility

    def move(self, dt: float, area: AreaConfig) -> None:
        self.position = self.mobility.step(self.position, dt, area)


class BeaconNode(BaseNode):
    def __init__(
        self,
        node_id: int,
        position: Position,
        radio_range_m: float,
        buffer_capacity: int,
        unlimited_power: bool = True,
        battery_mah: float = 0.0,
    ) -> None:
        initial_battery = math.inf if unlimited_power else battery_mah
        super().__init__(node_id, position, radio_range_m, buffer_capacity, initial_battery)
        self.is_beacon = True
