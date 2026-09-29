import csv
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
