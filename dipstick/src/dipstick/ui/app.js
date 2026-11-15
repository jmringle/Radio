// The app's page. It calls Python through pywebview's bridge (window.pywebview.api) and shows
// what comes back: the report as text, the plots as SVG drawn by dipstick's own code.
"use strict";

const $ = (id) => document.getElementById(id);
const POINTS = 101;
const CHECK_EVERY_MS = 2000;  // how often to look for the NanoVNA (reads the port list only)
const LIVE_PAUSE_MS = 300;    // breathing room between live passes
let live = false;             // true while live mode runs; Stop sets it false

function ready() {
  window.pywebview.api.bands().then((bands) => {
    const select = $("band");
    const choose = document.createElement("option");
    choose.value = "";
    choose.textContent = "Choose a band";
    select.append(choose);
    for (const band of bands) {
      const option = document.createElement("option");
      option.value = option.textContent = band;
      select.append(option);
    }
    select.value = "";  // or type a target: Python works out its band
    $("sweep").disabled = $("live").disabled = false;  // only now can a sweep reach Python
  });
  checkConnection();
  setInterval(checkConnection, CHECK_EVERY_MS);
}

async function checkConnection() {
  try {
    const answer = await window.pywebview.api.nanovna();
    $("connection").textContent = answer.text;
    $("connection").className = answer.connected ? "connected" : "missing";
  } catch (error) {
    $("connection").textContent = `Couldn't check for the NanoVNA: ${error}`;
    $("connection").className = "missing";
  }
}

async function sweepOnce() {
  try {
    const answer = await window.pywebview.api.sweep($("band").value, $("target").value, POINTS);
    show(answer);
    return answer.ok;
  } catch (error) {
    show({ ok: false, error: `Couldn't reach dipstick's Python side: ${error}` });
    return false;
  }
}

function lock(locked) {
  for (const id of ["band", "target", "sweep"]) $(id).disabled = locked;
}

function show(answer) {
  $("error").textContent = answer.ok ? "" : answer.error;
  if (answer.ok) $("band").value = answer.band;  // the band actually swept
  $("report").textContent = answer.ok ? answer.report : "";  // text, never markup
  // The SVG comes from dipstick's own plot code, not from the NanoVNA or anything typed.
  $("swr").innerHTML = answer.ok ? answer.swr_svg : "";
  $("smith").innerHTML = answer.ok ? answer.smith_svg : "";
}

$("controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  // A disabled submit button also blocks Enter in the target field, so one sweep runs at a time.
  $("sweep").disabled = $("live").disabled = true;
  $("status").textContent = "Sweeping…";
  await sweepOnce();
  $("sweep").disabled = $("live").disabled = false;
  $("status").textContent = "";
});

// Live: sweep, show, sweep again, until Stop or an error. Stop doesn't cut a pass off halfway:
// each pass puts the NanoVNA's settings back at its end, so the loop finishes the pass first.
$("live").addEventListener("click", async () => {
  const button = $("live");
  if (live) {
    live = false;
    button.textContent = "Stopping…";
    button.disabled = true;
    return;
  }
  live = true;
  lock(true);
  button.textContent = "Stop";
  for (let pass = 1; live; pass++) {
    $("status").textContent = `Live: pass ${pass}`;
    if (!(await sweepOnce())) break;  // the error is on the page; don't keep trying
    await new Promise((resolve) => setTimeout(resolve, LIVE_PAUSE_MS));
  }
  live = false;
  lock(false);
  button.textContent = "Live";
  button.disabled = false;
  $("status").textContent = "";
});

// pywebview creates window.pywebview.api as an empty object first, adds the functions later, then
// fires "pywebviewready" (its js/api.js and js/finish.js). So check for a function, not the object.
if (typeof window.pywebview?.api?.bands === "function") ready();
else window.addEventListener("pywebviewready", ready, { once: true });
