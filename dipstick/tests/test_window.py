"""The real app window (pywebview), which no browser test can stand in for: Playwright's own
evaluate skips the page's security policy, and the fake bridge isn't pywebview's.

Opens a small window for a few seconds, checks the page reached Python (band list filled in,
Sweep enabled), closes it. No NanoVNA needed: nothing is swept. Run it when you ask:

    DIPSTICK_WINDOW=1 .venv/bin/pytest tests/test_window.py
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("DIPSTICK_WINDOW") != "1",
                                reason="set DIPSTICK_WINDOW=1 to open the real window (needs requirements-app.txt)")

PROBE = """
import json, sys, time
import webview
from dipstick.app import PAGE, Api

def probe(window):
    result = {}
    for _ in range(50):  # up to 5 s for the page and the bridge
        time.sleep(0.1)
        try:
            result = window.evaluate_js(
                "({bands: document.getElementById('band').options.length,"
                " disabled: document.getElementById('sweep').disabled})")
        except Exception as error:
            result = {"error": str(error)}
        if result.get("bands", 0) > 1 and result.get("disabled") is False:
            break
    print(json.dumps(result), flush=True)
    window.destroy()

window = webview.create_window("dipstick window test", PAGE.as_uri(), js_api=Api(connect=None), width=500, height=250)
webview.start(probe, window)
"""


def test_the_window_reaches_python():
    # Its own process: pywebview must own the main thread, and pytest's would be the wrong one.
    done = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=60)
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr
    assert '"bands": 16' in last and '"disabled": false' in last, last  # "Choose a band" + 15 bands
