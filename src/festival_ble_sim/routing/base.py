from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Dict, List, Optional, TYPE_CHECKING
from ..models import Message

if TYPE_CHECKING:
    from ..config import BleConfig
    from ..energy import EnergyModel
    from ..nodes import BaseNode


def per_destination_table_bytes(peer: "BaseNode", entry_bytes: int = 8) -> int:
    # The usual table answer: one entry (id + value) per destination the
    # peer carries messages for, e.g. when this node last met it.
    return entry_bytes * len({m.dst_id for m in peer.buffer.values()})


class RoutingDecision(Enum):
    FORWARD = auto()
    IGNORE = auto()


class RoutingAlgorithm(ABC):
    # True: the engine spreads delivery acks over connections (the
    # destination mints one, each side acks the ids the other advertises, a
    # node that learns one drops its copy), billing ack_size_bytes each.
    # Never a global "delivered" set: a node only knows what reached it.
    uses_delivery_acks = False
    ack_size_bytes = 8
    # True: data goes out connectionless (Bluetooth Mesh's advertising
    # bearer): no connection setup or slots, one broadcast per message to
    # the neighbors decide() picks, receptions lost rather than resent.
    advertising_bearer = False

    @abstractmethod
    def decide(self, message: Message, holder: "BaseNode", contact: "BaseNode", now: float) -> RoutingDecision:
        # FORWARD is only an intention: the engine may still drop the copy
        # (link budget, packet loss) without calling on_forward. Anything
        # that assumes the copy arrived (token splits, "reached X" flags,
        # dropping the holder's copy) belongs in on_forward/on_delivered.
        # >>> POINT D'INJECTION : tes propres algos de routage
        # (Spray & Wait, PRoPHET, scoring base sur les bornes...)
        ...

    def on_simulation_start(self, nodes: Dict[int, "BaseNode"]) -> None:
        pass

    def on_energy_model(self, energy_model: "EnergyModel") -> None:
        # The run's own costs, for algorithms that bill extra traffic (acks,
        # beacons) themselves instead of letting the engine charge it.
        pass

    def on_ble_config(self, ble_config: "BleConfig") -> None:
        # The run's radio settings (airtime per tick), for algorithms that
        # size their own control traffic.
        pass

    def on_tick(self, now: float, neighbors_by_node: Dict[int, List["BaseNode"]]) -> None:
        # Every in-range pair this tick, whether or not anything is sent:
        # decide() alone only sees contacts where the holder has a message,
        # which undersamples contact-history-driven algorithms.
        pass

    def control_broadcasts(self, now: float) -> Dict[int, int]:
        # {node_id: bytes} each node broadcasts this tick (announces, distance
        # vectors), called right after on_tick. The engine sends each one at
        # its node's turn, before that node's data, with the same airtime
        # budget and tx/rx energy as data, on the advertising channels'
        # load, lost rather than resent (no connection).
        return {}

    def on_control_received(self, now: float, received: Dict[int, List[int]], sent: List[int]) -> None:
        # {receiver_id: [sender_ids]} whose control_broadcasts got through,
        # and the senders whose broadcast actually went out (not backed off,
        # within airtime), once per tick after all data has been sent.
        pass

    def on_delivered(self, message: Message, holder: "BaseNode") -> None:
        pass

    def connection_table_bytes(self, node: "BaseNode", peer: "BaseNode") -> int:
        # Bytes `node` sends `peer` once their connection is up for the
        # algorithm's own state (encounter times, predictabilities,
        # utilities) that decide() then reads about the peer.
        return 0

    def on_forward(self, message: Message, holder: "BaseNode", contact: "BaseNode", forwarded_copy: Message) -> None:
        # Called right after `forwarded_copy` has been created (independent
        # routing_state dict) and stored in `contact`'s buffer. Lets an
        # algorithm split per-copy state asymmetrically between the holder's
        # remaining copy and the newly forwarded one (e.g. Spray & Wait).
        pass

    def select_links(self, sender: "BaseNode", neighbors: List["BaseNode"], max_links: int) -> List["BaseNode"]:
        # Which neighbors get the sender's limited concurrent links
        # (BleConfig.max_concurrent_links). Real BLE stacks only sustain a
        # handful of simultaneous GATT connections. By default the
        # destinations of what the sender carries come first (a phone
        # recognizes them in their advertisements; in a packed crowd the
        # destination is otherwise never among the few nearest), then the
        # closest contacts (stronger link/RSSI proxy). Squared distance sorts
        # identically to real distance without paying for the sqrt.
        dst_ids = {m.dst_id for m in sender.buffer.values()}
        ranked = sorted(
            neighbors, key=lambda n: (n.id not in dst_ids, sender.position.distance_squared_to(n.position))
        )
        return ranked[:max_links]

    def choose_eviction(self, node: "BaseNode", now: float) -> Optional[int]:
        # Called when a forwarded copy lands in a full buffer. None (or an id
        # not in the buffer) keeps BaseNode's default FIFO eviction.
        return None
