from __future__ import annotations
import argparse
import csv
import multiprocessing
import shutil
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Tuple
from festival_ble_sim.config import BeaconConfig, SimulationConfig
from festival_ble_sim.metrics import SimulationReport
from festival_ble_sim.routing.base import RoutingAlgorithm
from festival_ble_sim.routing.beacon_priority import BeaconPriorityRouting
from festival_ble_sim.routing.bubble_f import BubbleFRouting
from festival_ble_sim.routing.dasfv import DasfVRouting
from festival_ble_sim.routing.epidemic import EpidemicRouting
from festival_ble_sim.routing.gossip_a import GossipARouting
from festival_ble_sim.routing.managed_flood import ManagedFloodRouting
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
    "bubble_f": BubbleFRouting,
    "managed_flood": ManagedFloodRouting,
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

MINI_BAR_WIDTH = 10
STATUS_REFRESH_S = 0.5


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes:02d}m{secs:02d}s"


def run_label(algo_name: str, beacon_count: int) -> str:
    return f"{algo_name} ({'avec' if beacon_count > 0 else 'sans'} bornes)"


def render_status(
    running: List[str],
    progress: MutableMapping[str, float],
    done_count: int,
    total_runs: int,
    wall_elapsed: float,
) -> str:
    parts = []
    for label in running:
        fraction = progress.get(label, 0.0)
        filled = int(round(fraction * MINI_BAR_WIDTH))
        bar = "█" * filled + "░" * (MINI_BAR_WIDTH - filled)
        parts.append(f"{label} {bar} {fraction * 100:3.0f}%")
    line = f"{done_count}/{total_runs} terminés | {format_duration(wall_elapsed)} | " + " | ".join(parts)
    width = shutil.get_terminal_size((120, 20)).columns - 1
    return "\r" + line[:width].ljust(width)


def append_csv_row(row: dict, path: str, write_header: bool) -> None:
    headers = ["algorithm", "beacons"] + REPORT_FIELDS
    with open(path, "w" if write_header else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _run_one(
    algo_name: str,
    beacon_count: int,
    seed: int,
    duration_s: float,
    num_festivaliers: int,
    progress: Optional[MutableMapping[str, float]],
) -> Tuple[dict, float]:
    config = SimulationConfig(
        duration_s=duration_s,
        num_festivaliers=num_festivaliers,
        random_seed=seed,
        beacons=BeaconConfig(count=beacon_count),
    )
    label = run_label(algo_name, beacon_count)
    progress_callback = None
    if progress is not None:
        progress[label] = 0.0

        def progress_callback(sim_now: float) -> None:
            progress[label] = min(sim_now / duration_s, 1.0) if duration_s > 0 else 1.0

    start = time.monotonic()
    report: SimulationReport = run_simulation(
        config,
        routing_algorithm=ALGORITHMS[algo_name](),
        progress_callback=progress_callback,
        progress_interval_s=max(duration_s / 1000, 1.0),
    )
    row: Dict[str, Any] = {"algorithm": algo_name, "beacons": beacon_count}
    row.update({field: getattr(report, field) for field in REPORT_FIELDS})
    return row, time.monotonic() - start


def run_matrix(
    seed: int = 42,
    duration_s: float = 3600.0,
    num_festivaliers: int = 200,
    beacon_count: int = 6,
    workers: int = 1,
    show_progress: bool = False,
    csv_path: Optional[str] = None,
) -> List[dict]:
    tasks = [(algo_name, count) for algo_name in ALGORITHMS for count in (0, beacon_count)]
    results: Dict[int, dict] = {}
    matrix_start = time.monotonic()
    manager = multiprocessing.Manager() if show_progress else None
    progress = manager.dict() if manager is not None else None
    executor = ProcessPoolExecutor(max_workers=workers)
    try:
        futures: Dict[Future, int] = {
            executor.submit(_run_one, algo_name, count, seed, duration_s, num_festivaliers, progress): index
            for index, (algo_name, count) in enumerate(tasks)
        }
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=STATUS_REFRESH_S, return_when=FIRST_COMPLETED)
            for future in finished:
                index = futures[future]
                row, run_elapsed = future.result()
                results[index] = row
                if csv_path:
                    append_csv_row(row, csv_path, write_header=len(results) == 1)
                if progress is not None:
                    label = run_label(*tasks[index])
                    progress.pop(label, None)
                    sys.stderr.write(
                        f"\r\033[K✓ [{len(results)}/{len(tasks)}] {label} terminé en {format_duration(run_elapsed)} "
                        f"(delivery_ratio={row['delivery_ratio']:.3f}) — total écoulé "
                        f"{format_duration(time.monotonic() - matrix_start)}\n"
                    )
            if progress is not None:
                running = sorted(progress.keys())
                sys.stderr.write(
                    render_status(running, progress, len(results), len(tasks), time.monotonic() - matrix_start)
                )
                sys.stderr.flush()
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        executor.shutdown(wait=True)
        if manager is not None:
            manager.shutdown()
    if progress is not None:
        sys.stderr.write("\r\033[K")
    return [results[index] for index in range(len(tasks))]


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
    parser.add_argument("--workers", type=int, default=2, help="Nombre de simulations lancees en parallele")
    parser.add_argument("--csv", default=None, help="Chemin d'export CSV (optionnel)")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers doit etre >= 1")

    rows = run_matrix(
        seed=args.seed,
        duration_s=args.duration,
        num_festivaliers=args.num_festivaliers,
        beacon_count=args.beacon_count,
        workers=args.workers,
        show_progress=True,
        csv_path=args.csv,
    )
    if args.csv:
        write_csv(rows, args.csv)
    print_table(rows)
    if args.csv:
        print(f"\nExporte vers {args.csv}")


if __name__ == "__main__":
    main()
