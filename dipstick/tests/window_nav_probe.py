"""Run by tests/test_window.py in its own process (pywebview needs the main thread). Navigates the
real window away from dipstick's page, the way a dropped file does, then calls the NanoVNA from the
page it landed on. Prints one JSON line. The Api's connect only records: nothing reaches a NanoVNA."""

import json
import sys
import time
from pathlib import Path

import webview

from dipstick.app import PAGE, Api, _open_window

foreign = Path(sys.argv[1])
connects, out = [], {}
api = Api(connect=lambda port: connects.append(port), ports=lambda: [])


def run(window):
    try:
        time.sleep(1.5)
        window.evaluate_js(f"location.href = {json.dumps(foreign.as_uri())}")  # stands in for a drop
        time.sleep(2.0)
        out["landed"] = window.get_current_url() != PAGE.as_uri()
        out["bridge_there"] = window.evaluate_js("typeof window.pywebview?.api?.cable") == "function"
        window.evaluate_js("window.pywebview.api.cable(true, '0.66', '', '50')"
                           ".then(a => { document.title = JSON.stringify(a); })")
        time.sleep(1.0)
        out["answer"] = json.loads(window.evaluate_js("document.title"))
        out["connects"] = len(connects)
    finally:
        window.destroy()


window = _open_window(api, "nav probe", width=500, height=250)
webview.start(run, window)
print(json.dumps(out), flush=True)
