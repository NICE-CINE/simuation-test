from __future__ import annotations
import itertools
import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from .config import SimulationConfig

DEFAULT_ARCHIVE_DIR = "archives"


def archive_stem(archive_dir: str, label: str) -> Path:
    directory = Path(archive_dir)
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{label}"
    # Every caller writes <stem>.json: creating it exclusively reserves the
    # stem, so two runs started in the same second (parallel launches) get
    # base and base-2 instead of overwriting each other.
    for n in itertools.count(1):
        stem = directory / (base if n == 1 else f"{base}-{n}")
        try:
            stem.with_suffix(".json").touch(exist_ok=False)
            return stem
        except FileExistsError:
            continue
    raise AssertionError("unreachable")


def _git(*args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=Path(__file__).resolve().parent, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def git_state() -> Optional[Dict[str, Any]]:
    # Uncommitted edits and untracked scripts produced past archives that no
    # commit can reproduce: keep the commit plus whatever differed from it.
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return None
    status = _git("status", "--porcelain") or ""
    return {
        "commit": commit.strip(),
        "dirty": bool(status.strip()),
        "status": status.splitlines(),
        "diff": _git("diff", "HEAD") or "",
    }


def write_params(path: Path, cli_args: Dict[str, Any], config: SimulationConfig) -> None:
    # CLI args alone aren't enough to reproduce a run: config.py defaults
    # change over time, so the fully resolved config is archived too.
    payload = {"cli": cli_args, "config": asdict(config), "git": git_state()}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
