from __future__ import annotations
import json
from .history import SimulationHistory

_MESSAGE_FIELDS = ("src", "dst", "created")

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  body { font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 0; padding: 16px; }
  h1 { font-size: 16px; font-weight: 600; margin: 0 0 12px; }
  h2 { font-size: 13px; font-weight: 600; margin: 0 0 6px; color: #ccc; }
  .layout { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
  canvas { background: #1b1b1f; border: 1px solid #333; display: block; }
  .controls { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
  .controls input[type=range] { flex: 1; }
  button, select { background: #2a2a30; color: #eee; border: 1px solid #444; border-radius: 4px; padding: 6px 12px; cursor: pointer; font: inherit; }
  button:hover { background: #35353c; }
  button:disabled { opacity: 0.4; cursor: default; }
  .readout { font-variant-numeric: tabular-nums; min-width: 220px; }
  .legend { margin-top: 8px; font-size: 12px; color: #aaa; max-width: 800px; }
  .legend span { margin-right: 16px; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  .side { width: 340px; display: flex; flex-direction: column; gap: 14px; }
  .box { background: #1b1b1f; border: 1px solid #333; border-radius: 6px; padding: 10px; }
  .box label { font-size: 12px; color: #aaa; display: block; margin-bottom: 6px; }
  #msgList { width: 100%; box-sizing: border-box; height: 190px; background: #111; color: #eee; border: 1px solid #333; font-size: 12px; font-variant-numeric: tabular-nums; }
  #msgList option { padding: 2px 4px; }
  #trackPanel { font-size: 12px; line-height: 1.5; }
  #trackPanel .muted { color: #888; }
  .btnrow { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
  .btnrow button { padding: 4px 9px; font-size: 12px; }
  #timeline { max-height: 200px; overflow-y: auto; font-size: 12px; font-variant-numeric: tabular-nums; }
  #timeline div { padding: 1px 4px; cursor: pointer; color: #666; border-radius: 3px; }
  #timeline div.past { color: #ddd; }
  #timeline div.win { color: #3ddc84; }
  #timeline div:hover { background: #2a2a30; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<div class="layout">
  <div>
    <canvas id="c"></canvas>
    <div class="controls">
      <button id="playBtn">Play</button>
      <select id="speed" title="Vitesse">
        <option value="480">x0.25</option><option value="240">x0.5</option><option value="120" selected>x1</option>
        <option value="60">x2</option><option value="30">x4</option>
      </select>
      <input id="slider" type="range" min="0" value="0" step="1">
      <span id="readout" class="readout"></span>
    </div>
    <div class="legend" id="legend"></div>
  </div>
  <div class="side">
    <div class="box">
      <h2>Suivre un message</h2>
      <label><input type="checkbox" id="onlyDelivered" checked> livrés seulement</label>
      <select id="msgList" size="10"></select>
    </div>
    <div class="box" id="trackPanel"><span class="muted">Choisis un message dans la liste pour suivre son trajet.</span></div>
  </div>
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
const messages = DATA.messages || {};
const slider = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");
const speedSel = document.getElementById("speed");
const readout = document.getElementById("readout");
const msgList = document.getElementById("msgList");
const onlyDelivered = document.getElementById("onlyDelivered");
const trackPanel = document.getElementById("trackPanel");
const legend = document.getElementById("legend");

slider.max = Math.max(0, frames.length - 1);

const GENERIC_LEGEND = `
  <span><i class="dot" style="background:#4da3ff"></i>phone</span>
  <span><i class="dot" style="background:#ffb020"></i>beacon</span>
  <span><i class="dot" style="background:#3ddc84"></i>delivery this tick</span>
  <span style="color:#888">line = relay/delivery event in this tick's window</span>`;
const TRACK_LEGEND = `
  <span><i class="dot" style="background:#3ddc84"></i>source</span>
  <span><i class="dot" style="background:#ff5d5d"></i>destinataire</span>
  <span><i class="dot" style="background:#4da3ff"></i>porte une copie</span>
  <span><i class="dot" style="background:#ffd23f"></i>nouveau relais</span>
  <span style="color:#888">trait vert = chemin livré, bleu = autres copies, pointillé orange = backhaul bornes, chiffre = saut</span>`;
legend.innerHTML = GENERIC_LEGEND;

function frameAt(t) {
  if (frames.length === 0) return 0;
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].time >= t) hi = mid; else lo = mid + 1;
  }
  return lo;
}

function posAt(f, id) {
  return frames[f].positions[id] || DATA.beacons[id] || null;
}

function eventsForFrame(i) {
  if (frames.length === 0) return [];
  const upper = frames[i].time;
  const lower = i > 0 ? frames[i - 1].time : -Infinity;
  return events.filter(e => e.time > lower && e.time <= upper);
}

const byMsg = {};
for (const e of events) {
  if (e.msg === undefined) continue;
  (byMsg[e.msg] = byMsg[e.msg] || []).push(e);
}

const msgInfos = Object.keys(byMsg).map(id => {
  const evs = byMsg[id];
  const meta = messages[id];
  const delivery = evs.find(e => e.delivered) || null;
  return {
    id: Number(id), src: meta.src, dst: meta.dst, created: meta.created, evs, delivery,
    hops: delivery ? delivery.hops : 0,
    latency: delivery ? delivery.time - meta.created : null,
  };
});
msgInfos.sort((a, b) => {
  if (!!a.delivery !== !!b.delivery) return a.delivery ? -1 : 1;
  return b.hops - a.hops || b.evs.length - a.evs.length || a.id - b.id;
});

let tracked = null;

function fillList() {
  const keepId = tracked ? tracked.info.id : null;
  msgList.innerHTML = "";
  for (const info of msgInfos) {
    if (onlyDelivered.checked && !info.delivery) continue;
    const opt = document.createElement("option");
    opt.value = info.id;
    const status = info.delivery
      ? `livré ${info.hops} saut${info.hops > 1 ? "s" : ""} en ${info.latency.toFixed(0)}s`
      : `non livré (${info.evs.length} relais)`;
    opt.textContent = `#${info.id}  ${info.src} → ${info.dst}  ${status}`;
    if (info.id === keepId) opt.selected = true;
    msgList.appendChild(opt);
  }
}

// The delivered path is rebuilt backwards from the delivery event: the relay that handed the message
// to the current holder has one hop less (same hop count if it was a beacon backhaul copy).
function winningPath(info) {
  const win = new Set();
  let cur = info.delivery;
  while (cur) {
    win.add(cur);
    if (cur.from === info.src) break;
    const wantedHops = cur.backhaul ? cur.hops : cur.hops - 1;
    const prev = cur;
    cur = info.evs.find(e => e.to === prev.from && e.hops === wantedHops && e.time <= prev.time && !win.has(e)) || null;
  }
  return win;
}

function selectMessage(id) {
  const info = msgInfos.find(m => m.id === Number(id));
  if (!info) return;
  const win = winningPath(info);
  const segs = info.evs.map(e => {
    const f = frameAt(e.time);
    return { e, a: posAt(f, e.from), b: posAt(f, e.to), win: win.has(e) };
  });
  tracked = { info, segs };
  legend.innerHTML = TRACK_LEGEND;
  renderTrackPanel();
  draw(Number(slider.value));
}

function clearSelection() {
  tracked = null;
  legend.innerHTML = GENERIC_LEGEND;
  trackPanel.innerHTML = '<span class="muted">Choisis un message dans la liste pour suivre son trajet.</span>';
  Array.from(msgList.options).forEach(o => { o.selected = false; });
  draw(Number(slider.value));
}

function seek(t) {
  const f = frameAt(t);
  slider.value = f;
  draw(f);
}

function renderTrackPanel() {
  const { info, segs } = tracked;
  const status = info.delivery
    ? `<b style="color:#3ddc84">livré</b> à t=${info.delivery.time.toFixed(0)}s en ${info.hops} saut${info.hops > 1 ? "s" : ""} (délai ${info.latency.toFixed(0)}s)`
    : `<b style="color:#ff8a5d">non livré</b> sur la durée du replay`;
  trackPanel.innerHTML = `
    <h2>Message #${info.id}</h2>
    <div>${info.src} → ${info.dst}, créé à t=${info.created.toFixed(0)}s</div>
    <div>${status}</div>
    <div id="live" class="muted"></div>
    <div class="btnrow">
      <button id="btnFollow">&#9654; Suivre depuis la création</button>
      <button id="btnDeliv"${info.delivery ? "" : " disabled"}>Aller à la livraison</button>
      <button id="btnClear">Désélectionner</button>
    </div>
    <h2>Chronologie</h2>
    <div id="timeline"></div>`;
  const tl = document.getElementById("timeline");
  segs.forEach((s, k) => {
    const row = document.createElement("div");
    const kind = s.e.backhaul ? "backhaul" : (s.e.delivered ? "livraison" : `saut ${s.e.hops}`);
    row.textContent = `${s.win ? "★ " : ""}t=${s.e.time.toFixed(0)}s  ${s.e.from} → ${s.e.to}  ${kind}`;
    row.dataset.k = k;
    row.addEventListener("click", () => seek(s.e.time));
    tl.appendChild(row);
  });
  document.getElementById("btnFollow").addEventListener("click", () => {
    seek(Math.max(0, info.created - 2));
    if (!playing) playBtn.click();
  });
  document.getElementById("btnDeliv").addEventListener("click", () => seek(info.delivery.time));
  document.getElementById("btnClear").addEventListener("click", clearSelection);
}

function updateTrackLive(i) {
  const live = document.getElementById("live");
  if (!live) return;
  const T = frames[i].time;
  const past = tracked.segs.filter(s => s.e.time <= T);
  if (T < tracked.info.created) {
    live.textContent = `Pas encore créé (création dans ${(tracked.info.created - T).toFixed(0)}s)`;
  } else {
    const holders = new Set([tracked.info.src]);
    let maxHops = 0;
    for (const s of past) { holders.add(s.e.to); maxHops = Math.max(maxHops, s.e.hops); }
    const done = past.some(s => s.e.delivered);
    live.textContent = `À cet instant : ${done ? "livré, " : ""}${holders.size} porteur${holders.size > 1 ? "s" : ""}, ${maxHops} saut${maxHops > 1 ? "s" : ""} max`;
  }
  const rows = document.getElementById("timeline").children;
  tracked.segs.forEach((s, k) => {
    rows[k].className = (s.e.time <= T ? "past " : "") + (s.win ? "win" : "");
  });
}

function drawBeacons() {
  for (const [, [bx, by]] of beaconEntries) {
    ctx.fillStyle = "#ffb020";
    ctx.fillRect(bx * scale - 4, by * scale - 4, 8, 8);
  }
}

function marker(pos, color, label) {
  if (!pos) return;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(pos[0] * scale, pos[1] * scale, 7, 0, 2 * Math.PI);
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.fillStyle = "#fff";
  ctx.font = "bold 11px system-ui";
  ctx.fillText(label, pos[0] * scale + 10, pos[1] * scale - 8);
}

function drawTracked(i) {
  const frame = frames[i];
  const positions = frame.positions;
  const T = frame.time;
  const lower = i > 0 ? frames[i - 1].time : -Infinity;
  const { info, segs } = tracked;

  for (const [, [x, y]] of Object.entries(positions)) {
    ctx.fillStyle = "#2d3a4d";
    ctx.beginPath();
    ctx.arc(x * scale, y * scale, 2, 0, 2 * Math.PI);
    ctx.fill();
  }
  drawBeacons();

  const past = segs.filter(s => s.e.time <= T);
  for (const s of past) {
    if (!s.a || !s.b) continue;
    const fresh = s.e.time > lower;
    ctx.setLineDash(s.e.backhaul ? [5, 4] : []);
    ctx.strokeStyle = fresh ? "#ffd23f" : (s.win ? "#3ddc84" : (s.e.backhaul ? "#ffb020" : "#4da3ff"));
    ctx.globalAlpha = s.win || fresh ? 1 : 0.55;
    ctx.lineWidth = s.win || fresh ? 3 : 1.5;
    ctx.beginPath();
    ctx.moveTo(s.a[0] * scale, s.a[1] * scale);
    ctx.lineTo(s.b[0] * scale, s.b[1] * scale);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
  ctx.font = "11px system-ui";
  for (const s of past) {
    if (!s.a || !s.b || s.e.backhaul || !(s.win || past.length <= 40)) continue;
    ctx.fillStyle = s.win ? "#3ddc84" : "#9cc4ff";
    ctx.fillText(String(s.e.hops), (s.a[0] + s.b[0]) / 2 * scale + 3, (s.a[1] + s.b[1]) / 2 * scale - 3);
  }

  if (T >= info.created) {
    const holders = new Set([info.src]);
    const fresh = new Set();
    for (const s of past) {
      holders.add(s.e.to);
      if (s.e.time > lower) fresh.add(s.e.to);
    }
    for (const id of holders) {
      const p = positions[id] || DATA.beacons[id];
      if (!p) continue;
      ctx.strokeStyle = fresh.has(id) ? "#ffd23f" : "#4da3ff";
      ctx.fillStyle = ctx.strokeStyle;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p[0] * scale, p[1] * scale, 6, 0, 2 * Math.PI);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(p[0] * scale, p[1] * scale, 3, 0, 2 * Math.PI);
      ctx.fill();
    }
  }

  const delivered = past.some(s => s.e.delivered);
  marker(positions[info.src] || DATA.beacons[info.src], "#3ddc84", `source ${info.src}`);
  marker(positions[info.dst] || DATA.beacons[info.dst], delivered ? "#ffd23f" : "#ff5d5d", delivered ? `reçu ! ${info.dst}` : `dest. ${info.dst}`);
  updateTrackLive(i);
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

  if (tracked) {
    drawTracked(i);
  } else {
    drawBeacons();

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

function restartTimer() {
  clearInterval(timer);
  if (playing) timer = setInterval(step, Number(speedSel.value));
}

playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.textContent = playing ? "Pause" : "Play";
  restartTimer();
});

speedSel.addEventListener("change", restartTimer);
slider.addEventListener("input", () => draw(Number(slider.value)));
msgList.addEventListener("change", () => selectMessage(msgList.value));
onlyDelivered.addEventListener("change", fillList);

fillList();
draw(0);
</script>
</body>
</html>
"""


def render_replay_html(history: SimulationHistory, output_path: str, title: str = "Festival BLE Mesh - Replay") -> None:
    messages = {}
    events = []
    for event in history.events:
        if "msg" in event:
            messages.setdefault(event["msg"], {"src": event["src"], "dst": event["dst"], "created": event["created"]})
            event = {k: v for k, v in event.items() if k not in _MESSAGE_FIELDS}
        events.append(event)
    data = {
        "area": {"width": history.area_width_m, "height": history.area_height_m},
        "beacons": history.beacon_positions,
        "frames": [{"time": t, "positions": positions} for t, positions in history.position_snapshots],
        "events": events,
        "messages": messages,
    }
    html = _HTML_TEMPLATE.replace("__TITLE__", title).replace("__DATA__", json.dumps(data))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
