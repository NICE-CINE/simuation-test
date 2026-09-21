import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as main_module  # noqa: E402


def test_build_arg_parser_defaults():
    args = main_module.build_arg_parser().parse_args([])
    assert args.routing == "epidemic"
    assert args.beacons == 0
    assert args.beacon_placement == "grid"
    assert args.duration == 3600.0
    assert args.num_festivaliers == 10000
    assert args.seed == 42
    assert args.output == "rapport_simulation.txt"
    assert args.spray_initial_copies == 8


def test_routing_factories_cover_every_cli_choice():
    args = main_module.build_arg_parser().parse_args([])
    for name in ["epidemic", "spray_wait", "prophet", "beacon_priority"]:
        args.routing = name
        algo = main_module.ROUTING_FACTORIES[name](args)
        assert algo is not None


def test_build_config_applies_overrides():
    args = main_module.build_arg_parser().parse_args(
        ["--beacons", "3", "--duration", "60", "--num-festivaliers", "10", "--seed", "1"]
    )
    config = main_module.build_config(args)
    assert config.beacons.count == 3
    assert config.duration_s == 60.0
    assert config.num_festivaliers == 10
    assert config.random_seed == 1


def test_main_runs_end_to_end_and_writes_report(tmp_path, capsys):
    output_path = tmp_path / "report.txt"
    main_module.main(
        [
            "--routing", "beacon_priority",
            "--beacons", "3",
            "--duration", "60",
            "--num-festivaliers", "10",
            "--seed", "1",
            "--output", str(output_path),
        ]
    )
    assert output_path.exists()
    captured = capsys.readouterr()
    assert "RAPPORT DE SIMULATION" in captured.out
