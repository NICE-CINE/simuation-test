from __future__ import annotations
import argparse
import csv
from typing import Callable, Dict, List, Optional
from festival_ble_sim.config import BeaconConfig, SimulationConfig
from festival_ble_sim.metrics import SimulationReport
from festival_ble_sim.routing.base import RoutingAlgorithm
from festival_ble_sim.routing.beacon_priority import BeaconPriorityRouting
from festival_ble_sim.routing.dasfv import DasfVRouting
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.routing.gossip_a import GossipARouting
from festival_ble_sim.routing.prophet import ProphetRouting
from festival_ble_sim.routing.spray_and_wait import SprayAndWaitRouting
from festival_ble_sim.simulation import run_simulation

ALGORITHMS: Dict[str, Callable[[], RoutingAlgorithm]] = {
    "epidemic": EpidemicRouting,
    "spray_wait": SprayAndWaitRouting,
    "prophet": ProphetRouting,
    "beacon_priority": BeaconPriorityRouting,
    "dasfv": DasfVRouting,
    "gossip_a": GossipARouting,
}

REPORT_FIELDS = [
    "delivery_ratio",
    "avg_latency_s",
    "p95_latency_s",
    "avg_hops",
    "overhead",
    "total_energy_consumed_mah",
    "buffer_eviction_count",
    "packet_loss_count",
    "backhaul_transmissions",
]


def run_matrix(
    seed: int = 42,
    duration_s: float = 3600.0,
    num_festivaliers: int = 200,
    beacon_count: int = 6,
) -> List[dict]:
    rows: List[dict] = []
    for algo_name, algo_factory in ALGORITHMS.items():
        for beacons_enabled in (False, True):
            beacons = BeaconConfig(count=beacon_count if beacons_enabled else 0)
            config = SimulationConfig(
                duration_s=duration_s,
                num_festivaliers=num_festivaliers,
                random_seed=seed,
                beacons=beacons,
            )
            report: SimulationReport = run_simulation(config, routing_algorithm=algo_factory())
            row = {"algorithm": algo_name, "beacons": beacon_count if beacons_enabled else 0}
            row.update({field: getattr(report, field) for field in REPORT_FIELDS})
            rows.append(row)
    return rows


def print_table(rows: List[dict]) -> None:
    headers = ["algorithm", "beacons"] + REPORT_FIELDS
    widths = {h: max(len(h), *(len(f"{row[h]:.3f}" if isinstance(row[h], float) else str(row[h])) for row in rows)) for h in headers}

    def fmt_cell(value) -> str:
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print(" | ".join(fmt_cell(row[h]).ljust(widths[h]) for h in headers))


def write_csv(rows: List[dict], path: str) -> None:
    headers = ["algorithm", "beacons"] + REPORT_FIELDS
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Compare les algos de routing avec/sans bornes")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--num-festivaliers", type=int, default=200)
    parser.add_argument("--beacon-count", type=int, default=6)
    parser.add_argument("--csv", default=None, help="Chemin d'export CSV (optionnel)")
    args = parser.parse_args(argv)

    rows = run_matrix(
        seed=args.seed,
        duration_s=args.duration,
        num_festivaliers=args.num_festivaliers,
        beacon_count=args.beacon_count,
    )
    print_table(rows)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nExporte vers {args.csv}")


if __name__ == "__main__":
    main()
