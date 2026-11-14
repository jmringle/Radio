// The page's only script (2026-11-13): the app's window has no browser spinner, so a form marked
// data-busy says it's working while it posts, and its buttons can't be clicked twice. It sends
// and fetches nothing; with it blocked or missing, the forms work exactly the same.
"use strict";
document.addEventListener("submit", (event) => {
  const form = event.target;
  const message = form.dataset.busy;
  if (!message) return;
  const file = form.querySelector("input[type=file]");
  const name = file && file.files.length ? file.files[0].name.slice(0, 80) : "";
  const status = document.getElementById("busy");
  status.textContent = message.replace("{file}", name);  // text, never HTML
  status.hidden = false;
  // Buttons only: a disabled file input would leave its file out of the upload.
  document.querySelectorAll("form[data-busy] button").forEach((button) => { button.disabled = true; });
});
// Back to a page kept in the browser's cache: it's no longer busy.
window.addEventListener("pageshow", () => {
  document.getElementById("busy").hidden = true;
  document.querySelectorAll("form[data-busy] button").forEach((button) => { button.disabled = false; });
});
