import json
import subprocess
from festival_ble_sim import archive
from festival_ble_sim.config import SimulationConfig


def test_stems_created_in_the_same_second_do_not_collide(tmp_path, monkeypatch):
    class FrozenNow:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime(2026, 10, 12, 10, 0, 0)

    monkeypatch.setattr(archive, "datetime", FrozenNow)
    first = archive.archive_stem(str(tmp_path), "epidemic")
    second = archive.archive_stem(str(tmp_path), "epidemic")
    assert first.name == "2026-10-12_10-00-00_epidemic"
    assert second.name == "2026-10-12_10-00-00_epidemic-2"


def test_params_record_the_git_commit_and_local_changes(tmp_path):
    path = tmp_path / "run.json"
    archive.write_params(path, {"seed": 1}, SimulationConfig())
    state = json.loads(path.read_text())["git"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert state["commit"] == head
    assert isinstance(state["dirty"], bool)
    assert set(state) == {"commit", "dirty", "status", "diff"}


def test_params_without_git_store_none(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_git", lambda *args: None)
    path = tmp_path / "run.json"
    archive.write_params(path, {}, SimulationConfig())
    assert json.loads(path.read_text())["git"] is None
