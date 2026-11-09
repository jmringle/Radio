"use strict";
// The meter page: readings arrive over a WebSocket about 10 times a second.

const BAR_MAX_DB = 60;       // the bar's full scale, dB over noise
const HISTORY = 600;         // 60 s at 10 readings/s
const $ = (id) => document.getElementById(id);
const history = [];
let recording = false;
let tone = null;             // {ctx, osc, gain} once the Tone button is pressed

function fmt(value) {
  return value === null || value === undefined ? "--" : value.toFixed(1);
}

function showError(text) {
  $("error").hidden = !text;
  $("error").textContent = text || "";
}

function showSettings(state) {
  const s = state.settings;
  $("freq").value = s.freq_mhz;
  $("gain").value = s.gain_db;
  $("att").value = s.attenuator_db;
  const used = state.gain_used !== null && state.gain_used !== s.gain_db ? ` (dongle uses ${state.gain_used} dB)` : "";
  $("tuned").textContent = `${s.freq_mhz.toFixed(4)} MHz, gain ${s.gain_db} dB${used}, attenuator ${s.attenuator_db} dB`;
  showRecording(state.recording);
  showSpots(state.spots);
}

function text(tag, content) {
  // textContent only, never HTML (README threat model T2).
  const el = document.createElement(tag);
  el.textContent = content;
  return el;
}

function showSpots(spots) {
  $("bearings").replaceChildren(...spots.map((s) => {
    const where = s.lat === null ? "no position" : `${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}`;
    const b = s.bearing;
    const li = text("li", `Spot ${s.id} (${where}): ` + (b ? `bearing ${b.heading}° ±${b.pm}° (${b.method})` : "no bearings yet"));
    const marks = document.createElement("ul");
    marks.replaceChildren(...s.marks.map((m) =>
      text("li", `${m.time.slice(11, 19)}Z  ${m.heading}°  level ${fmt(m.level_db)} dB, ${fmt(m.over_noise_db)} dB over noise`)));
    li.append(marks);
    return li;
  }));
  refreshMap();
}

async function newSpot(event) {
  event.preventDefault();
  try {
    const result = await post("/spot", { lat: $("lat").value, lon: $("lon").value });
    showSpots(result.spots);
    $("spot-message").textContent = `Spot ${result.spot.id} started. Bearings now belong to it.`;
  } catch (error) {
    $("spot-message").textContent = error.message;
  }
}

async function refreshMap() {
  try {
    drawMap(await (await fetch("/map")).json());
  } catch {
    $("map-text").textContent = "Couldn't load the map.";
  }
}

function drawMap(m) {
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  const style = getComputedStyle(document.documentElement);
  const color = (name) => style.getPropertyValue(name).trim();
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  $("map-text").textContent = m.text;
  if (!m.estimate) return;

  // Probability: one hue, clear to solid accent (sequential).
  const hex = color("--accent").replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const cells = new ImageData(m.size, m.size);
  m.grid.forEach((v, i) => cells.data.set([r, g, b, Math.round(v * 0.85)], i * 4));
  const off = new OffscreenCanvas(m.size, m.size);
  off.getContext("2d").putImageData(cells, 0, 0);
  ctx.drawImage(off, 0, 0, width, height);

  const px = (x) => ((x + m.half_m) / (2 * m.half_m)) * width;
  const py = (y) => ((m.half_m - y) / (2 * m.half_m)) * height;
  for (const s of m.spots) {  // bearing lines
    const rad = (s.heading * Math.PI) / 180;
    ctx.strokeStyle = color(s.reflection ? "--muted" : "--ink");
    ctx.lineWidth = 2;
    ctx.setLineDash(s.reflection ? [6, 6] : []);
    ctx.beginPath();
    ctx.moveTo(px(s.x), py(s.y));
    ctx.lineTo(px(s.x + Math.sin(rad) * 4 * m.half_m), py(s.y + Math.cos(rad) * 4 * m.half_m));
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.font = "600 14px 'Avenir Next', 'Helvetica Neue', sans-serif";
  for (const s of m.spots) {  // spot dots with a surface ring, labeled
    ctx.beginPath();
    ctx.arc(px(s.x), py(s.y), 6, 0, 2 * Math.PI);
    ctx.fillStyle = color("--ink");
    ctx.strokeStyle = color("--panel");
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
    ctx.fillText(String(s.id), px(s.x) + 9, py(s.y) - 9);
  }
  ctx.fillStyle = color("--ink");
  ctx.fillText("N ↑", 10, 22);
  // Scale bar: a round length about a quarter of the map.
  const target = m.half_m / 2;
  const meters = [100, 200, 500, 1000, 2000, 5000, 10000, 20000].reduce((a, c) => (c <= target ? c : a), 100);
  const bar = (meters / (2 * m.half_m)) * width;
  ctx.fillRect(10, height - 16, bar, 3);
  ctx.fillText(meters >= 1000 ? `${meters / 1000} km` : `${meters} m`, 10, height - 22);
}

async function markBearing(event) {
  event.preventDefault();
  try {
    const result = await post("/bearing", { heading: $("heading").value });
    showSpots(result.spots);
    $("bearing-message").textContent = `Marked ${result.bearing.heading}°.`;
  } catch (error) {
    $("bearing-message").textContent = error.message;
  }
}

function showRecording(name) {
  recording = Boolean(name);
  $("record").setAttribute("aria-pressed", String(recording));
  $("record").textContent = recording ? "Stop recording" : "Record";
  $("recording").textContent = recording ? `Recording to data/sessions/${name}` : "";
}

function showReading(r) {
  showError(null);
  $("over-noise").textContent = fmt(r.over_noise_db);
  $("level").textContent = fmt(r.level_db);
  $("peak").textContent = fmt(r.peak_db);
  $("noise").textContent = fmt(r.noise_db);
  const below = r.peak_db === null ? null : r.peak_db - r.level_db;
  $("below").textContent = fmt(below);
  $("overload").hidden = !r.overload;

  const share = (db) => Math.max(0, Math.min(1, db / BAR_MAX_DB)) * 100;
  $("bar-fill").style.width = `${share(r.over_noise_db)}%`;
  $("bar").setAttribute("aria-valuenow", r.over_noise_db.toFixed(0));
  // The peak level on the bar's scale: where the bar would reach at the peak, with today's noise.
  $("bar-peak").hidden = below === null;
  if (below !== null) $("bar-peak").style.left = `${share(r.over_noise_db + below)}%`;

  history.push(r.over_noise_db);
  if (history.length > HISTORY) history.shift();
  draw();
  if (tone) setTone(r.over_noise_db);
}

function draw() {
  const canvas = $("history");
  const ctx = canvas.getContext("2d");
  const style = getComputedStyle(document.documentElement);
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = style.getPropertyValue("--rule");
  ctx.lineWidth = 1;
  for (const db of [20, 40]) {  // guide lines
    const y = height - (db / BAR_MAX_DB) * height;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }
  ctx.strokeStyle = style.getPropertyValue("--ink");
  ctx.lineWidth = 2;
  ctx.beginPath();
  history.forEach((db, i) => {
    const x = width - (history.length - 1 - i) * (width / (HISTORY - 1));
    const y = height - Math.max(0, Math.min(1, db / BAR_MAX_DB)) * height;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// Pitch rises with signal: 200 Hz at 0 dB over noise, 1700 Hz at 60.
function setTone(db) {
  const hz = 200 + Math.max(0, Math.min(BAR_MAX_DB, db)) * 25;
  tone.osc.frequency.setTargetAtTime(hz, tone.ctx.currentTime, 0.05);
}

function toggleTone() {
  // Browsers only allow sound after a click, so the audio starts here, not on page load.
  if (tone) {
    tone.ctx.close();
    tone = null;
  } else {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    tone = { ctx, osc, gain };
    if (history.length) setTone(history[history.length - 1]);
  }
  $("tone").setAttribute("aria-pressed", String(Boolean(tone)));
  $("tone").textContent = tone ? "Tone on" : "Tone off";
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function applySettings(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    showSettings(await post("/settings", Object.fromEntries(form)));
    $("settings-message").textContent = "Applied.";
    history.length = 0;
  } catch (error) {
    $("settings-message").textContent = error.message;
  }
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.reading) showReading(message.reading);
    if (message.schedule) $("schedule").textContent = message.schedule.text;
    if ("advice" in message) {
      $("advice").hidden = !message.advice;
      $("advice").textContent = message.advice || "";
    }
    if (message.error) showError(message.error);
  };
  ws.onclose = () => {
    showError("Lost the connection to the meter. Is foxhunt still running? Retrying…");
    setTimeout(connect, 2000);
  };
}

document.addEventListener("DOMContentLoaded", async () => {
  $("settings").addEventListener("submit", applySettings);
  $("bearing-form").addEventListener("submit", markBearing);
  $("spot-form").addEventListener("submit", newSpot);
  $("tone").addEventListener("click", toggleTone);
  $("reset").addEventListener("click", () => post("/peak/reset", {}).catch((e) => showError(e.message)));
  $("record").addEventListener("click", async () => {
    try {
      showRecording((await post("/record", { on: !recording })).recording);
    } catch (error) {
      showError(error.message);
    }
  });
  try {
    showSettings(await (await fetch("/state")).json());
  } catch {
    showError("Couldn't reach the meter.");
  }
  connect();
});
