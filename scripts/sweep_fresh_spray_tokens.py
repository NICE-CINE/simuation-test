from __future__ import annotations
import argparse
import csv
import multiprocessing
import statistics
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any, Dict, List, MutableMapping, Optional, Tuple
from compare_algorithms import REPORT_FIELDS, STATUS_REFRESH_S, build_config, format_duration, render_status
from festival_ble_sim.archive import DEFAULT_ARCHIVE_DIR, archive_stem, write_params
from festival_ble_sim.mobility.poi import PoiMobility
from festival_ble_sim.presets import SITE_PRESETS, resolve_cli_args
from festival_ble_sim.routing.fresh_spray import FreshSprayRouting
from festival_ble_sim.simulation import run_simulation

HEADERS = ["initial_tokens", "seed", "beacons"] + REPORT_FIELDS + ["wall_s"]
SUMMARY_FIELDS = ["delivery_ratio", "avg_latency_s", "p95_latency_s", "overhead", "total_energy_consumed_mah"]

_worker_progress: Optional[MutableMapping[str, float]] = None


def _init_worker(progress: Optional[MutableMapping[str, float]]) -> None:
    global _worker_progress
    _worker_progress = progress


def run_label(tokens: int, seed: int) -> str:
    return f"t={tokens} s={seed}"


def _run_one(
    tokens: int,
    seed: int,
    duration_s: float,
    num_festivaliers: int,
    beacon_count: int,
    mobility: str,
    reply_probability: float,
    size: Optional[str] = None,
) -> Dict[str, Any]:
    progress = _worker_progress
    config = build_config(
        beacon_count, seed, duration_s, num_festivaliers, mobility, reply_probability, size=size
    )
    label = run_label(tokens, seed)
    progress_callback = None
    if progress is not None:
        progress[label] = 0.0

        def progress_callback(sim_now: float) -> None:
            progress[label] = min(sim_now / duration_s, 1.0) if duration_s > 0 else 1.0

    start = time.monotonic()
    report = run_simulation(
        config,
        routing_algorithm=FreshSprayRouting(initial_tokens=tokens),
        mobility_factory=(lambda rng: PoiMobility(config.mobility, rng=rng)) if mobility == "poi" else None,
        progress_callback=progress_callback,
        progress_interval_s=max(duration_s / 1000, 1.0),
    )
    row: Dict[str, Any] = {"initial_tokens": tokens, "seed": seed, "beacons": beacon_count}
    row.update({field: getattr(report, field) for field in REPORT_FIELDS})
    row["wall_s"] = time.monotonic() - start
    return row


def run_sweep(
    tokens_list: List[int],
    seeds: List[int],
    duration_s: float,
    num_festivaliers: int,
    beacon_count: int,
    mobility: str = "random_waypoint",
    reply_probability: float = 0.0,
    size: Optional[str] = None,
    workers: int = 1,
    show_progress: bool = False,
    csv_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tasks: List[Tuple[int, int]] = [(tokens, seed) for tokens in tokens_list for seed in seeds]
    results: Dict[int, Dict[str, Any]] = {}
    sweep_start = time.monotonic()
    manager = multiprocessing.Manager() if show_progress else None
    progress = manager.dict() if manager is not None else None
    executor = ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(progress,))
    try:
        futures: Dict[Future, int] = {
            executor.submit(
                _run_one, tokens, seed, duration_s, num_festivaliers, beacon_count, mobility, reply_probability, size
            ): index
            for index, (tokens, seed) in enumerate(tasks)
        }
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=STATUS_REFRESH_S, return_when=FIRST_COMPLETED)
            for future in finished:
                index = futures[future]
                row = future.result()
                results[index] = row
                if csv_path:
                    with open(csv_path, "w" if len(results) == 1 else "a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=HEADERS)
                        if len(results) == 1:
                            writer.writeheader()
                        writer.writerow(row)
                if progress is not None:
                    label = run_label(*tasks[index])
                    progress.pop(label, None)
                    sys.stderr.write(
                        f"\r\033[K✓ [{len(results)}/{len(tasks)}] {label} terminé en {format_duration(row['wall_s'])} "
                        f"(delivery_ratio={row['delivery_ratio']:.3f}, latence={row['avg_latency_s']:.0f} s)\n"
                    )
            if progress is not None:
                sys.stderr.write(
                    render_status(sorted(progress.keys()), progress, len(results), len(tasks), time.monotonic() - sweep_start)
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


def summarize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary = []
    for tokens in sorted({row["initial_tokens"] for row in rows}):
        group = [row for row in rows if row["initial_tokens"] == tokens]
        entry: Dict[str, Any] = {"initial_tokens": tokens, "runs": len(group)}
        for field in SUMMARY_FIELDS:
            entry[field] = statistics.mean(row[field] for row in group)
        summary.append(entry)
    return summary


def print_summary(summary: List[Dict[str, Any]]) -> None:
    headers = ["initial_tokens", "runs"] + SUMMARY_FIELDS
    cells = [[f"{e[h]:.3f}" if isinstance(e[h], float) else str(e[h]) for h in headers] for e in summary]
    widths = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for c in cells:
        print(" | ".join(v.ljust(w) for v, w in zip(c, widths)))


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Balayage de initial_tokens pour fresh_spray")
    parser.add_argument("--tokens", type=int, nargs="+", default=[4, 8, 16, 32])
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--num-festivaliers", type=int, default=None, help="200 par defaut, fixe par --size")
    parser.add_argument("--beacon-count", type=int, default=6)
    parser.add_argument(
        "--mobility", choices=["random_waypoint", "poi"], default=None, help="random_waypoint par defaut, poi avec --size",
    )
    parser.add_argument(
        "--size", choices=sorted(SITE_PRESETS), default=None,
        help="Preset de site (festivaliers, surface a 3 m2/pers., 70%% du public sur 15%% de la surface)",
    )
    parser.add_argument("--reply-probability", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--archive-dir", default=DEFAULT_ARCHIVE_DIR)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers doit etre >= 1")
    if min(args.tokens) < 1:
        parser.error("--tokens doit etre >= 1")
    resolve_cli_args(args, 200, parser.error)

    stem = archive_stem(args.archive_dir, "sweep_fresh_spray_tokens")
    archive_csv = str(stem.with_suffix(".csv"))
    # initial_tokens isn't part of SimulationConfig: it lives in the CLI args.
    write_params(
        stem.with_suffix(".json"),
        vars(args),
        build_config(
            args.beacon_count, args.seeds[0], args.duration, args.num_festivaliers, args.mobility,
            args.reply_probability, size=args.size,
        ),
    )
    rows = run_sweep(
        args.tokens, args.seeds, args.duration, args.num_festivaliers, args.beacon_count,
        mobility=args.mobility, reply_probability=args.reply_probability, size=args.size,
        workers=args.workers, show_progress=True, csv_path=archive_csv,
    )
    print_summary(summarize(rows))
    print(f"\nArchive ecrite dans {archive_csv} / .json")


if __name__ == "__main__":
    main()
