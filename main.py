from __future__ import annotations
import argparse
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from festival_ble_sim.archive import DEFAULT_ARCHIVE_DIR, archive_stem, write_params
from festival_ble_sim.config import (
    BeaconConfig,
    ChurnConfig,
    GpsConfig,
    SimulationConfig,
    TrafficConfig,
)
from festival_ble_sim.metrics import format_report
from festival_ble_sim.mobility.base import MobilityModel
from festival_ble_sim.mobility.poi import PoiMobility
from festival_ble_sim.mobility.random_waypoint import RandomWaypointMobility
from festival_ble_sim.presets import SITE_PRESETS, add_random_charge_argument, build_site, energy_config, resolve_cli_args
from festival_ble_sim.progress import format_duration, render_bar
from festival_ble_sim.routing.registry import ROUTING_NAMES, build_routing
from festival_ble_sim.simulation import run_simulation
from festival_ble_sim.viz.history import SimulationHistory
from festival_ble_sim.viz.replay import render_replay_html, write_replay_index

DEFAULT_NUM_FESTIVALIERS = 4000
PROGRESS_BAR_WIDTH = 30
STATUS_REFRESH_S = 0.5

# "poi" has no CLI knobs of its own: build_config() points it at a default
# festival layout (see default_festival_pois) since the mobility_factory
# signature only takes an RNG, not a config.
MOBILITY_FACTORIES: Dict[str, Callable[[SimulationConfig], Callable[[random.Random], MobilityModel]]] = {
    "random_waypoint": lambda config: (lambda rng: RandomWaypointMobility(config.mobility, rng=rng)),
    "poi": lambda config: (lambda rng: PoiMobility(config.mobility, rng=rng)),
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulateur de messagerie BLE mesh en festival")
    parser.add_argument("--routing", choices=sorted(ROUTING_NAMES), default="epidemic")
    parser.add_argument(
        "--mobility", choices=sorted(MOBILITY_FACTORIES), default=None,
        help="random_waypoint par defaut, poi avec --size",
    )
    parser.add_argument(
        "--size", choices=sorted(SITE_PRESETS), default=None,
        help="Preset de site (festivaliers, surface a 3 m2/pers., 70%% du public sur 15%% de la surface)",
    )
    parser.add_argument("--beacons", type=int, default=0, help="Nombre de bornes (0 = desactivees)")
    parser.add_argument("--beacon-placement", choices=["grid", "manual"], default="grid")
    parser.add_argument("--duration", type=float, default=3600.0, help="Duree de la simulation en secondes")
    parser.add_argument("--cooldown", type=float, default=None, help="Secondes simulees en plus apres --duration pour laisser arriver les messages crees pendant --duration (seuls eux sont comptes). Defaut : le TTL des messages (1800 s) ; 0 = coupure seche")
    parser.add_argument("--num-festivaliers", type=int, default=None, help="4000 par defaut, fixe par --size")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="Copie optionnelle du rapport, en plus de l'archive")
    parser.add_argument(
        "--archive-dir", default=DEFAULT_ARCHIVE_DIR,
        help="Dossier ou chaque run ecrit <date>_<algo>.txt (rapport) et .json (parametres)",
    )
    parser.add_argument("--spray-initial-copies", type=int, default=8, help="Nombre de copies initiales (Spray & Wait)")
    parser.add_argument(
        "--replay-html", action="store_true",
        help="Ecrit un replay HTML autonome (positions + evenements) dans <archive-dir>/replay/, "
        "sous le meme nom que le rapport (<date>_<heure>_<algo>.html) avec ses donnees dans <meme nom>.data.js a cote, et regenere index.html qui les liste tous (a la racine avec l'archive par defaut, sinon dans --archive-dir).",
    )
    parser.add_argument(
        "--replay-frame-step", type=float, default=5.0,
        help="Avec --replay-html : une position tous les N secondes simulees (arrondi au tick de mobilite)",
    )
    parser.add_argument(
        "--replay-max-messages", type=int, default=100,
        help="Avec --replay-html : nombre de messages dont tous les relais sont gardes (livres en priorite, repartis dans le temps) ; les autres messages livres ne gardent que leur livraison",
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
    resolve_cli_args(args, DEFAULT_NUM_FESTIVALIERS, _raise_value_error)
    num_festivaliers, area, mobility = build_site(args.size, args.num_festivaliers, args.mobility)
    churn = ChurnConfig(
        enabled=args.churn,
        arrival_window_s=tuple(args.churn_arrival_window_s),
        session_duration_range_s=tuple(args.churn_session_duration_s),
    )
    traffic = TrafficConfig(reply_probability=args.reply_probability, followup_probability=args.followup_probability)
    return SimulationConfig(
        duration_s=args.duration,
        cooldown_s=args.cooldown if args.cooldown is not None else traffic.message_ttl_s,
        num_festivaliers=num_festivaliers,
        random_seed=args.seed,
        area=area,
        mobility=mobility,
        beacons=BeaconConfig(count=args.beacons, placement=args.beacon_placement),
        churn=churn,
        traffic=traffic,
        gps=GpsConfig(fix_failure_probability=args.gps_fix_failure),
        energy=energy_config(args.random_charge),
    )


def _raise_value_error(message: str) -> None:
    raise ValueError(message)


def make_progress_callback(total_s: float) -> Callable[[float], None]:
    start = time.monotonic()
    last_refresh = [0.0]

    def callback(sim_now: float) -> None:
        fraction = min(sim_now / total_s, 1.0) if total_s > 0 else 1.0
        now = time.monotonic()
        if fraction < 1.0 and now - last_refresh[0] < STATUS_REFRESH_S:
            return
        last_refresh[0] = now
        line = f"{render_bar(fraction, PROGRESS_BAR_WIDTH)} {fraction * 100:3.0f}% | {format_duration(now - start)}"
        width = shutil.get_terminal_size((120, 20)).columns - 1
        sys.stderr.write("\r" + line[:width].ljust(width))
        sys.stderr.flush()

    return callback


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    resolve_cli_args(args, DEFAULT_NUM_FESTIVALIERS, parser.error)
    config = build_config(args)
    routing_algorithm = build_routing(args.routing, args.seed, args.spray_initial_copies)
    mobility_factory = MOBILITY_FACTORIES[args.mobility](config)
    history = None
    if args.replay_html:
        history = SimulationHistory(
            area_width_m=config.area.width_m,
            area_height_m=config.area.height_m,
            tick_interval_s=config.mobility.tick_interval_s,
            snapshot_every_ticks=max(1, round(args.replay_frame_step / config.mobility.tick_interval_s)),
        )
    total_s = config.duration_s + config.cooldown_s
    report = run_simulation(
        config, routing_algorithm=routing_algorithm, mobility_factory=mobility_factory, history=history,
        progress_callback=make_progress_callback(total_s), progress_interval_s=max(total_s / 1000, 1.0),
    )
    sys.stderr.write("\r\033[K")
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
        replay_dir = Path(args.archive_dir) / "replay"
        replay_dir.mkdir(parents=True, exist_ok=True)
        replay_path = replay_dir / f"{stem.name}.html"
        render_replay_html(
            history, str(replay_path), title=f"Festival BLE Mesh - {args.routing}/{args.mobility}",
            max_messages=args.replay_max_messages,
        )
        print(f"Replay HTML ecrit dans {replay_path}")
        # Only the default archive dir owns the repo root's index.html; a custom one
        # could share its parent with unrelated files or other archive dirs.
        index_dir = Path(".") if args.archive_dir == DEFAULT_ARCHIVE_DIR else Path(args.archive_dir)
        index_path = index_dir / "index.html"
        write_replay_index(str(replay_dir), str(index_path))
        print(f"Index des replays mis a jour : {index_path}")


if __name__ == "__main__":
    main()
