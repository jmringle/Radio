"""The real app window (pywebview), which no browser test can stand in for: Playwright's own
evaluate skips the page's security policy, and the fake bridge isn't pywebview's.

Runs the app's own `--self-test`, the same check CI runs on each built app: it opens a small window
for a few seconds, checks the page reached Python (band list filled in, Sweep and Live enabled, the
NanoVNA line filled in, Check cable enabled once the Cable tab's box is ticked), and closes it. No
NanoVNA needed: the self-test gets no connection, so nothing can be swept, and Check cable is never
clicked. Run it when you ask:

    DIPSTICK_WINDOW=1 .venv/bin/pytest tests/test_window.py
"""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("DIPSTICK_WINDOW") != "1",
                                reason="set DIPSTICK_WINDOW=1 to open the real window (needs requirements-app.txt)")


def test_the_window_reaches_python():
    # Its own process: pywebview must own the main thread, and pytest's would be the wrong one.
    done = subprocess.run([sys.executable, "-m", "dipstick.app", "--self-test"],
                          capture_output=True, text=True, timeout=60)
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr
    assert last.startswith("{"), last
    assert json.loads(last) == {"bands": 16,  # "Choose a band" + 15 bands
                                "disabled": False, "live": False,
                                "connection": "No NanoVNA found. Is it plugged in and switched on?",  # no ports given
                                "cable": False,  # Check cable enabled: the box is ticked and Python is reachable
                                "calibrate_bands": 16,  # the Calibrate tab's band list, filled in too
                                # The window's own address passes the only-our-page check (on every
                                # OS CI builds for: Windows writes file:///C:/...), and the check is on.
                                "app_page": True, "guarded": True}
    assert done.returncode == 0


def test_a_page_the_window_is_sent_to_cant_use_the_nanovna(tmp_path):
    # Security review 2026-11-16: a dropped file or dragged-in link navigates the window, and pywebview
    # gives that page its bridge too. The bridge is still there (pywebview's doing); the check refuses.
    foreign = tmp_path / "not-dipstick.html"
    foreign.write_text("<!doctype html><title>x</title>")
    done = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "window_nav_probe.py"),
                           str(foreign)], capture_output=True, text=True, timeout=60)
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr
    seen = json.loads(last)
    assert seen["landed"] and seen["bridge_there"]  # the attack's precondition really happened
    assert seen["answer"]["ok"] is False and "Only Dipstick's own page" in seen["answer"]["error"]
    assert seen["connects"] == 0
