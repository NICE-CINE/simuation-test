import json
import random
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as main_module  # noqa: E402


def test_build_arg_parser_defaults():
    args = main_module.build_arg_parser().parse_args([])
    assert args.routing == "epidemic"
    assert args.mobility == "random_waypoint"
    assert args.beacons == 0
    assert args.beacon_placement == "grid"
    assert args.duration == 3600.0
    assert args.num_festivaliers == 4000
    assert args.seed == 42
    assert args.output is None
    assert args.archive_dir == "archives"
    assert args.spray_initial_copies == 8
    assert args.churn is False
    assert tuple(args.churn_arrival_window_s) == (0.0, 1800.0)
    assert tuple(args.churn_session_duration_s) == (1800.0, 10800.0)


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
    for name in sorted(main_module.ROUTING_FACTORIES):
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


def test_build_config_defaults_poi_mobility_to_a_festival_layout_inside_the_area():
    args = main_module.build_arg_parser().parse_args(["--mobility", "poi"])
    config = main_module.build_config(args)
    pois = config.mobility.points_of_interest
    assert len(pois) == 4
    for poi in pois:
        assert 0 <= poi.x <= config.area.width_m
        assert 0 <= poi.y <= config.area.height_m
        assert poi.weight > 0
    assert max(pois, key=lambda p: p.weight) is pois[0]


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
            "--archive-dir", str(tmp_path / "archives"),
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
            "--archive-dir", str(tmp_path / "archives"),
        ]
    )
    assert replay_path.exists()
    assert "<canvas" in replay_path.read_text(encoding="utf-8")
    assert "Replay HTML ecrit" in capsys.readouterr().out


def test_main_does_not_write_replay_html_by_default(tmp_path):
    output_path = tmp_path / "report.txt"
    main_module.main(
        ["--duration", "30", "--num-festivaliers", "10", "--seed", "1", "--output", str(output_path),
         "--archive-dir", str(tmp_path / "archives")]
    )
    assert list(tmp_path.glob("*.html")) == []


def test_main_archives_report_and_params_named_after_date_and_algo(tmp_path):
    archive_dir = tmp_path / "archives"
    main_module.main(
        ["--routing", "prophet", "--duration", "30", "--num-festivaliers", "10", "--seed", "3",
         "--archive-dir", str(archive_dir)]
    )
    reports = list(archive_dir.glob("*_prophet.txt"))
    assert len(reports) == 1
    assert reports[0].name[:10].count("-") == 2
    assert "RAPPORT DE SIMULATION" in reports[0].read_text(encoding="utf-8")
    params = json.loads(reports[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert params["cli"]["routing"] == "prophet"
    assert params["config"]["random_seed"] == 3
    assert params["config"]["num_festivaliers"] == 10


def test_tide_g2_cli_wires_followups_and_fix_failures():
    args = main_module.build_arg_parser().parse_args(
        ["--routing", "tide_g2", "--followup-probability", "0.3", "--gps-fix-failure", "0.1"]
    )
    config = main_module.build_config(args)
    assert config.traffic.followup_probability == 0.3
    assert config.gps.fix_failure_probability == 0.1
    assert main_module.ROUTING_FACTORIES["tide_g2"](args)._ack_hint
