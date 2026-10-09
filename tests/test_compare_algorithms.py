import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_algorithms  # noqa: E402


def test_run_matrix_covers_every_algorithm_with_and_without_beacons():
    rows = compare_algorithms.run_matrix(seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2)
    assert len(rows) == 2 * len(compare_algorithms.ALGORITHMS)
    combos = {(row["algorithm"], row["beacons"] > 0) for row in rows}
    expected = {(name, with_beacons) for name in compare_algorithms.ALGORITHMS for with_beacons in (False, True)}
    assert combos == expected
    for row in rows:
        assert 0.0 <= row["delivery_ratio"] <= 1.0


def test_run_matrix_parallel_workers_match_sequential_results():
    sequential = compare_algorithms.run_matrix(seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2, workers=1)
    parallel = compare_algorithms.run_matrix(seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2, workers=2)
    assert parallel == sequential


def test_run_matrix_writes_csv_incrementally(tmp_path):
    csv_path = tmp_path / "incremental.csv"
    rows = compare_algorithms.run_matrix(
        seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2, workers=2, csv_path=str(csv_path)
    )
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == len(rows)


def test_write_csv_produces_a_valid_file(tmp_path):
    rows = compare_algorithms.run_matrix(seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2)
    csv_path = tmp_path / "comparison.csv"
    compare_algorithms.write_csv(rows, str(csv_path))
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == len(rows)
    assert set(reader[0].keys()) == {"algorithm", "beacons", *compare_algorithms.REPORT_FIELDS}


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


def test_run_matrix_with_poi_mobility_and_replies():
    rows = compare_algorithms.run_matrix(
        seed=1, duration_s=60.0, num_festivaliers=10, beacon_count=2, mobility="poi", reply_probability=0.5
    )
    assert len(rows) == 2 * len(compare_algorithms.ALGORITHMS)


def test_build_config_wires_followups_and_fix_failures():
    config = compare_algorithms.build_config(
        0, 1, 60.0, 10, followup_probability=0.3, gps_fix_failure=0.1
    )
    assert config.traffic.followup_probability == 0.3
    assert config.gps.fix_failure_probability == 0.1
    assert "tide_g2" in compare_algorithms.ALGORITHMS


def test_geo_spray_focus_is_registered_in_both_scripts():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import main as main_module

    assert "geo_spray_focus" in compare_algorithms.ALGORITHMS
    assert "geo_spray_focus" in main_module.ROUTING_FACTORIES


def test_build_config_uses_the_default_area_unless_told_otherwise():
    default = compare_algorithms.build_config(0, 1, 60.0, 10)
    assert (default.area.width_m, default.area.height_m) == (700.0, 500.0)
    resized = compare_algorithms.build_config(0, 1, 60.0, 10, area_width_m=1400.0, area_height_m=1000.0)
    assert (resized.area.width_m, resized.area.height_m) == (1400.0, 1000.0)
    only_width = compare_algorithms.build_config(0, 1, 60.0, 10, area_width_m=900.0)
    assert (only_width.area.width_m, only_width.area.height_m) == (900.0, 500.0)


def test_resized_area_moves_pois_with_it():
    config = compare_algorithms.build_config(
        4, 1, 60.0, 10, mobility="poi", area_width_m=1400.0, area_height_m=1000.0
    )
    assert max(poi.x for poi in config.mobility.points_of_interest) > 700.0


def test_main_with_area_archives_the_resized_config(tmp_path):
    archive_dir = tmp_path / "archives"
    compare_algorithms.main(
        ["--area-width", "300", "--area-height", "200", "--duration", "30", "--num-festivaliers", "10",
         "--beacon-count", "2", "--workers", "1", "--archive-dir", str(archive_dir)]
    )
    csvs = list(archive_dir.glob("*_comparaison.csv"))
    params = json.loads(csvs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert params["config"]["area"] == {"width_m": 300.0, "height_m": 200.0}
