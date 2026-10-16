from __future__ import annotations
import ast
from dataclasses import fields, is_dataclass, replace
from typing import Any, List, Optional, Sequence
from .config import SimulationConfig

SET_HELP = (
    "Change n'importe quel reglage de SimulationConfig, repetable : --set traffic.message_ttl_s=900 "
    "--set mobility.group.split_probability=0.5 --set social.outside_friends_range=0,4 --set churn.enabled=True. "
    "Valeurs : nombres, True/False, None, paires 'a,b', sinon texte. Champs : voir src/festival_ble_sim/config.py"
)


def add_override_arguments(parser: Any) -> None:
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="CHEMIN=VALEUR", help=SET_HELP)


def collect_overrides(args: Any) -> List[str]:
    return list(args.overrides)


def override_paths(overrides: Sequence[str]) -> List[str]:
    return [item.partition("=")[0].strip() for item in overrides]


def apply_overrides(config: SimulationConfig, overrides: Sequence[str]) -> SimulationConfig:
    for item in overrides:
        path, sep, text = item.partition("=")
        if not sep:
            raise ValueError(f"--set attend chemin=valeur, recu {item!r}")
        config = _replace_path(config, path.strip().split("."), _parse_value(text.strip()), path.strip())
    return config


def apply_cli_overrides(
    config: SimulationConfig, overrides: Sequence[str], cooldown_s: Optional[float]
) -> SimulationConfig:
    # The CLI's cooldown defaults to the message TTL: follow a TTL changed by
    # an override, unless the cooldown was given (option or override).
    config = apply_overrides(config, overrides)
    if cooldown_s is None and "cooldown_s" not in override_paths(overrides):
        config = replace(config, cooldown_s=config.traffic.message_ttl_s)
    return config


def _parse_value(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _replace_path(obj: Any, keys: List[str], value: Any, path: str) -> Any:
    names = [f.name for f in fields(obj)]
    name = keys[0]
    if name not in names:
        raise ValueError(f"--set {path} : {name!r} n'existe pas ici ; champs possibles : {', '.join(names)}")
    current = getattr(obj, name)
    if len(keys) > 1:
        if not is_dataclass(current):
            raise ValueError(f"--set {path} : {name!r} n'a pas de sous-champs")
        return replace(obj, **{name: _replace_path(current, keys[1:], value, path)})
    if is_dataclass(current):
        raise ValueError(f"--set {path} : {name!r} est un groupe de reglages, choisir un de ses champs")
    if isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if isinstance(value, list):
        value = tuple(value)
    return replace(obj, **{name: value})
