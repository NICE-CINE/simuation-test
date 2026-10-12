import json
import re
from festival_ble_sim.viz.history import SimulationHistory
from festival_ble_sim.viz.replay import render_replay_html, write_replay_index


def _sample_history() -> SimulationHistory:
    history = SimulationHistory(area_width_m=100.0, area_height_m=100.0, tick_interval_s=1.0)
    history.beacon_positions[1] = (50.0, 50.0)
    history.position_snapshots.append((1.0, {2: (10.0, 10.0), 3: (20.0, 20.0)}))
    history.position_snapshots.append((2.0, {2: (12.0, 10.0), 3: (18.0, 22.0)}))
    history.events.append({"time": 2.0, "from": 2, "to": 3, "delivered": True})
    return history


def _message_history() -> SimulationHistory:
    history = _sample_history()
    events = []
    for msg_id in range(1, 7):
        created = float(msg_id)
        for k in range(5):
            events.append(
                {"time": created + k, "from": 2, "to": 3, "delivered": False, "msg": msg_id, "hops": k + 1,
                 "src": 2, "dst": 9, "created": created}
            )
        if msg_id % 2 == 1:
            events.append(
                {"time": created + 5, "from": 3, "to": 9, "delivered": True, "msg": msg_id, "hops": 6,
                 "src": 2, "dst": 9, "created": created}
            )
    events.sort(key=lambda e: e["time"])
    history.events = events
    return history


def _load_data(html_path) -> dict:
    text = html_path.with_suffix(".data.js").read_text(encoding="utf-8")
    prefix = "const DATA = "
    assert text.startswith(prefix)
    return json.loads(text[len(prefix):].rstrip().rstrip(";"))


def _decode_events(data: dict) -> list:
    return [
        {"time": t, "from": f, "to": to, "delivered": bool(flags & 1), "backhaul": bool(flags & 2), "hops": hops, "msg": msg}
        for t, f, to, flags, hops, msg in data["events"]
    ]


def _full_messages(data: dict) -> set:
    return {int(m) for m, meta in data["messages"].items() if meta["full"]}


def test_render_replay_html_writes_a_file(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<canvas" in content
    assert "<!DOCTYPE html>" in content


def test_render_replay_html_splits_data_into_a_sibling_js_file(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    content = output_path.read_text(encoding="utf-8")
    assert (tmp_path / "replay.data.js").exists()
    assert '<script src="replay.data.js"></script>' in content
    assert "const DATA = " not in content
    assert len(content) < 100_000


def test_render_replay_html_data_file_name_is_url_quoted(tmp_path):
    output_path = tmp_path / "re play.html"
    render_replay_html(_sample_history(), str(output_path))
    assert '<script src="re%20play.data.js"></script>' in output_path.read_text(encoding="utf-8")


def test_render_replay_html_embeds_matching_data(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    data = _load_data(output_path)
    assert data["area"] == {"width": 100.0, "height": 100.0}
    assert data["beacons"] == {"1": [50.0, 50.0]}
    assert len(data["frames"]) == 2
    assert data["frames"][0] == {"time": 1, "ids": [2, 3], "xy": [100, 100, 200, 200]}
    assert data["frames"][1] == {"time": 2, "xy": [120, 100, 180, 220]}
    assert _decode_events(data) == [
        {"time": 2, "from": 2, "to": 3, "delivered": True, "backhaul": False, "hops": 0, "msg": -1}
    ]


def test_render_replay_html_repeats_ids_only_when_they_change(tmp_path):
    history = _sample_history()
    history.position_snapshots.append((3.0, {2: (12.0, 10.0)}))
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path))
    frames = _load_data(output_path)["frames"]
    assert "ids" not in frames[1]
    assert frames[2]["ids"] == [2]


def test_render_replay_html_data_file_is_line_oriented(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_message_history(), str(output_path))
    lines = output_path.with_suffix(".data.js").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 10
    assert max(len(line) for line in lines) < 1000


def test_render_replay_html_uses_custom_title(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path), title="Run #1")
    content = output_path.read_text(encoding="utf-8")
    assert "<title>Run #1</title>" in content
    assert "<h1>Run #1</h1>" in content


def test_render_replay_html_handles_empty_history(tmp_path):
    history = SimulationHistory(area_width_m=100.0, area_height_m=100.0, tick_interval_s=1.0)
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path))
    data = _load_data(output_path)
    assert data["frames"] == []
    assert data["events"] == []


def test_render_replay_html_embeds_message_index_built_from_events(tmp_path):
    history = _sample_history()
    history.events = [
        {"time": 1.0, "from": 2, "to": 3, "delivered": False, "msg": 7, "hops": 1, "src": 2, "dst": 9, "created": 0.5},
        {"time": 2.0, "from": 3, "to": 9, "delivered": True, "msg": 7, "hops": 2, "src": 2, "dst": 9, "created": 0.5},
        {"time": 2.0, "from": 3, "to": 1, "delivered": False, "msg": 8, "hops": 1, "src": 3, "dst": 2, "created": 1.5},
    ]
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path))
    data = _load_data(output_path)
    assert data["messages"]["7"] == {"src": 2, "dst": 9, "created": 0.5, "full": True}
    assert data["messages"]["8"] == {"src": 3, "dst": 2, "created": 1.5, "full": True}
    assert _decode_events(data)[1] == {
        "time": 2, "from": 3, "to": 9, "delivered": True, "backhaul": False, "hops": 2, "msg": 7
    }


def test_render_replay_html_flags_backhaul_events(tmp_path):
    history = _sample_history()
    history.events = [
        {"time": 1.0, "from": 1, "to": 4, "delivered": False, "msg": 7, "hops": 1, "src": 2, "dst": 9,
         "created": 0.5, "backhaul": True},
    ]
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path))
    event = _decode_events(_load_data(output_path))[0]
    assert event["backhaul"] and not event["delivered"]


def test_render_replay_html_caps_fully_recorded_messages_and_keeps_every_delivery(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_message_history(), str(output_path), max_messages=2)
    data = _load_data(output_path)
    events = _decode_events(data)
    assert len(_full_messages(data)) == 2
    assert {e["msg"] for e in events if e["delivered"]} == {1, 3, 5}
    for msg_id, meta in data["messages"].items():
        count = sum(1 for e in events if e["msg"] == int(msg_id))
        assert count == (6 if meta["full"] else 1)
    assert "2" not in data["messages"] and "4" not in data["messages"]


def test_render_replay_html_sampling_spreads_messages_over_time(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_message_history(), str(output_path), max_messages=2)
    assert _full_messages(_load_data(output_path)) == {1, 5}


def test_render_replay_html_fills_sample_with_undelivered_messages(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_message_history(), str(output_path), max_messages=5)
    full = _full_messages(_load_data(output_path))
    assert {1, 3, 5} <= full
    assert len(full) == 5


def test_render_replay_html_keeps_all_messages_under_the_cap(tmp_path):
    history = _message_history()
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path), max_messages=100)
    data = _load_data(output_path)
    assert all(meta["full"] for meta in data["messages"].values())
    assert len(data["events"]) == len(history.events)


def test_render_replay_html_has_message_tracking_panel(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    content = output_path.read_text(encoding="utf-8")
    assert 'id="msgList"' in content
    assert 'id="trackPanel"' in content


def test_write_replay_index_lists_replays_newest_first(tmp_path):
    replay_dir = tmp_path / "archives" / "replay"
    replay_dir.mkdir(parents=True)
    for name in ("2026-10-11_09-00-00_epidemic", "2026-10-12_10-30-00_tide_g2", "2026-10-12_08-00-00_a<b"):
        (replay_dir / f"{name}.html").write_text("x", encoding="utf-8")
    (replay_dir / "2026-10-12_10-30-00_tide_g2.data.js").write_text("y" * 2_000_000, encoding="utf-8")
    index_path = tmp_path / "index.html"
    write_replay_index(str(replay_dir), str(index_path))
    html = index_path.read_text(encoding="utf-8")
    assert "Replays (3)" in html
    hrefs = re.findall(r'href="([^"]+)"', html)
    assert hrefs == [
        "archives/replay/2026-10-12_10-30-00_tide_g2.html",
        "archives/replay/2026-10-12_08-00-00_a%3Cb.html",
        "archives/replay/2026-10-11_09-00-00_epidemic.html",
    ]
    assert "<td>10:30:00</td>" in html
    assert ">tide_g2</a>" in html
    assert ">a&lt;b</a>" in html
    assert "<td>2.0 Mo</td>" in html
