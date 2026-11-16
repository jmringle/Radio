// The app's page. It calls Python through pywebview's bridge (window.pywebview.api) and shows
// what comes back: the report as text, the plots as SVG drawn by dipstick's own code.
"use strict";

const $ = (id) => document.getElementById(id);
const POINTS = 101;
const CHECK_EVERY_MS = 2000;  // how often to look for the NanoVNA (reads the port list only)
const LIVE_PAUSE_MS = 300;    // breathing room between live passes
let live = false;             // true while live mode runs; Stop sets it false
let pythonReady = false;      // the bridge's functions have arrived

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
    $("cal-band").append(...[...select.options].map((option) => option.cloneNode(true)));
    $("cal-band").value = "";
    $("sweep").disabled = $("live").disabled = false;  // only now can a sweep reach Python
    pythonReady = true;
    allowCableCheck();
    showCalibrationStep();
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

// Asks Python and shows the answer; true if it worked.
async function ask(call) {
  try {
    const answer = await call();
    show(answer);
    return answer.ok;
  } catch (error) {
    show({ ok: false, error: `Couldn't reach dipstick's Python side: ${error}` });
    return false;
  }
}

const sweepOnce = () => ask(() => window.pywebview.api.sweep($("band").value, $("target").value, POINTS));

function lock(locked) {
  for (const id of ["band", "target", "sweep"]) $(id).disabled = locked;
}

// One NanoVNA: while anything sweeps, the other tab can't be opened. Partway through a calibration
// the NanoVNA's own calibration is reset, so a sweep would be uncorrected but look normal: only the
// Calibrate tab stays open until the load step finishes (or the calibration is cancelled).
function running(on) {
  const calibrating = calStep !== "open";
  for (const tab of tabs) tab.disabled = on || (calibrating && tab !== $("tab-calibrate"));
}

function show(answer) {
  $("error").textContent = answer.ok ? "" : answer.error;
  if (answer.ok && answer.band) $("band").value = answer.band;  // the band actually swept
  // A band other than this session's calibration: the reading isn't calibrated for it.
  const note = answer.ok && answer.band && calibratedBand && answer.band !== calibratedBand
    ? `Note: the NanoVNA was calibrated for ${calibratedBand} on the Calibrate tab, not for ` +
      `${answer.band}, so this reading isn't calibrated for this band (unless you've switched the ` +
      `NanoVNA off and on since, which goes back to its saved calibration). Calibrate ${answer.band} ` +
      "for a reading you can trust.\n\n"
    : "";
  $("report").textContent = answer.ok ? note + answer.report : "";  // text, never markup
  // The SVG comes from dipstick's own plot code, not from the NanoVNA or anything typed.
  $("swr").innerHTML = answer.ok ? answer.swr_svg || "" : "";  // a cable has no SWR plot
  $("smith").innerHTML = answer.ok ? answer.smith_svg : "";
}

$("controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  // A disabled submit button also blocks Enter in the target field, so one sweep runs at a time.
  $("sweep").disabled = $("live").disabled = true;
  running(true);
  $("status").textContent = "Sweeping…";
  await sweepOnce();
  $("sweep").disabled = $("live").disabled = false;
  running(false);
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
  running(true);
  button.textContent = "Stop";
  for (let pass = 1; live; pass++) {
    $("status").textContent = `Live: pass ${pass}`;
    if (!(await sweepOnce())) break;  // the error is on the page; don't keep trying
    await new Promise((resolve) => setTimeout(resolve, LIVE_PAUSE_MS));
  }
  live = false;
  lock(false);
  running(false);
  button.textContent = "Live";
  button.disabled = false;
  $("status").textContent = "";
});

// --- tabs: Antenna (band sweeps), Cable and Calibrate -----------------------------------------
const tabs = [$("tab-antenna"), $("tab-cable"), $("tab-calibrate")];

function selectTab(tab) {
  if (tab.getAttribute("aria-selected") === "true") return;
  for (const each of tabs) {
    const selected = each === tab;
    each.setAttribute("aria-selected", String(selected));
    each.tabIndex = selected ? 0 : -1;  // roving tabindex: Tab reaches only the selected tab
    $(each.getAttribute("aria-controls")).hidden = !selected;
  }
  // A band's results aren't this cable's (or the other way round), and the box is confirmed afresh.
  show({ ok: true, report: "", smith_svg: "" });
  $("no-antenna").checked = false;
  allowCableCheck();
}

for (const tab of tabs) {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    // Skip shut tabs: the arrow keys mustn't open what clicking can't.
    for (let i = 1; i < tabs.length; i++) {
      const next = tabs[(tabs.indexOf(tab) + step * i + tabs.length * i) % tabs.length];
      if (next.disabled) continue;
      selectTab(next);
      next.focus();
      return;
    }
  });
}

// --- the cable check: only with "No antenna connected" ticked, cleared after every check -------
function allowCableCheck() {
  $("check-cable").disabled = !(pythonReady && $("no-antenna").checked);
}

$("no-antenna").addEventListener("change", allowCableCheck);

$("cable-controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  const fields = ["no-antenna", "vf", "length", "max-length", "check-cable"];
  for (const id of fields) $(id).disabled = true;
  running(true);
  $("status").textContent = "Checking the cable…";
  await ask(() => window.pywebview.api.cable($("no-antenna").checked, $("vf").value, $("length").value,
                                              $("max-length").value));
  $("no-antenna").checked = false;  // the antenna might be back on by the next check
  for (const id of fields) $(id).disabled = false;
  allowCableCheck();
  running(false);
  $("status").textContent = "";
});

// --- calibrating: open, short, load, in that order, over one band ------------------------------
const CAL_STEPS = {
  open: "Step 1 of 3: screw the open standard onto the port. An open reflects all of the signal straight " +
        "back, in step: it shows the NanoVNA what nothing connected looks like at its connector.",
  short: "Step 2 of 3: swap it for the short standard. A short also reflects all of the signal, but " +
         "turned upside down (inverted): the opposite side of the Smith chart.",
  load: "Step 3 of 3: swap it for the load standard (50 ohms). A load takes in all of the signal and " +
        "reflects none: a perfect match, SWR 1.0, the middle of the Smith chart.",
};
let calStep = "open";  // the next standard to measure
let calDone = "";      // the band just calibrated, until another calibration starts
let calibratedBand = "";  // the band the NanoVNA holds this session's calibration for, until the next open resets it
const PARTWAY = " The other tabs open again after the load step. To stop partway, set the band back to " +
  "Choose a band and switch the NanoVNA off and on (it goes back to its saved calibration).";

function showCalibrationStep() {
  $("cal-step").textContent = `Measure ${calStep}`;
  $("cal-step").disabled = !(pythonReady && $("cal-band").value);
  $("cal-instruction").textContent = calDone && calStep === "open"
    ? `Calibrated for ${calDone}. Put your antenna back on and sweep ${calDone} on the Antenna tab. The ` +
      "calibration lasts until you switch the NanoVNA off and on, which goes back to its saved one."
    : $("cal-band").value ? CAL_STEPS[calStep] + (calStep === "open" ? "" : PARTWAY)
    : "Choose the band you'll measure.";
}

$("cal-band").addEventListener("change", () => {
  calStep = "open";  // a calibration covers one band: another band starts over
  calDone = "";
  running(false);    // a cancelled calibration opens the other tabs again
  showCalibrationStep();
});

$("cal-controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  const band = $("cal-band").value;
  $("cal-step").disabled = $("cal-band").disabled = true;
  running(true);
  $("status").textContent = `Measuring the ${calStep} standard…`;
  try {
    const answer = await window.pywebview.api.calibrate(band, calStep);
    $("error").textContent = answer.ok ? "" : answer.error;
    if (answer.ok) {
      if (calStep === "open") calibratedBand = "";  // open reset the NanoVNA's calibration
      if (!answer.next) calibratedBand = band;
      calDone = answer.next ? "" : band;
      calStep = answer.next || "open";
    }
  } catch (error) {
    $("error").textContent = `Couldn't reach dipstick's Python side: ${error}`;
  }
  $("cal-band").disabled = false;
  running(false);
  $("status").textContent = "";
  showCalibrationStep();
});

// pywebview creates window.pywebview.api as an empty object first, adds the functions later, then
// fires "pywebviewready" (its js/api.js and js/finish.js). So check for a function, not the object.
if (typeof window.pywebview?.api?.bands === "function") ready();
else window.addEventListener("pywebviewready", ready, { once: true });
