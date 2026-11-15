// The app's page. It calls Python through pywebview's bridge (window.pywebview.api) and shows
// what comes back: the report as text, the plots as SVG drawn by dipstick's own code.
"use strict";

const $ = (id) => document.getElementById(id);
const POINTS = 101;

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
    $("sweep").disabled = false;  // only now can a sweep reach Python
  });
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
  $("sweep").disabled = true;
  $("status").textContent = "Sweeping…";
  try {
    show(await window.pywebview.api.sweep($("band").value, $("target").value, POINTS));
  } catch (error) {
    show({ ok: false, error: `Couldn't reach dipstick's Python side: ${error}` });
  } finally {
    $("sweep").disabled = false;
    $("status").textContent = "";
  }
});

// pywebview creates window.pywebview.api as an empty object first, adds the functions later, then
// fires "pywebviewready" (its js/api.js and js/finish.js). So check for a function, not the object.
if (typeof window.pywebview?.api?.bands === "function") ready();
else window.addEventListener("pywebviewready", ready, { once: true });
