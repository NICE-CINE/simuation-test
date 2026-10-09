import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sweep_band_fanout as sweep  # noqa: E402


def test_parse_variant_reads_typed_values():
    params = sweep.parse_variant("fanout=2,max_hops=5,band_low=0.1,band_high=0.9,purge_delivered=0")
    assert params == {
        "fanout": 2,
        "max_hops": 5,
        "band_low": 0.1,
        "band_high": 0.9,
        "purge_delivered": False,
    }


def test_parse_variant_empty_means_defaults():
    assert sweep.parse_variant("") == {}


@pytest.mark.parametrize("text", ["unknown=1", "fanout", "fanout=abc", "purge_delivered=2", "reachable_links=6"])
def test_parse_variant_rejects_bad_input(text):
    with pytest.raises(ValueError):
        sweep.parse_variant(text)


def test_build_algorithm_applies_band_and_flags():
    algo = sweep.build_algorithm({"fanout": 2, "band_low": 0.0, "band_high": 1.0, "purge_delivered": False}, seed=5)
    assert algo._fanout == 2
    assert algo._band == (0.0, 1.0)
    assert algo._purge_delivered is False
    assert sweep.build_algorithm({"band_high": 0.8}, seed=5)._band == (0.4, 0.8)


def test_variant_label_names_the_defaults():
    assert sweep.variant_label("") == "defaults"
    assert sweep.variant_label("fanout=2") == "fanout=2"


def test_default_variants_all_parse():
    assert "" in sweep.DEFAULT_VARIANTS
    for text in sweep.DEFAULT_VARIANTS:
        sweep.parse_variant(text)


def test_run_sweep_covers_every_variant_seed_pair_and_writes_csv(tmp_path):
    csv_path = tmp_path / "sweep.csv"
    rows = sweep.run_sweep(
        ["", "fanout=2"], [1, 2], duration_s=60.0, num_festivaliers=10, beacon_count=2,
        mobility="poi", reply_probability=0.5, workers=2, csv_path=str(csv_path),
    )
    assert [(row["variant"], row["seed"]) for row in rows] == [
        ("defaults", 1), ("defaults", 2), ("fanout=2", 1), ("fanout=2", 2),
    ]
    with open(csv_path, newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 4
    summary = sweep.summarize(rows)
    assert [(entry["variant"], entry["runs"]) for entry in summary] == [("defaults", 2), ("fanout=2", 2)]


def test_main_archives_csv_and_json_in_given_dir(tmp_path, capsys):
    sweep.main([
        "--variant", "fanout=2", "--seeds", "1", "--duration", "30", "--num-festivaliers", "10",
        "--beacon-count", "2", "--workers", "1", "--archive-dir", str(tmp_path),
    ])
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("_sweep_band_fanout.csv") for n in names)
    assert any(n.endswith("_sweep_band_fanout.json") for n in names)
    assert "fanout=2" in capsys.readouterr().out


def test_run_sweep_runs_duplicate_variants_once(tmp_path):
    rows = sweep.run_sweep(
        ["fanout=2", "fanout=2"], [1], duration_s=30.0, num_festivaliers=10, beacon_count=2, workers=1,
    )
    assert [row["variant"] for row in rows] == ["fanout=2"]
