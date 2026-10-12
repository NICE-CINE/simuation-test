from __future__ import annotations
from typing import Callable, Dict, Tuple
from .band_fanout import BandFanoutRouting
from .base import RoutingAlgorithm
from .beacon_priority import BeaconPriorityRouting
from .bubble_f import BubbleFRouting
from .dasfv import DasfVRouting
from .eco_sf import EcoSfRouting
from .epidemic import EpidemicRouting
from .fresh_spray import FreshSprayRouting
from .geo_spray_focus import GeoSprayFocusRouting
from .gossip_a import GossipARouting
from .managed_flood import ManagedFloodRouting
from .prophet import ProphetRouting
from .spray_and_wait import SprayAndWaitRouting
from .tide import TideRouting
from .tide_g import TIDE_G2_KWARGS, TideGRouting

# The one registry main.py and every script build algorithms from, so the
# same --seed gives the same run whichever entry point launched it.
# Arguments: (seed, spray_initial_copies).
_FACTORIES: Dict[str, Callable[[int, int], RoutingAlgorithm]] = {
    "epidemic": lambda seed, copies: EpidemicRouting(),
    "spray_wait": lambda seed, copies: SprayAndWaitRouting(initial_copies=copies),
    "prophet": lambda seed, copies: ProphetRouting(),
    "beacon_priority": lambda seed, copies: BeaconPriorityRouting(),
    "dasfv": lambda seed, copies: DasfVRouting(),
    "gossip_a": lambda seed, copies: GossipARouting(seed=seed),
    "bubble_f": lambda seed, copies: BubbleFRouting(),
    "managed_flood": lambda seed, copies: ManagedFloodRouting(),
    "tide": lambda seed, copies: TideRouting(seed=seed),
    "tide_g": lambda seed, copies: TideGRouting(seed=seed),
    "tide_g2": lambda seed, copies: TideGRouting(seed=seed, **TIDE_G2_KWARGS),
    "fresh_spray": lambda seed, copies: FreshSprayRouting(),
    "geo_spray_focus": lambda seed, copies: GeoSprayFocusRouting(),
    "eco_sf": lambda seed, copies: EcoSfRouting(seed=seed),
    "band_fanout": lambda seed, copies: BandFanoutRouting(seed=seed),
}

ROUTING_NAMES: Tuple[str, ...] = tuple(_FACTORIES)


def build_routing(name: str, seed: int, spray_initial_copies: int = 8) -> RoutingAlgorithm:
    return _FACTORIES[name](seed, spray_initial_copies)
