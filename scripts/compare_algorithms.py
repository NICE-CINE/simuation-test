from __future__ import annotations
import argparse
import csv
import math
import multiprocessing
import shutil
import statistics
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any, Dict, List, MutableMapping, Optional, Tuple
from festival_ble_sim.archive import DEFAULT_ARCHIVE_DIR, archive_stem, write_params
from festival_ble_sim.config import BeaconConfig, GpsConfig, SimulationConfig, TrafficConfig
from festival_ble_sim.metrics import SimulationReport
from festival_ble_sim.presets import MOBILITY_MODELS, mobility_factory
from festival_ble_sim.presets import (
    DEFAULT_WARMUP_S, SITE_PRESETS, WARMUP_HELP, add_random_charge_argument, add_schedule_argument,
    add_social_arguments, build_site, energy_config, resolve_cli_args, social_config, with_schedule,
)
from festival_ble_sim.progress import MINI_BAR_WIDTH, format_duration, render_bar
from festival_ble_sim.routing.registry import ROUTING_NAMES, build_routing
from festival_ble_sim.simulation import run_simulation

ALGORITHMS = ROUTING_NAMES

REPORT_FIELDS = [
    "messages_created",
    "delivery_ratio",
    "avg_latency_s",
    "p95_latency_s",
    "avg_hops",
    "overhead",
    "overhead_bytes",
    "retransmitted_bytes",
    "total_energy_consumed_mah",
    "total_mesh_energy_consumed_mah",
    "buffer_eviction_count",
    "packet_loss_count",
    "backhaul_transmissions",
    "replies_created",
    "reply_delivery_ratio",
]

HEADERS = ["algorithm", "beacons", "seed"] + REPORT_FIELDS
SUMMARY_HEADERS = ["algorithm", "beacons", "runs"] + [
    name for field in REPORT_FIELDS for name in (field, f"{field}_ci95")
]
# Two-sided 95 % Student t quantiles by degrees of freedom; a missing df
# takes the next lower one (wider interval), 1.96 past 30.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042}

STATUS_REFRESH_S = 0.5


def run_label(algo_name: str, beacon_count: int, seed: int) -> str:
    return f"{algo_name} ({'avec' if beacon_count > 0 else 'sans'} bornes) s={seed}"


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
        parts.append(f"{label} {render_bar(fraction, MINI_BAR_WIDTH)} {fraction * 100:3.0f}%")
    line = f"{done_count}/{total_runs} terminés | {format_duration(wall_elapsed)} | " + " | ".join(parts)
    width = shutil.get_terminal_size((120, 20)).columns - 1
    return "\r" + line[:width].ljust(width)


def append_csv_row(row: dict, path: str, write_header: bool, headers: Optional[List[str]] = None) -> None:
    headers = headers or HEADERS
    with open(path, "w" if write_header else "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def build_config(
    beacon_count: int,
    seed: int,
    duration_s: float,
    num_festivaliers: int,
    mobility: str = "random_waypoint",
    reply_probability: float = 0.0,
    followup_probability: float = 0.0,
    gps_fix_failure: float = 0.0,
    size: Optional[str] = None,
    cooldown_s: Optional[float] = None,
    random_charge: bool = False,
    warmup_s: Optional[float] = None,
    no_outside_friends: bool = False,
    no_lost_messages: bool = False,
    schedule: bool = False,
) -> SimulationConfig:
    num_festivaliers, area, mobility_config = build_site(size, num_festivaliers, mobility)
    traffic = TrafficConfig(
        reply_probability=reply_probability,
        followup_probability=followup_probability,
        lost_messages_per_hour=0.0 if no_lost_messages else TrafficConfig.lost_messages_per_hour,
    )
    return SimulationConfig(
        duration_s=duration_s,
        # Default: the message TTL, so every counted message gets its full lifetime.
        cooldown_s=cooldown_s if cooldown_s is not None else traffic.message_ttl_s,
        warmup_s=warmup_s if warmup_s is not None else DEFAULT_WARMUP_S,
        num_festivaliers=num_festivaliers,
        random_seed=seed,
        area=area,
        mobility=with_schedule(mobility_config, schedule),
        beacons=BeaconConfig(count=beacon_count),
        traffic=traffic,
        gps=GpsConfig(fix_failure_probability=gps_fix_failure),
        energy=energy_config(random_charge),
        social=social_config(no_outside_friends),
    )


_worker_progress: Optional[MutableMapping[str, float]] = None


def _init_worker(progress: Optional[MutableMapping[str, float]]) -> None:
    # The Manager proxy is handed over once per worker, not per task: a
    # per-task proxy copy being garbage-collected closes the worker's
    # shared Manager connection under the next task's proxy.
    global _worker_progress
    _worker_progress = progress


def _run_one(
    algo_name: str,
    beacon_count: int,
    seed: int,
    duration_s: float,
    num_festivaliers: int,
    mobility: str = "random_waypoint",
    reply_probability: float = 0.0,
    followup_probability: float = 0.0,
    gps_fix_failure: float = 0.0,
    size: Optional[str] = None,
    cooldown_s: Optional[float] = None,
    random_charge: bool = False,
    warmup_s: Optional[float] = None,
    no_outside_friends: bool = False,
    no_lost_messages: bool = False,
    schedule: bool = False,
) -> Tuple[dict, float]:
    progress = _worker_progress
    config = build_config(
        beacon_count, seed, duration_s, num_festivaliers, mobility, reply_probability,
        followup_probability, gps_fix_failure, size, cooldown_s, random_charge, warmup_s, no_outside_friends,
        no_lost_messages, schedule,
    )
    total_s = config.total_s
    label = run_label(algo_name, beacon_count, seed)
    progress_callback = None
    if progress is not None:
        progress[label] = 0.0

        def progress_callback(sim_now: float) -> None:
            progress[label] = min(sim_now / total_s, 1.0) if total_s > 0 else 1.0

    start = time.monotonic()
    report: SimulationReport = run_simulation(
        config,
        routing_algorithm=build_routing(algo_name, seed),
        mobility_factory=mobility_factory(mobility, config.mobility),
        progress_callback=progress_callback,
        progress_interval_s=max(total_s / 1000, 1.0),
    )
    row: Dict[str, Any] = {"algorithm": algo_name, "beacons": beacon_count}
    row.update({field: getattr(report, field) for field in REPORT_FIELDS})
    return row, time.monotonic() - start


def run_matrix(
    seeds: Tuple[int, ...] = (42,),
    duration_s: float = 3600.0,
    num_festivaliers: int = 200,
    beacon_count: int = 6,
    workers: int = 1,
    show_progress: bool = False,
    csv_path: Optional[str] = None,
    mobility: str = "random_waypoint",
    reply_probability: float = 0.0,
    followup_probability: float = 0.0,
    gps_fix_failure: float = 0.0,
    size: Optional[str] = None,
    cooldown_s: Optional[float] = None,
    algorithms: Optional[List[str]] = None,
    random_charge: bool = False,
    warmup_s: Optional[float] = None,
    no_outside_friends: bool = False,
    no_lost_messages: bool = False,
    schedule: bool = False,
) -> List[dict]:
    names = list(ALGORITHMS) if algorithms is None else algorithms
    # Every algorithm runs on the same seeds, so runs are paired by seed.
    tasks = [(algo_name, count, seed) for seed in seeds for algo_name in names for count in (0, beacon_count)]
    results: Dict[int, dict] = {}
    matrix_start = time.monotonic()
    manager = multiprocessing.Manager() if show_progress else None
    progress = manager.dict() if manager is not None else None
    executor = ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(progress,))
    try:
        futures: Dict[Future, int] = {
            executor.submit(
                _run_one, algo_name, count, seed, duration_s, num_festivaliers, mobility, reply_probability,
                followup_probability, gps_fix_failure, size, cooldown_s, random_charge, warmup_s, no_outside_friends,
                no_lost_messages, schedule,
            ): index
            for index, (algo_name, count, seed) in enumerate(tasks)
        }
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=STATUS_REFRESH_S, return_when=FIRST_COMPLETED)
            for future in finished:
                index = futures[future]
                row, run_elapsed = future.result()
                row = {"seed": tasks[index][2], **row}
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


def summarize(rows: List[dict]) -> List[dict]:
    groups: Dict[Tuple[str, int], List[dict]] = {}
    for row in rows:
        groups.setdefault((row["algorithm"], row["beacons"]), []).append(row)
    summary = []
    for (algo_name, beacons), group in groups.items():
        entry: Dict[str, Any] = {"algorithm": algo_name, "beacons": beacons, "runs": len(group)}
        n = len(group)
        t = _T95[max(df for df in _T95 if df <= n - 1)] if 1 < n <= 31 else 1.96
        for field in REPORT_FIELDS:
            values = [float(row[field]) for row in group]
            entry[field] = statistics.mean(values)
            entry[f"{field}_ci95"] = t * statistics.stdev(values) / math.sqrt(n) if n > 1 else 0.0
        summary.append(entry)
    return summary


def print_table(rows: List[dict], headers: Optional[List[str]] = None) -> None:
    headers = headers or HEADERS
    widths = {h: max(len(h), *(len(f"{row[h]:.3f}" if isinstance(row[h], float) else str(row[h])) for row in rows)) for h in headers}

    def fmt_cell(value) -> str:
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print(" | ".join(fmt_cell(row[h]).ljust(widths[h]) for h in headers))


def write_csv(rows: List[dict], path: str, headers: Optional[List[str]] = None) -> None:
    headers = headers or HEADERS
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Compare les algos de routing avec/sans bornes")
    parser.add_argument(
        "--seeds", "--seed", dest="seeds", type=int, nargs="+", default=[42],
        help="Une ou plusieurs seeds ; avec plusieurs, un resume moyenne +/- IC 95 %% par algo x bornes",
    )
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--cooldown", type=float, default=None, help="Secondes simulees en plus apres --duration pour laisser arriver les messages crees pendant --duration (seuls eux sont comptes). Defaut : le TTL des messages (1800 s) ; 0 = coupure seche")
    parser.add_argument("--warmup", type=float, default=None, help=WARMUP_HELP)
    parser.add_argument("--num-festivaliers", type=int, default=None, help="200 par defaut, fixe par --size")
    parser.add_argument("--beacon-count", type=int, default=6)
    parser.add_argument(
        "--mobility", choices=sorted(MOBILITY_MODELS), default=None, help="random_waypoint par defaut, group avec --size",
    )
    parser.add_argument(
        "--size", choices=sorted(SITE_PRESETS), default=None,
        help="Preset de site (festivaliers, surface a 3 m2/pers., 70%% du public sur 15%% de la surface)",
    )
    parser.add_argument(
        "--reply-probability", type=float, default=0.0,
        help="Probabilite qu'un message livre recoive une reponse du destinataire (0 = pas de reponses)",
    )
    parser.add_argument(
        "--followup-probability", type=float, default=0.0,
        help="Probabilite qu'un message spontane soit suivi d'une relance au meme destinataire (0 = pas de rafales)",
    )
    parser.add_argument(
        "--gps-fix-failure", type=float, default=0.0,
        help="Probabilite qu'un fix GPS echoue (0 = fix toujours reussi)",
    )
    add_random_charge_argument(parser)
    add_social_arguments(parser)
    add_schedule_argument(parser)
    parser.add_argument(
        "--algorithms", nargs="+", choices=sorted(ALGORITHMS), default=None,
        help="Sous-ensemble d'algos a lancer (defaut : tous)",
    )
    parser.add_argument("--workers", type=int, default=2, help="Nombre de simulations lancees en parallele")
    parser.add_argument("--csv", default=None, help="Copie optionnelle du CSV, en plus de l'archive")
    parser.add_argument(
        "--archive-dir", default=DEFAULT_ARCHIVE_DIR,
        help="Dossier ou chaque comparaison ecrit <date>_comparaison.csv et .json (parametres)",
    )
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers doit etre >= 1")
    resolve_cli_args(args, 200, parser.error)

    stem = archive_stem(args.archive_dir, "comparaison")
    archive_csv = str(stem.with_suffix(".csv"))
    # Beacon count varies per row (0 or --beacon-count); the archived config
    # is the "with beacons" one, the CSV's `beacons` column says which applied.
    write_params(
        stem.with_suffix(".json"),
        vars(args),
        build_config(
            args.beacon_count, args.seeds[0], args.duration, args.num_festivaliers, args.mobility, args.reply_probability,
            args.followup_probability, args.gps_fix_failure, args.size, args.cooldown, args.random_charge,
            args.warmup, args.no_outside_friends, args.no_lost_messages, args.schedule,
        ),
    )
    rows = run_matrix(
        seeds=args.seeds,
        duration_s=args.duration,
        num_festivaliers=args.num_festivaliers,
        beacon_count=args.beacon_count,
        workers=args.workers,
        show_progress=True,
        csv_path=archive_csv,
        mobility=args.mobility,
        reply_probability=args.reply_probability,
        followup_probability=args.followup_probability,
        gps_fix_failure=args.gps_fix_failure,
        size=args.size,
        cooldown_s=args.cooldown,
        algorithms=args.algorithms,
        random_charge=args.random_charge,
        warmup_s=args.warmup,
        no_outside_friends=args.no_outside_friends,
        no_lost_messages=args.no_lost_messages,
        schedule=args.schedule,
    )
    write_csv(rows, archive_csv)
    if args.csv:
        write_csv(rows, args.csv)
    print_table(rows)
    if len(args.seeds) > 1:
        summary = summarize(rows)
        summary_csv = str(stem.parent / f"{stem.name}_resume.csv")
        write_csv(summary, summary_csv, SUMMARY_HEADERS)
        print("\nMoyenne +/- IC 95 % sur les seeds :")
        print_table(summary, ["algorithm", "beacons", "runs", "delivery_ratio", "delivery_ratio_ci95",
                              "avg_latency_s", "avg_latency_s_ci95", "overhead", "overhead_ci95",
                              "total_energy_consumed_mah", "total_energy_consumed_mah_ci95"])
        print(f"\nResume ecrit dans {summary_csv}")
    print(f"\nArchive ecrite dans {archive_csv} / .json")
    if args.csv:
        print(f"\nExporte vers {args.csv}")


if __name__ == "__main__":
    main()
