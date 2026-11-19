// The app's page. It calls Python through pywebview's bridge (window.pywebview.api) and shows
// what comes back: the report as text, the plots as SVG drawn by dipstick's own code.
"use strict";

const $ = (id) => document.getElementById(id);
const POINTS = 101;
const CHECK_EVERY_MS = 2000;  // how often to look for the NanoVNA (reads the port list only)
const LIVE_PAUSE_MS = 300;    // breathing room between live passes
let live = false;             // true while live mode runs; Stop sets it false
let pythonReady = false;      // the bridge's functions have arrived
let lastQuiz = [];            // the last result's "Check yourself" questions, shown once Live stops
let quizOn = true;            // the Show Check yourself box; Python remembers it between launches
let detailOpen = false;       // a band report's More detail; Python remembers it too

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
    const wide = document.createElement("option");
    wide.value = WIDE;
    wide.textContent = "HF wide, 1.8 to 54 MHz (Balun tab)";
    $("cal-band").append(wide);
    $("cal-band").value = "";
    $("sweep").disabled = $("live").disabled = false;  // only now can a sweep reach Python
    pythonReady = true;
    allowCableCheck();
    allowBalunCheck();
    showCalibrationStep();
  });
  window.pywebview.api.settings().then((settings) => {
    quizOn = $("quiz-on").checked = settings.quiz !== false;
    $("detail").open = detailOpen = settings.detail === true;
    $("quiz-on").disabled = false;
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
  await showPortChoice();
}

// "Is your NanoVNA one of these?": for a NanoVNA that uses a generic USB chip, which Dipstick won't
// guess at (it could be a radio's cable). Rebuilt only when the list changes, so the open menu isn't
// reset every few seconds. The ports' names come from the USB devices, so they go in as text.
let portSignature = "";
async function showPortChoice() {
  let answer;
  try {
    answer = await window.pywebview.api.serial_ports();
  } catch (error) {
    return;  // the port choice is optional; the connection line already says what's wrong
  }
  const missing = $("connection").className === "missing";
  const signature = JSON.stringify([missing, answer.ports, answer.remembered]);
  if (signature === portSignature) return;
  portSignature = signature;
  $("port-picker").hidden = !(missing && answer.ports.length > 0);
  $("port-choice").replaceChildren(...answer.ports.map((port) => {
    const option = document.createElement("option");
    option.value = port.device;
    option.textContent = `${port.label} (USB ID ${port.id})`;
    return option;
  }));
  $("port-remembered").hidden = answer.remembered.length === 0;
  $("port-ids").textContent = answer.remembered.join(", ");
}

$("port-use").addEventListener("click", async () => {
  try {
    const answer = await window.pywebview.api.use_port($("port-choice").value);
    if (!answer.ok) $("error").textContent = answer.error;
  } catch (error) {
    $("error").textContent = `Couldn't save the port choice: ${error}`;
  }
  portSignature = "";
  checkConnection();
});

$("port-forget").addEventListener("click", async () => {
  try {
    const answer = await window.pywebview.api.forget_ports();
    if (!answer.ok) $("error").textContent = answer.error;
  } catch (error) {
    $("error").textContent = `Couldn't forget the port choice: ${error}`;
  }
  portSignature = "";
  checkConnection();
});

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

const sweepOnce = () => ask(() => window.pywebview.api.sweep($("band").value, $("target").value, POINTS,
                                                             $("antenna-length").value));

function lock(locked) {
  for (const id of ["band", "target", "antenna-length", "sweep"]) $(id).disabled = locked;
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
    ? `Note: the NanoVNA was calibrated for ${calName(calibratedBand)} on the Calibrate tab, not for ` +
      `${answer.band}, so this reading isn't calibrated for this band (unless you've switched the ` +
      `NanoVNA off and on since, which goes back to its saved calibration). Calibrate ${answer.band} ` +
      "for a reading you can trust.\n\n"
    : "";
  showLines($("report"), answer.ok ? note + answer.report : "");
  showLines($("detail-text"), answer.ok ? answer.detail || "" : "");  // only a band sweep has detail
  $("detail").hidden = !(answer.ok && answer.detail);
  lastQuiz = answer.ok && Array.isArray(answer.quiz) ? answer.quiz : [];
  showQuiz(live ? [] : lastQuiz);
  // The SVG comes from dipstick's own plot code, not from the NanoVNA or anything typed.
  $("swr").innerHTML = answer.ok ? answer.swr_svg || "" : "";  // a cable has no SWR plot
  $("smith").innerHTML = answer.ok ? answer.smith_svg || "" : "";  // a transformer has no Smith chart
}

// The report is plain text. Lines starting with two spaces explain (report.py's convention) and are
// shown dimmer, so the answers stand out. Each line goes in as text, never markup.
function showLines(element, text) {
  const lines = text ? text.split("\n") : [];
  element.replaceChildren(...lines.map((line) => {
    const span = document.createElement("span");
    if (line.startsWith("  ")) span.className = "explain";
    span.textContent = line + "\n";
    return span;
  }));
}

// One group of radio buttons per question; choosing says right or not, and why. Text only, never markup.
function showQuiz(questions) {
  $("quiz-questions").replaceChildren(...questions.map((question, number) => {
    const group = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = question.ask;
    const feedback = document.createElement("p");
    feedback.setAttribute("role", "status");
    group.append(legend);
    question.choices.forEach((choice, index) => {
      const label = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `question-${number}`;
      radio.addEventListener("change", () => {
        const right = index === question.answer;
        feedback.textContent = right ? `Right. ${question.why}`
          : `Not quite: the answer is ${question.choices[question.answer]}. ${question.why}`;
        feedback.className = right ? "right" : "wrong";
      });
      label.append(radio, ` ${choice}`);
      group.append(label);
    });
    group.append(feedback);
    return group;
  }));
  showOrHideQuiz();
}

// Hiding keeps the questions and your answers, so ticking the box again brings them back as they were.
function showOrHideQuiz() {
  $("quiz").hidden = !quizOn || $("quiz-questions").childElementCount === 0;
}

$("quiz-on").addEventListener("change", async () => {
  quizOn = $("quiz-on").checked;
  showOrHideQuiz();
  try {
    const answer = await window.pywebview.api.set_quiz(quizOn);
    if (!answer.ok) $("error").textContent = answer.error;
  } catch (error) {
    $("error").textContent = `Couldn't save the Check yourself setting: ${error}`;
  }
});

// "toggle" also fires when the saved setting opens it at start; only a change from what Python has is saved.
$("detail").addEventListener("toggle", async () => {
  if ($("detail").open === detailOpen) return;
  detailOpen = $("detail").open;
  try {
    const answer = await window.pywebview.api.set_detail(detailOpen);
    if (!answer.ok) $("error").textContent = answer.error;
  } catch (error) {
    $("error").textContent = `Couldn't save whether More detail is open: ${error}`;
  }
});

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
  showQuiz(lastQuiz);  // the last pass's questions, now that they won't be redrawn
  lock(false);
  running(false);
  button.textContent = "Live (repeat)";
  button.disabled = false;
  $("status").textContent = "";
});

// --- tabs: Antenna (band sweeps), Cable, Balun and Calibrate ----------------------------------
const tabs = [$("tab-antenna"), $("tab-cable"), $("tab-balun"), $("tab-calibrate")];

function selectTab(tab) {
  if (tab.getAttribute("aria-selected") === "true") return;
  for (const each of tabs) {
    const selected = each === tab;
    each.setAttribute("aria-selected", String(selected));
    each.tabIndex = selected ? 0 : -1;  // roving tabindex: Tab reaches only the selected tab
    $(each.getAttribute("aria-controls")).hidden = !selected;
  }
  $("quiz-option").hidden = tab === $("tab-calibrate") || tab === $("tab-balun");  // these ask no questions
  // A band's results aren't this cable's (or the other way round), and the boxes are confirmed afresh.
  show({ ok: true, report: "", smith_svg: "" });
  $("no-antenna").checked = $("balun-no-antenna").checked = false;
  allowCableCheck();
  allowBalunCheck();
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

// --- the transformer and choke tests: only with "No antenna connected" ticked, cleared after every test ---
function allowBalunCheck() {
  $("check-balun").disabled = !(pythonReady && $("balun-no-antenna").checked);
}

$("balun-no-antenna").addEventListener("change", allowBalunCheck);

// The resistor that makes a perfect transformer read 50 ohms: 50 times the ratio.
$("ratio").addEventListener("change", () => {
  $("resistor").placeholder = `${50 * parseInt($("ratio").value, 10)} (default)`;
});

// Each test shows its own fields (the choke test has none) and its own wiring hint.
const BALUN_TESTS = {
  "Transformer": {fields: "transformer-fields", hint: "balun-hint", button: "Test transformer", status: "Testing the transformer…"},
  "Choke": {fields: null, hint: "choke-hint", button: "Test choke", status: "Testing the choke…"},
  "Through loss": {fields: "loss-fields", hint: "loss-hint", button: "Test through loss", status: "Measuring the through loss…"},
};
const balunTest = () => $("balun-test").value;

$("balun-test").addEventListener("change", () => {
  for (const [name, test] of Object.entries(BALUN_TESTS)) {
    if (test.fields) $(test.fields).hidden = name !== balunTest();
    $(test.hint).hidden = name !== balunTest();
  }
  $("check-balun").textContent = BALUN_TESTS[balunTest()].button;
});

$("balun-controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  const fields = ["balun-test", "balun-no-antenna", "ratio", "resistor", "loss-connection", "check-balun"];
  for (const id of fields) $(id).disabled = true;
  running(true);
  const noAntenna = $("balun-no-antenna").checked;
  const api = window.pywebview.api;
  $("status").textContent = BALUN_TESTS[balunTest()].status;
  const calls = {
    "Transformer": () => api.transformer(noAntenna, $("ratio").value, $("resistor").value),
    "Choke": () => api.choke(noAntenna),
    "Through loss": () => api.loss(noAntenna, $("loss-connection").value),
  };
  await ask(calls[balunTest()]);
  $("balun-no-antenna").checked = false;  // the antenna wire might be back on by the next test
  for (const id of fields) $(id).disabled = false;
  allowBalunCheck();
  running(false);
  $("status").textContent = "";
});

// --- calibrating: open, short, load (then isolation and thru for Both ports), over one band (or HF wide)
const WIDE = "wide";  // app.py's WIDE: the transformer test's range, 1.8 to 54 MHz
const calName = (band) => band === WIDE ? "1.8 to 54 MHz (HF wide)" : band;
const CAL_STEPS = {
  open: "screw the open standard onto CH0. An open reflects all of the signal straight " +
        "back, in step: it shows the NanoVNA what nothing connected looks like at its connector.",
  short: "swap it for the short standard. A short also reflects all of the signal, but " +
         "turned upside down (inverted): the opposite side of the Smith chart.",
  load: "swap it for the load standard (50 ohms). A load takes in all of the signal and " +
        "reflects none: a perfect match, SWR 1.0, the middle of the Smith chart.",
  // nanovna.com's calibration page (read 2026-11-17): with one load, it stays on CH0 and CH1 is left open.
  isoln: "leave the load on CH0, and put a second load on CH1 if you have one; with only one load, leave " +
         "CH1 open. Isolation measures the little that leaks from CH0 to CH1 inside the NanoVNA itself.",
  thru: "connect CH0 to CH1: the two cables joined by the through connector (the barrel with a socket at " +
        "each end), the same cables you'll measure through. A thru is everything getting through: 0 dB loss.",
};
const calOrder = () => $("cal-both").checked ? ["open", "short", "load", "isoln", "thru"] : ["open", "short", "load"];
const stepName = (step) => step === "isoln" ? "isolation" : step;
let calStep = "open";  // the next standard to measure
let calDone = "";      // the band just calibrated, until another calibration starts
let calDoneBoth = false;  // whether that calibration covered both ports
let calibratedBand = "";  // the band the NanoVNA holds this session's calibration for, until the next open resets it
const PARTWAY = "The other tabs open again after the last step. To stop partway, set the band back to " +
  "Choose a band and switch the NanoVNA off and on (it goes back to its saved calibration).";

function showCalibrationStep() {
  const wide = $("cal-band").value === WIDE;
  $("cal-wide").hidden = !wide;
  $("cal-step").textContent = `Measure ${stepName(calStep)}`;
  const calibrated = `Calibrated ${calDoneBoth ? "both ports " : ""}for`;
  $("cal-step").disabled = !(pythonReady && $("cal-band").value && (!wide || $("cal-no-antenna").checked));
  $("cal-instruction").textContent = calDone === WIDE && calStep === "open"
    ? `${calibrated} 1.8 to 54 MHz. Test your transformer on the Balun tab. The NanoVNA keeps sweeping ` +
      "that range on its own, so keep antennas off it until you calibrate a band, or switch it off and on " +
      "(it goes back to its saved calibration)."
    : calDone && calStep === "open"
    ? `${calibrated} ${calDone}. Put your antenna back on and sweep ${calDone} on the Antenna tab. The ` +
      "calibration lasts until you switch the NanoVNA off and on, which goes back to its saved one."
    : $("cal-band").value ? `Step ${calOrder().indexOf(calStep) + 1} of ${calOrder().length}: ${CAL_STEPS[calStep]}`
    : "Choose the band you'll measure.";
  // Apart from the step, and smaller: the step is what to do now (UI review 2026-11-16).
  $("cal-partway").textContent = PARTWAY;
  $("cal-partway").hidden = !($("cal-band").value && calStep !== "open");
}

$("cal-no-antenna").addEventListener("change", showCalibrationStep);

$("cal-both").addEventListener("change", () => {
  calStep = "open";  // a different set of steps: start over
  calDone = "";
  running(false);
  showCalibrationStep();
});

$("cal-band").addEventListener("change", () => {
  calStep = "open";  // a calibration covers one band: another band starts over
  calDone = "";
  $("cal-no-antenna").checked = false;
  running(false);    // a cancelled calibration opens the other tabs again
  showCalibrationStep();
});

$("cal-controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  const band = $("cal-band").value;
  $("cal-step").disabled = $("cal-band").disabled = $("cal-no-antenna").disabled = $("cal-both").disabled = true;
  running(true);
  $("status").textContent = `Measuring the ${stepName(calStep)} standard…`;
  try {
    const answer = await window.pywebview.api.calibrate(band, calStep, $("cal-no-antenna").checked, $("cal-both").checked);
    $("error").textContent = answer.ok ? "" : answer.error;
    if (answer.ok) {
      if (calStep === "open") calibratedBand = "";  // open reset the NanoVNA's calibration
      if (!answer.next) calibratedBand = band;
      calDone = answer.next ? "" : band;
      calDoneBoth = $("cal-both").checked;
      calStep = answer.next || "open";
      if (!answer.next) $("cal-no-antenna").checked = false;  // confirmed afresh for the next calibration
    }
  } catch (error) {
    $("error").textContent = `Couldn't reach dipstick's Python side: ${error}`;
  }
  $("cal-band").disabled = $("cal-no-antenna").disabled = $("cal-both").disabled = false;
  running(false);
  $("status").textContent = "";
  showCalibrationStep();
});

// pywebview creates window.pywebview.api as an empty object first, adds the functions later, then
// fires "pywebviewready" (its js/api.js and js/finish.js). So check for a function, not the object.
if (typeof window.pywebview?.api?.bands === "function") ready();
else window.addEventListener("pywebviewready", ready, { once: true });
