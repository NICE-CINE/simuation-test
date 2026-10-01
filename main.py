from __future__ import annotations
import argparse
import random
from typing import Callable, Dict, List, Optional, Tuple
from festival_ble_sim.archive import DEFAULT_ARCHIVE_DIR, archive_stem, write_params
from festival_ble_sim.config import (
    AreaConfig,
    BeaconConfig,
    ChurnConfig,
    MobilityConfig,
    PointOfInterest,
    SimulationConfig,
)
from festival_ble_sim.metrics import format_report
from festival_ble_sim.mobility.base import MobilityModel
from festival_ble_sim.mobility.poi import PoiMobility
from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility
from festival_ble_sim.routing.base import RoutingAlgorithm
from festival_ble_sim.routing.beacon_priority import BeaconPriorityRouting
from festival_ble_sim.routing.bubble_f import BubbleFRouting
from festival_ble_sim.routing.dasfv import DasfVRouting
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.routing.gossip_a import GossipARouting
from festival_ble_sim.routing.managed_flood import ManagedFloodRouting
from festival_ble_sim.routing.prophet import ProphetRouting
from festival_ble_sim.routing.spray_and_wait import SprayAndWaitRouting
from festival_ble_sim.routing.tide import TideRouting
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.viz.history import SimulationHistory
from festival_ble_sim.viz.replay import render_replay_html

ROUTING_FACTORIES: Dict[str, Callable[[argparse.Namespace], RoutingAlgorithm]] = {
    "epidemic": lambda args: EpidemicRouting(),
    "spray_wait": lambda args: SprayAndWaitRouting(initial_copies=args.spray_initial_copies),
    "prophet": lambda args: ProphetRouting(),
    "beacon_priority": lambda args: BeaconPriorityRouting(),
    "dasfv": lambda args: DasfVRouting(),
    "gossip_a": lambda args: GossipARouting(seed=args.seed),
    "bubble_f": lambda args: BubbleFRouting(seed=args.seed),
    "managed_flood": lambda args: ManagedFloodRouting(),
    "tide": lambda args: TideRouting(seed=args.seed),
}

# "poi" has no CLI knobs of its own: build_config() points it at a default
# festival layout (see _default_festival_pois) since the mobility_factory
# signature only takes an RNG, not a config.
MOBILITY_FACTORIES: Dict[str, Callable[[SimulationConfig], Callable[[random.Random], MobilityModel]]] = {
    "random_waypoint": lambda config: (lambda rng: RandomWaypointMobility(config.mobility, rng=rng)),
    "poi": lambda config: (lambda rng: PoiMobility(config.mobility, rng=rng)),
}


def _default_festival_pois(area: AreaConfig) -> Tuple[PointOfInterest, ...]:
    w, h = area.width_m, area.height_m
    r = min(w, h)
    return (
        PointOfInterest(x=0.25 * w, y=0.75 * h, radius_m=0.15 * r, weight=4.0),  # main stage
        PointOfInterest(x=0.80 * w, y=0.70 * h, radius_m=0.10 * r, weight=2.0),  # second stage
        PointOfInterest(x=0.55 * w, y=0.35 * h, radius_m=0.12 * r, weight=3.0),  # bars / food court
        PointOfInterest(x=0.50 * w, y=0.05 * h, radius_m=0.08 * r, weight=1.0),  # entrance / toilets
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulateur de messagerie BLE mesh en festival")
    parser.add_argument("--routing", choices=sorted(ROUTING_FACTORIES), default="epidemic")
    parser.add_argument("--mobility", choices=sorted(MOBILITY_FACTORIES), default="random_waypoint")
    parser.add_argument("--beacons", type=int, default=0, help="Nombre de bornes (0 = desactivees)")
    parser.add_argument("--beacon-placement", choices=["grid", "manual"], default="grid")
    parser.add_argument("--duration", type=float, default=3600.0, help="Duree de la simulation en secondes")
    parser.add_argument("--num-festivaliers", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="Copie optionnelle du rapport, en plus de l'archive")
    parser.add_argument(
        "--archive-dir", default=DEFAULT_ARCHIVE_DIR,
        help="Dossier ou chaque run ecrit <date>_<algo>.txt (rapport) et .json (parametres)",
    )
    parser.add_argument("--spray-initial-copies", type=int, default=8, help="Nombre de copies initiales (Spray & Wait)")
    parser.add_argument(
        "--replay-html", default=None,
        help="Ecrit un replay HTML autonome (positions + evenements) vers ce chemin. "
        "Cout memoire proportionnel a duration x num-festivaliers : reserve aux scenarios modestes.",
    )
    parser.add_argument("--churn", action="store_true", help="Active les arrivees/departs echelonnes des festivaliers")
    parser.add_argument(
        "--churn-arrival-window-s", type=float, nargs=2, default=(0.0, 1800.0), metavar=("LO", "HI"),
        help="Fenetre (secondes) dans laquelle chaque festivalier arrive, si --churn",
    )
    parser.add_argument(
        "--churn-session-duration-s", type=float, nargs=2, default=(1800.0, 10800.0), metavar=("LO", "HI"),
        help="Duree de presence (secondes) de chaque festivalier apres son arrivee, si --churn",
    )
    return parser


def build_config(args: argparse.Namespace) -> SimulationConfig:
    area = AreaConfig()
    mobility = MobilityConfig()
    if args.mobility == "poi":
        mobility = MobilityConfig(points_of_interest=_default_festival_pois(area))
    churn = ChurnConfig(
        enabled=args.churn,
        arrival_window_s=tuple(args.churn_arrival_window_s),
        session_duration_range_s=tuple(args.churn_session_duration_s),
    )
    return SimulationConfig(
        duration_s=args.duration,
        num_festivaliers=args.num_festivaliers,
        random_seed=args.seed,
        area=area,
        mobility=mobility,
        beacons=BeaconConfig(count=args.beacons, placement=args.beacon_placement),
        churn=churn,
    )


def main(argv: Optional[List[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = build_config(args)
    routing_algorithm = ROUTING_FACTORIES[args.routing](args)
    mobility_factory = MOBILITY_FACTORIES[args.mobility](config)
    history = None
    if args.replay_html is not None:
        history = SimulationHistory(
            area_width_m=config.area.width_m,
            area_height_m=config.area.height_m,
            tick_interval_s=config.mobility.tick_interval_s,
        )
    report = run_simulation(
        config, routing_algorithm=routing_algorithm, mobility_factory=mobility_factory, history=history
    )
    text = format_report(report)
    print(text)
    stem = archive_stem(args.archive_dir, args.routing)
    stem.with_suffix(".txt").write_text(text, encoding="utf-8")
    write_params(stem.with_suffix(".json"), vars(args), config)
    print(f"Archive ecrite dans {stem}.txt / .json")
    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    if history is not None:
        render_replay_html(history, args.replay_html, title=f"Festival BLE Mesh - {args.routing}/{args.mobility}")
        print(f"Replay HTML ecrit dans {args.replay_html}")


if __name__ == "__main__":
    main()
