import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as main_module  # noqa: E402


def test_build_arg_parser_defaults():
    args = main_module.build_arg_parser().parse_args([])
    assert args.routing == "epidemic"
    assert args.mobility == "random_waypoint"
    assert args.beacons == 0
    assert args.beacon_placement == "grid"
    assert args.duration == 3600.0
    assert args.num_festivaliers == 10000
    assert args.seed == 42
    assert args.output == "rapport_simulation.txt"
    assert args.spray_initial_copies == 8
    assert args.churn is False
    assert tuple(args.churn_arrival_window_s) == (0.0, 0.0)
    assert tuple(args.churn_session_duration_s) == (600.0, 3600.0)


def test_build_config_wires_churn_flags():
    args = main_module.build_arg_parser().parse_args(
        ["--churn", "--churn-arrival-window-s", "0", "50", "--churn-session-duration-s", "10", "20"]
    )
    config = main_module.build_config(args)
    assert config.churn.enabled is True
    assert config.churn.arrival_window_s == (0.0, 50.0)
    assert config.churn.session_duration_range_s == (10.0, 20.0)


def test_build_config_churn_disabled_by_default():
    args = main_module.build_arg_parser().parse_args([])
    config = main_module.build_config(args)
    assert config.churn.enabled is False


def test_routing_factories_cover_every_cli_choice():
    args = main_module.build_arg_parser().parse_args([])
    for name in ["epidemic", "spray_wait", "prophet", "beacon_priority", "dasfv"]:
        args.routing = name
        algo = main_module.ROUTING_FACTORIES[name](args)
        assert algo is not None


def test_mobility_factories_cover_every_cli_choice():
    for name in ["random_waypoint", "poi"]:
        args = main_module.build_arg_parser().parse_args(["--mobility", name])
        config = main_module.build_config(args)
        factory = main_module.MOBILITY_FACTORIES[name](config)
        mobility = factory(random.Random(0))
        assert mobility is not None


def test_build_config_defaults_poi_mobility_to_a_center_main_stage():
    args = main_module.build_arg_parser().parse_args(["--mobility", "poi"])
    config = main_module.build_config(args)
    assert len(config.mobility.points_of_interest) == 1
    poi = config.mobility.points_of_interest[0]
    assert poi.x == pytest.approx(config.area.width_m / 2)
    assert poi.y == pytest.approx(config.area.height_m / 2)


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


def test_main_writes_replay_html_when_requested(tmp_path, capsys):
    output_path = tmp_path / "report.txt"
    replay_path = tmp_path / "replay.html"
    main_module.main(
        [
            "--routing", "epidemic",
            "--duration", "30",
            "--num-festivaliers", "10",
            "--seed", "1",
            "--output", str(output_path),
            "--replay-html", str(replay_path),
        ]
    )
    assert replay_path.exists()
    assert "<canvas" in replay_path.read_text(encoding="utf-8")
    assert "Replay HTML ecrit" in capsys.readouterr().out


def test_main_does_not_write_replay_html_by_default(tmp_path):
    output_path = tmp_path / "report.txt"
    main_module.main(
        ["--duration", "30", "--num-festivaliers", "10", "--seed", "1", "--output", str(output_path)]
    )
    assert list(tmp_path.glob("*.html")) == []
