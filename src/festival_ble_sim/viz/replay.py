from __future__ import annotations
import json
from .history import SimulationHistory

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  body { font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 0; padding: 16px; }
  h1 { font-size: 16px; font-weight: 600; margin: 0 0 12px; }
  canvas { background: #1b1b1f; border: 1px solid #333; display: block; }
  .controls { display: flex; align-items: center; gap: 10px; margin-top: 10px; max-width: 900px; }
  .controls input[type=range] { flex: 1; }
  button { background: #2a2a30; color: #eee; border: 1px solid #444; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
  button:hover { background: #35353c; }
  .readout { font-variant-numeric: tabular-nums; min-width: 220px; }
  .legend { margin-top: 8px; font-size: 12px; color: #aaa; }
  .legend span { margin-right: 16px; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<canvas id="c"></canvas>
<div class="controls">
  <button id="playBtn">Play</button>
  <input id="slider" type="range" min="0" value="0" step="1">
  <span id="readout" class="readout"></span>
</div>
<div class="legend">
  <span><i class="dot" style="background:#4da3ff"></i>phone</span>
  <span><i class="dot" style="background:#ffb020"></i>beacon</span>
  <span><i class="dot" style="background:#3ddc84"></i>delivery this tick</span>
  <span style="color:#888">line = relay/delivery event in this tick's window</span>
</div>
<script>
const DATA = __DATA__;

const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const maxPixels = 800;
const scale = Math.min(maxPixels / DATA.area.width, maxPixels / DATA.area.height);
canvas.width = Math.max(1, DATA.area.width * scale);
canvas.height = Math.max(1, DATA.area.height * scale);

const beaconEntries = Object.entries(DATA.beacons);
const frames = DATA.frames;
const events = DATA.events;
const slider = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");
const readout = document.getElementById("readout");

slider.max = Math.max(0, frames.length - 1);

function eventsForFrame(i) {
  if (frames.length === 0) return [];
  const upper = frames[i].time;
  const lower = i > 0 ? frames[i - 1].time : -Infinity;
  return events.filter(e => e.time > lower && e.time <= upper);
}

function draw(i) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (frames.length === 0) {
    ctx.fillStyle = "#888";
    ctx.fillText("No recorded frames.", 10, 20);
    return;
  }
  const frame = frames[i];
  const positions = frame.positions;

  for (const [, [bx, by]] of beaconEntries) {
    ctx.fillStyle = "#ffb020";
    ctx.fillRect(bx * scale - 4, by * scale - 4, 8, 8);
  }

  const delivered = new Set();
  for (const e of eventsForFrame(i)) {
    if (e.delivered) delivered.add(e.to);
    const from = positions[e.from];
    const to = positions[e.to] || (DATA.beacons[e.to]);
    if (!from || !to) continue;
    ctx.strokeStyle = e.delivered ? "#3ddc84" : "#555";
    ctx.lineWidth = e.delivered ? 1.5 : 1;
    ctx.beginPath();
    ctx.moveTo(from[0] * scale, from[1] * scale);
    ctx.lineTo(to[0] * scale, to[1] * scale);
    ctx.stroke();
  }

  for (const [idStr, [x, y]] of Object.entries(positions)) {
    ctx.fillStyle = delivered.has(Number(idStr)) ? "#3ddc84" : "#4da3ff";
    ctx.beginPath();
    ctx.arc(x * scale, y * scale, delivered.has(Number(idStr)) ? 4 : 2.5, 0, 2 * Math.PI);
    ctx.fill();
  }

  readout.textContent = `t = ${frame.time.toFixed(1)}s — frame ${i + 1}/${frames.length} — ${Object.keys(positions).length} active nodes`;
}

let playing = false;
let timer = null;

function step() {
  let i = Number(slider.value);
  i = (i + 1) % frames.length;
  slider.value = i;
  draw(i);
}

playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.textContent = playing ? "Pause" : "Play";
  if (playing) {
    timer = setInterval(step, 120);
  } else {
    clearInterval(timer);
  }
});

slider.addEventListener("input", () => draw(Number(slider.value)));

draw(0);
</script>
</body>
</html>
"""


def render_replay_html(history: SimulationHistory, output_path: str, title: str = "Festival BLE Mesh - Replay") -> None:
    data = {
        "area": {"width": history.area_width_m, "height": history.area_height_m},
        "beacons": history.beacon_positions,
        "frames": [{"time": t, "positions": positions} for t, positions in history.position_snapshots],
        "events": history.events,
    }
    html = _HTML_TEMPLATE.replace("__TITLE__", title).replace("__DATA__", json.dumps(data))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
