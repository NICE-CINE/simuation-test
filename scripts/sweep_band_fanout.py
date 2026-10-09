from __future__ import annotations
import argparse
import csv
import multiprocessing
import statistics
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Tuple
from compare_algorithms import REPORT_FIELDS, STATUS_REFRESH_S, build_config, format_duration, render_status
from festival_ble_sim.archive import DEFAULT_ARCHIVE_DIR, archive_stem, write_params
from festival_ble_sim.mobility.poi import PoiMobility
from festival_ble_sim.routing.band_fanout import BandFanoutRouting
from festival_ble_sim.simulation import run_simulation

HEADERS = ["variant", "seed", "beacons"] + REPORT_FIELDS + ["wall_s"]
SUMMARY_FIELDS = ["delivery_ratio", "avg_latency_s", "p95_latency_s", "overhead", "total_energy_consumed_mah"]
DEFAULT_VARIANTS = [
    "",
    "purge_delivered=0",
    "band_low=0,band_high=1",
    "fanout=2",
    "fanout=4",
    "max_hops=3",
    "max_hops=5",
]
DEFAULT_BAND = (0.4, 0.6)


def _parse_bool(value: str) -> bool:
    if value not in ("0", "1"):
        raise ValueError(f"expected 0 or 1, got {value!r}")
    return value == "1"


_PARSERS: Dict[str, Callable[[str], Any]] = {
    "fanout": int,
    "max_hops": int,
    "band_low": float,
    "band_high": float,
    "purge_delivered": _parse_bool,
}

_worker_progress: Optional[MutableMapping[str, float]] = None


def _init_worker(progress: Optional[MutableMapping[str, float]]) -> None:
    global _worker_progress
    _worker_progress = progress


def parse_variant(text: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        key, sep, value = item.partition("=")
        if not sep or key not in _PARSERS:
            raise ValueError(f"unknown or malformed variant item {item!r} (keys: {', '.join(_PARSERS)})")
        try:
            params[key] = _PARSERS[key](value)
        except ValueError as exc:
            raise ValueError(f"bad value in {item!r}: {exc}") from exc
    return params


def variant_label(text: str) -> str:
    return text or "defaults"


def build_algorithm(params: Dict[str, Any], seed: int) -> BandFanoutRouting:
    kwargs = {k: v for k, v in params.items() if k not in ("band_low", "band_high")}
    if "band_low" in params or "band_high" in params:
        kwargs["band"] = (params.get("band_low", DEFAULT_BAND[0]), params.get("band_high", DEFAULT_BAND[1]))
    return BandFanoutRouting(seed=seed, **kwargs)


def run_label(variant: str, seed: int) -> str:
    return f"{variant_label(variant)} s={seed}"


def _run_one(
    variant: str,
    seed: int,
    duration_s: float,
    num_festivaliers: int,
    beacon_count: int,
    mobility: str,
    reply_probability: float,
) -> Dict[str, Any]:
    progress = _worker_progress
    config = build_config(beacon_count, seed, duration_s, num_festivaliers, mobility, reply_probability)
    label = run_label(variant, seed)
    progress_callback = None
    if progress is not None:
        progress[label] = 0.0

        def progress_callback(sim_now: float) -> None:
            progress[label] = min(sim_now / duration_s, 1.0) if duration_s > 0 else 1.0

    start = time.monotonic()
    report = run_simulation(
        config,
        routing_algorithm=build_algorithm(parse_variant(variant), seed),
        mobility_factory=(lambda rng: PoiMobility(config.mobility, rng=rng)) if mobility == "poi" else None,
        progress_callback=progress_callback,
        progress_interval_s=max(duration_s / 1000, 1.0),
    )
    row: Dict[str, Any] = {"variant": variant_label(variant), "seed": seed, "beacons": beacon_count}
    row.update({field: getattr(report, field) for field in REPORT_FIELDS})
    row["wall_s"] = time.monotonic() - start
    return row


def run_sweep(
    variants: List[str],
    seeds: List[int],
    duration_s: float,
    num_festivaliers: int,
    beacon_count: int,
    mobility: str = "random_waypoint",
    reply_probability: float = 0.0,
    workers: int = 1,
    show_progress: bool = False,
    csv_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    tasks: List[Tuple[str, int]] = [(variant, seed) for variant in variants for seed in seeds]
    results: Dict[int, Dict[str, Any]] = {}
    sweep_start = time.monotonic()
    manager = multiprocessing.Manager() if show_progress else None
    progress = manager.dict() if manager is not None else None
    executor = ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(progress,))
    try:
        futures: Dict[Future, int] = {
            executor.submit(
                _run_one, variant, seed, duration_s, num_festivaliers, beacon_count, mobility, reply_probability
            ): index
            for index, (variant, seed) in enumerate(tasks)
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
    for variant in dict.fromkeys(row["variant"] for row in rows):
        group = [row for row in rows if row["variant"] == variant]
        entry: Dict[str, Any] = {"variant": variant, "runs": len(group)}
        for field in SUMMARY_FIELDS:
            entry[field] = statistics.mean(row[field] for row in group)
        summary.append(entry)
    return summary


def print_summary(summary: List[Dict[str, Any]]) -> None:
    headers = ["variant", "runs"] + SUMMARY_FIELDS
    cells = [[f"{e[h]:.3f}" if isinstance(e[h], float) else str(e[h]) for h in headers] for e in summary]
    widths = [max(len(h), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for c in cells:
        print(" | ".join(v.ljust(w) for v, w in zip(c, widths)))


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Balayage de variantes de band_fanout")
    parser.add_argument(
        "--variant", action="append", default=None,
        help="Variante 'cle=val,cle=val' (cles : " + ", ".join(_PARSERS) + "); repetable, '' = defauts. "
        "Sans --variant : " + " | ".join(variant_label(v) for v in DEFAULT_VARIANTS),
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--duration", type=float, default=3600.0)
    parser.add_argument("--num-festivaliers", type=int, default=200)
    parser.add_argument("--beacon-count", type=int, default=6)
    parser.add_argument("--mobility", choices=["random_waypoint", "poi"], default="random_waypoint")
    parser.add_argument("--reply-probability", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--archive-dir", default=DEFAULT_ARCHIVE_DIR)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers doit etre >= 1")
    if args.variant is None:
        args.variant = list(DEFAULT_VARIANTS)
    for text in args.variant:
        try:
            build_algorithm(parse_variant(text), seed=0)
        except ValueError as exc:
            parser.error(f"--variant {text!r}: {exc}")

    stem = archive_stem(args.archive_dir, "sweep_band_fanout")
    archive_csv = str(stem.with_suffix(".csv"))
    # The variants aren't part of SimulationConfig: they live in the CLI args.
    write_params(
        stem.with_suffix(".json"),
        vars(args),
        build_config(args.beacon_count, args.seeds[0], args.duration, args.num_festivaliers, args.mobility, args.reply_probability),
    )
    rows = run_sweep(
        args.variant, args.seeds, args.duration, args.num_festivaliers, args.beacon_count,
        mobility=args.mobility, reply_probability=args.reply_probability,
        workers=args.workers, show_progress=True, csv_path=archive_csv,
    )
    print_summary(summarize(rows))
    print(f"\nArchive ecrite dans {archive_csv} / .json")


if __name__ == "__main__":
    main()
