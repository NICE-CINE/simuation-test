from __future__ import annotations
import argparse
from typing import Callable, Dict, List, Optional
from festival_ble_sim.config import BeaconConfig, SimulationConfig
from festival_ble_sim.metrics import format_report
from festival_ble_sim.routing.base import RoutingAlgorithm
from festival_ble_sim.routing.beacon_priority import BeaconPriorityRouting
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.routing.prophet import ProphetRouting
from festival_ble_sim.routing.spray_and_wait import SprayAndWaitRouting
from festival_ble_sim.simulation import run_simulation

ROUTING_FACTORIES: Dict[str, Callable[[argparse.Namespace], RoutingAlgorithm]] = {
    "epidemic": lambda args: EpidemicRouting(),
    "spray_wait": lambda args: SprayAndWaitRouting(initial_copies=args.spray_initial_copies),
    "prophet": lambda args: ProphetRouting(),
    "beacon_priority": lambda args: BeaconPriorityRouting(),
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulateur de messagerie BLE mesh en festival")
    parser.add_argument("--routing", choices=sorted(ROUTING_FACTORIES), default="epidemic")
    parser.add_argument("--beacons", type=int, default=0, help="Nombre de bornes (0 = desactivees)")
    parser.add_argument("--beacon-placement", choices=["grid", "manual"], default="grid")
    parser.add_argument("--duration", type=float, default=3600.0, help="Duree de la simulation en secondes")
    parser.add_argument("--num-festivaliers", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="rapport_simulation.txt")
    parser.add_argument("--spray-initial-copies", type=int, default=8, help="Nombre de copies initiales (Spray & Wait)")
    return parser


def build_config(args: argparse.Namespace) -> SimulationConfig:
    return SimulationConfig(
        duration_s=args.duration,
        num_festivaliers=args.num_festivaliers,
        random_seed=args.seed,
        beacons=BeaconConfig(count=args.beacons, placement=args.beacon_placement),
    )


def main(argv: Optional[List[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = build_config(args)
    routing_algorithm = ROUTING_FACTORIES[args.routing](args)
    report = run_simulation(config, routing_algorithm=routing_algorithm)
    text = format_report(report)
    print(text)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
