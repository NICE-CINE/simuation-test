import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_algorithms  # noqa: E402


def test_run_matrix_covers_every_algorithm_with_and_without_beacons():
    rows = compare_algorithms.run_matrix(seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0)
    assert len(rows) == 2 * len(compare_algorithms.ALGORITHMS)
    combos = {(row["algorithm"], row["beacons"] > 0) for row in rows}
    expected = {(name, with_beacons) for name in compare_algorithms.ALGORITHMS for with_beacons in (False, True)}
    assert combos == expected
    for row in rows:
        assert 0.0 <= row["delivery_ratio"] <= 1.0


def test_run_matrix_parallel_workers_match_sequential_results():
    sequential = compare_algorithms.run_matrix(seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0, workers=1)
    parallel = compare_algorithms.run_matrix(seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0, workers=2)
    assert parallel == sequential


def test_run_matrix_writes_csv_incrementally(tmp_path):
    csv_path = tmp_path / "incremental.csv"
    rows = compare_algorithms.run_matrix(
        seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0, workers=2, csv_path=str(csv_path)
    )
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == len(rows)


def test_write_csv_produces_a_valid_file(tmp_path):
    rows = compare_algorithms.run_matrix(seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0)
    csv_path = tmp_path / "comparison.csv"
    compare_algorithms.write_csv(rows, str(csv_path))
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == len(rows)
    assert list(reader[0].keys()) == compare_algorithms.HEADERS


def test_main_archives_csv_and_params_named_after_date(tmp_path, capsys):
    archive_dir = tmp_path / "archives"
    compare_algorithms.main(
        ["--seed", "1", "--duration", "30", "--num-festivaliers", "10", "--beacon-count", "2",
         "--workers", "1", "--archive-dir", str(archive_dir)]
    )
    csvs = list(archive_dir.glob("*_comparaison.csv"))
    assert len(csvs) == 1
    with open(csvs[0], newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 2 * len(compare_algorithms.ALGORITHMS)
    params = json.loads(csvs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert params["cli"]["num_festivaliers"] == 10
    assert params["config"]["duration_s"] == 30.0
    assert params["config"]["cooldown_s"] == params["config"]["traffic"]["message_ttl_s"]


def test_run_matrix_with_poi_mobility_and_replies():
    rows = compare_algorithms.run_matrix(
        seeds=(1,), duration_s=60.0, num_festivaliers=10, beacon_count=2, cooldown_s=0.0, mobility="poi", reply_probability=0.5
    )
    assert len(rows) == 2 * len(compare_algorithms.ALGORITHMS)


def test_build_config_wires_followups_and_fix_failures():
    config = compare_algorithms.build_config(
        0, 1, 60.0, 10, followup_probability=0.3, gps_fix_failure=0.1
    )
    assert config.traffic.followup_probability == 0.3
    assert config.gps.fix_failure_probability == 0.1
    assert "tide_g2" in compare_algorithms.ALGORITHMS


def test_both_entry_points_build_from_the_shared_registry():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import main as main_module
    from festival_ble_sim.routing import registry

    assert compare_algorithms.ALGORITHMS == registry.ROUTING_NAMES
    assert main_module.build_routing is registry.build_routing is compare_algorithms.build_routing


def test_seeded_algorithms_receive_the_run_seed():
    from festival_ble_sim.routing.registry import build_routing

    for name in ("gossip_a", "tide", "tide_g", "tide_g2", "eco_sf", "band_fanout"):
        draws = {build_routing(name, seed)._rng.random() for seed in (1, 2)}
        assert len(draws) == 2, name


def test_build_config_size_sets_site_and_crowd():
    config = compare_algorithms.build_config(0, 1, 60.0, 200, "poi", size="small")
    assert config.num_festivaliers == 4000
    assert (config.area.width_m, config.area.height_m) == (130.0, 93.0)
    assert config.mobility.background_probability is not None


def test_main_rejects_size_with_a_different_num_festivaliers(tmp_path, capsys):
    with pytest.raises(SystemExit):
        compare_algorithms.main(["--size", "small", "--num-festivaliers", "10", "--archive-dir", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []
    assert "--size" in capsys.readouterr().err


def test_main_with_several_sizes_runs_one_comparison_per_size(tmp_path, monkeypatch):
    calls = []

    def fake_run_matrix(**kwargs):
        calls.append((kwargs["size"], kwargs["num_festivaliers"], kwargs["mobility"]))
        return [{"algorithm": "epidemic", "beacons": 0, "seed": 1, **{f: 0.5 for f in compare_algorithms.REPORT_FIELDS}}]

    monkeypatch.setattr(compare_algorithms, "run_matrix", fake_run_matrix)
    compare_algorithms.main([
        "--size", "small", "medium", "--algorithms", "epidemic", "--archive-dir", str(tmp_path),
        "--csv", str(tmp_path / "out.csv"),
    ])
    assert calls == [("small", 4000, "group"), ("medium", 10000, "group")]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert sum(n.endswith("_comparaison_small.csv") for n in names) == 1
    assert sum(n.endswith("_comparaison_medium.json") for n in names) == 1
    assert {"out_small.csv", "out_medium.csv"} <= set(names)


def test_summarize_gives_mean_and_student_ci95_per_algorithm_and_beacons():
    rows = [
        {"algorithm": "epidemic", "beacons": 0, "seed": seed, **{f: v for f in compare_algorithms.REPORT_FIELDS}}
        for seed, v in ((1, 0.4), (2, 0.6), (3, 0.5))
    ]
    (entry,) = compare_algorithms.summarize(rows)
    assert entry["runs"] == 3
    assert entry["delivery_ratio"] == pytest.approx(0.5)
    assert entry["delivery_ratio_ci95"] == pytest.approx(4.303 * 0.1 / 3 ** 0.5)


def test_main_with_several_seeds_writes_paired_runs_and_a_summary(tmp_path):
    compare_algorithms.main(
        ["--seeds", "1", "2", "--duration", "30", "--cooldown", "0", "--num-festivaliers", "10",
         "--beacon-count", "2", "--workers", "2", "--archive-dir", str(tmp_path)]
    )
    (runs_csv,) = [p for p in tmp_path.glob("*_comparaison.csv")]
    with open(runs_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert sorted({row["seed"] for row in rows}) == ["1", "2"]
    assert len(rows) == 2 * 2 * len(compare_algorithms.ALGORITHMS)
    (summary_csv,) = tmp_path.glob("*_comparaison_resume.csv")
    with open(summary_csv, encoding="utf-8") as f:
        summary = list(csv.DictReader(f))
    assert len(summary) == 2 * len(compare_algorithms.ALGORITHMS)
    assert {row["runs"] for row in summary} == {"2"}


def test_algorithms_option_runs_only_the_chosen_subset(tmp_path):
    compare_algorithms.main(
        ["--algorithms", "epidemic", "tide", "--seeds", "1", "--duration", "30", "--cooldown", "0",
         "--num-festivaliers", "10", "--beacon-count", "2", "--workers", "1", "--archive-dir", str(tmp_path)]
    )
    (runs_csv,) = tmp_path.glob("*_comparaison.csv")
    with open(runs_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(row["algorithm"], row["beacons"]) for row in rows] == [
        ("epidemic", "0"), ("epidemic", "2"), ("tide", "0"), ("tide", "2"),
    ]


def test_unknown_algorithm_is_rejected():
    with pytest.raises(SystemExit):
        compare_algorithms.main(["--algorithms", "nope"])


def test_main_refuses_to_override_the_beacon_count_and_writes_no_archive(tmp_path, capsys):
    with pytest.raises(SystemExit):
        compare_algorithms.main(["--set", "beacons.count=3", "--archive-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        compare_algorithms.main(["--set", "traffic.ttl=3", "--archive-dir", str(tmp_path)])
    assert "n'existe pas" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_build_config_applies_overrides():
    config = compare_algorithms.build_config(2, 1, 60.0, 10, overrides=("traffic.message_ttl_s=300",))
    assert config.traffic.message_ttl_s == 300.0 and config.cooldown_s == 300.0
