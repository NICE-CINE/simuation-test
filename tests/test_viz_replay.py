import json
import re
from festival_ble_sim.viz.history import SimulationHistory
from festival_ble_sim.viz.replay import render_replay_html


def _sample_history() -> SimulationHistory:
    history = SimulationHistory(area_width_m=100.0, area_height_m=100.0, tick_interval_s=1.0)
    history.beacon_positions[1] = (50.0, 50.0)
    history.position_snapshots.append((1.0, {2: (10.0, 10.0), 3: (20.0, 20.0)}))
    history.position_snapshots.append((2.0, {2: (12.0, 10.0), 3: (18.0, 22.0)}))
    history.events.append({"time": 2.0, "from": 2, "to": 3, "delivered": True})
    return history


def _extract_embedded_data(html: str) -> dict:
    match = re.search(r"^const DATA = (\{.*\});$", html, re.MULTILINE)
    assert match is not None
    return json.loads(match.group(1))


def test_render_replay_html_writes_a_file(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "<canvas" in content
    assert "<!DOCTYPE html>" in content


def test_render_replay_html_embeds_matching_data(tmp_path):
    history = _sample_history()
    output_path = tmp_path / "replay.html"
    render_replay_html(history, str(output_path))
    data = _extract_embedded_data(output_path.read_text(encoding="utf-8"))
    assert data["area"] == {"width": 100.0, "height": 100.0}
    assert data["beacons"] == {"1": [50.0, 50.0]}
    assert len(data["frames"]) == 2
    assert data["frames"][0]["time"] == 1.0
    assert data["frames"][0]["positions"] == {"2": [10.0, 10.0], "3": [20.0, 20.0]}
    assert data["events"] == [{"time": 2.0, "from": 2, "to": 3, "delivered": True}]


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
    data = _extract_embedded_data(output_path.read_text(encoding="utf-8"))
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
    data = _extract_embedded_data(output_path.read_text(encoding="utf-8"))
    assert data["messages"]["7"] == {"src": 2, "dst": 9, "created": 0.5}
    assert data["messages"]["8"] == {"src": 3, "dst": 2, "created": 1.5}
    assert data["events"][1] == {"time": 2.0, "from": 3, "to": 9, "delivered": True, "msg": 7, "hops": 2}


def test_render_replay_html_has_message_tracking_panel(tmp_path):
    output_path = tmp_path / "replay.html"
    render_replay_html(_sample_history(), str(output_path))
    content = output_path.read_text(encoding="utf-8")
    assert 'id="msgList"' in content
    assert 'id="trackPanel"' in content
