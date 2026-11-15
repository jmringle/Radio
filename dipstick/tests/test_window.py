"""The real app window (pywebview), which no browser test can stand in for: Playwright's own
evaluate skips the page's security policy, and the fake bridge isn't pywebview's.

Opens a small window for a few seconds, checks the page reached Python (band list filled in,
Sweep and Live enabled, the NanoVNA line filled in, Check cable enabled once the Cable tab's box is
ticked), closes it. No NanoVNA needed: nothing is swept, and Check cable is never clicked. Run it when you ask:

    DIPSTICK_WINDOW=1 .venv/bin/pytest tests/test_window.py
"""

import json
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
                "document.getElementById('tab-cable').click();"
                "const box = document.getElementById('no-antenna');"
                "box.checked = true; box.dispatchEvent(new Event('change'));"
                "({bands: document.getElementById('band').options.length,"
                " disabled: document.getElementById('sweep').disabled,"
                " live: document.getElementById('live').disabled,"
                " connection: document.getElementById('connection').textContent,"
                " cable: document.getElementById('check-cable').disabled})")
        except Exception as error:
            result = {"error": str(error)}
        if result.get("bands", 0) > 1 and result.get("disabled") is False and result.get("connection") \
                and result.get("cable") is False:
            break
    print(json.dumps(result), flush=True)
    window.destroy()

window = webview.create_window("dipstick window test", PAGE.as_uri(), js_api=Api(connect=None, ports=lambda: []), width=500, height=250)
webview.start(probe, window)
"""


def test_the_window_reaches_python():
    # Its own process: pywebview must own the main thread, and pytest's would be the wrong one.
    done = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=60)
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr
    assert last.startswith("{"), last
    assert json.loads(last) == {"bands": 16,  # "Choose a band" + 15 bands
                                "disabled": False, "live": False,
                                "connection": "No NanoVNA found. Is it plugged in and switched on?",  # no ports given
                                "cable": False}  # Check cable enabled: the box is ticked and Python is reachable
