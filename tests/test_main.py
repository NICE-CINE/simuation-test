import json
import random
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as main_module  # noqa: E402


def test_build_arg_parser_defaults():
    args = main_module.build_arg_parser().parse_args([])
    assert args.routing == "epidemic"
    assert args.mobility is None
    assert args.size is None
    assert args.beacons == 0
    assert args.beacon_placement == "grid"
    assert args.duration == 3600.0
    assert args.num_festivaliers is None
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
    for name in main_module.ROUTING_NAMES:
        assert main_module.build_routing(name, args.seed, args.spray_initial_copies) is not None


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
    archive_dir = tmp_path / "archives"
    main_module.main(
        [
            "--routing", "epidemic",
            "--duration", "30",
            "--num-festivaliers", "10",
            "--seed", "1",
            "--output", str(output_path),
            "--replay-html",
            "--archive-dir", str(archive_dir),
        ]
    )
    replays = list((archive_dir / "replay").glob("*_epidemic.html"))
    assert len(replays) == 1
    assert (archive_dir / f"{replays[0].stem}.txt").exists()
    assert "<canvas" in replays[0].read_text(encoding="utf-8")
    assert replays[0].with_suffix(".data.js").exists()
    assert "Replay HTML ecrit" in capsys.readouterr().out
    assert f'href="replay/{replays[0].name}"' in (archive_dir / "index.html").read_text(encoding="utf-8")
    assert not (tmp_path / "index.html").exists()


def test_replay_flags_default_to_a_light_replay():
    args = main_module.build_arg_parser().parse_args([])
    assert args.replay_frame_step == 5.0
    assert args.replay_max_messages == 100


def test_main_replay_flags_shape_the_replay_data(tmp_path):
    archive_dir = tmp_path / "archives"
    main_module.main(
        ["--routing", "epidemic", "--duration", "30", "--num-festivaliers", "10", "--seed", "1",
         "--cooldown", "0", "--replay-html", "--replay-frame-step", "10", "--replay-max-messages", "1",
         "--archive-dir", str(archive_dir)]
    )
    replay = next((archive_dir / "replay").glob("*_epidemic.html"))
    text = replay.with_suffix(".data.js").read_text(encoding="utf-8")
    data = json.loads(text[len("const DATA = "):].rstrip().rstrip(";"))
    times = [frame["time"] for frame in data["frames"]]
    assert times == [1, 11, 21]
    assert sum(1 for meta in data["messages"].values() if meta["full"]) <= 1


def test_main_does_not_write_replay_html_by_default(tmp_path):
    output_path = tmp_path / "report.txt"
    main_module.main(
        ["--duration", "30", "--num-festivaliers", "10", "--seed", "1", "--output", str(output_path),
         "--archive-dir", str(tmp_path / "archives")]
    )
    assert list(tmp_path.rglob("*.html")) == []


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
    assert main_module.build_routing(args.routing, args.seed)._ack_hint


def test_build_config_without_size_keeps_the_legacy_site():
    args = main_module.build_arg_parser().parse_args([])
    config = main_module.build_config(args)
    assert config.num_festivaliers == 4000
    assert (config.area.width_m, config.area.height_m) == (700.0, 500.0)
    assert config.mobility.points_of_interest == ()
    assert config.mobility.background_probability is None


def test_size_sets_festivaliers_area_and_crowd_layout():
    args = main_module.build_arg_parser().parse_args(["--size", "medium"])
    config = main_module.build_config(args)
    assert config.num_festivaliers == 10000
    assert (config.area.width_m, config.area.height_m) == (205.0, 146.0)
    assert len(config.mobility.points_of_interest) == 4
    assert config.mobility.background_probability == pytest.approx(0.30 / 0.85)
    assert args.mobility == "poi"


def test_size_with_explicit_random_waypoint_only_changes_count_and_area():
    args = main_module.build_arg_parser().parse_args(["--size", "small", "--mobility", "random_waypoint"])
    config = main_module.build_config(args)
    assert config.num_festivaliers == 4000
    assert config.mobility.points_of_interest == ()


def test_size_conflicts_with_a_different_num_festivaliers(capsys):
    with pytest.raises(SystemExit):
        main_module.main(["--size", "small", "--num-festivaliers", "10"])
    assert "--size" in capsys.readouterr().err


def test_size_rejects_unknown_names():
    with pytest.raises(SystemExit):
        main_module.build_arg_parser().parse_args(["--size", "gigantic"])


def test_cooldown_defaults_to_the_message_ttl_and_can_be_turned_off():
    parser = main_module.build_arg_parser()
    config = main_module.build_config(parser.parse_args([]))
    assert config.cooldown_s == config.traffic.message_ttl_s
    assert main_module.build_config(parser.parse_args(["--cooldown", "0"])).cooldown_s == 0.0
