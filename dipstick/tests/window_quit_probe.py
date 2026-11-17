"""Run by tests/test_window.py in its own process (pywebview needs the main thread). The app's own
self-test through main(), as the built app runs it, with a thread that never finishes, as if a call
from the page were stuck. beta.10's built app hung after its self-test 3 runs in 5 (2026-11-16): a
sample showed the main thread done and Python's exit waiting on a non-daemon thread blocked on a lock.
pywebview runs each page call on its own non-daemon thread (util.py, 6.2.1), which hands its answer
back with evaluate_js; on macOS that waits for the window's run loop, so a call still running when
the window closes can wait forever. The process must exit anyway."""

import sys
import threading

import dipstick.app as app

threading.Thread(target=threading.Event().wait, name="stuck page call").start()  # non-daemon, never ends
sys.argv = [sys.argv[0], "--self-test"]
sys.exit(app.main())
