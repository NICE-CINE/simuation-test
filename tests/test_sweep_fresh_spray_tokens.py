import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sweep_fresh_spray_tokens as sweep  # noqa: E402


def test_run_sweep_covers_every_token_seed_pair_and_writes_csv(tmp_path):
    csv_path = tmp_path / "sweep.csv"
    rows = sweep.run_sweep(
        [2, 8], [1, 2], duration_s=60.0, num_festivaliers=10, beacon_count=2,
        mobility="poi", reply_probability=0.5, workers=2, csv_path=str(csv_path),
    )
    assert [(row["initial_tokens"], row["seed"]) for row in rows] == [(2, 1), (2, 2), (8, 1), (8, 2)]
    with open(csv_path, newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 4
    summary = sweep.summarize(rows)
    assert [(entry["initial_tokens"], entry["runs"]) for entry in summary] == [(2, 2), (8, 2)]


def test_build_config_size_sets_site_and_crowd():
    config = sweep.build_config(0, 1, 60.0, 200, "poi", 0.0, size="medium")
    assert config.num_festivaliers == 10000
    assert (config.area.width_m, config.area.height_m) == (205.0, 146.0)
    assert config.mobility.background_probability is not None


def test_main_rejects_size_with_a_different_num_festivaliers(tmp_path, capsys):
    with pytest.raises(SystemExit):
        sweep.main(["--size", "small", "--num-festivaliers", "10", "--archive-dir", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []
    assert "--size" in capsys.readouterr().err
