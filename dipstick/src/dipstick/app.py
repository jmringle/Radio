"""The standalone app: dipstick in a native window (pywebview).

No web server runs. The page is loaded from a file:// address (pywebview starts its own local
HTTP server only for plain paths, checked in its source, 2026-11-15), and the page calls Python
through pywebview's bridge (window.pywebview.api), so no other web page can reach the NanoVNA.
pywebview loads only when a window opens, so tests and the command don't need it.
"""

import sys
import threading

from serial.tools import list_ports
import traceback
from pathlib import Path

from dipstick.bands import BANDS
from dipstick.device import DeviceError, NanoVNA, find_port, nanovna_ports
from dipstick.measure import band_for_target, measure_band, measure_cable
from dipstick.plots import smith_svg, swr_svg

APP_NAME = "dipstick"
PAGE = Path(__file__).parent / "ui" / "index.html"
# The cable tab's labels, so errors name the field to fix (index.html must match).
_FIELDS = {"no_antenna": "tick No antenna connected", "vf": "Velocity factor", "length": "Length",
           "max_length": "Longest cable"}


def connect_nanovna(port: str | None, ports=list_ports.comports) -> NanoVNA:
    """Opens the NanoVNA. The app has no --port option, so its errors never suggest one."""
    return NanoVNA.open(port or find_port(ports(), port_option=False))


class Api:
    """What the page may call. pywebview exposes public methods and walks public attributes, so
    everything else here is private (a leading underscore)."""

    def __init__(self, connect=connect_nanovna, ports=list_ports.comports):
        self._connect = connect
        self._ports = ports
        self._busy = threading.Lock()

    def bands(self) -> list[str]:
        return list(BANDS)

    def nanovna(self) -> dict:
        """Is a NanoVNA plugged in? Reads only the computer's list of USB serial ports; never opens
        one, so the page can ask every couple of seconds, even during a sweep."""
        found = nanovna_ports(self._ports())
        if len(found) == 1:
            return {"connected": True, "text": f"NanoVNA connected ({found[0]})"}
        if found:
            return {"connected": False, "text": f"More than one NanoVNA is plugged in ({', '.join(found)}); unplug one"}
        return {"connected": False, "text": "No NanoVNA found. Is it plugged in and switched on?"}

    def sweep(self, band, target, points) -> dict:
        """Measure a band (or, with no band, the band the target is in); answers
        {"ok": True, band, report, swr_svg, smith_svg} or {"ok": False, error}."""
        def measure():
            nonlocal band
            text = target if isinstance(target, str) else None
            if not band:  # "Choose a band" left as it is: the target decides
                band = band_for_target(text)
            if not isinstance(band, str):
                raise ValueError("Choose a band")
            measured = measure_band(band, text, _points(points), self._connect)
            # The window's stylesheet colors the plots (its security policy blocks inline styles).
            return {"band": band, "report": measured.report,
                    "swr_svg": swr_svg(measured.readings, band, standalone=False),
                    "smith_svg": smith_svg(measured.readings, standalone=False)}
        return self._one_at_a_time(measure)

    def cable(self, no_antenna, vf, length, max_length) -> dict:
        """Check a coax cable (a wide sweep: only when no_antenna is exactly true); answers
        {"ok": True, report, smith_svg} or {"ok": False, error}."""
        def measure():
            measured = measure_cable(no_antenna, vf, length, max_length, self._connect, names=_FIELDS)
            return {"report": measured.report, "smith_svg": smith_svg(measured.readings, standalone=False)}
        return self._one_at_a_time(measure)

    def _one_at_a_time(self, measure) -> dict:
        """pywebview runs each call from the page on its own thread, and there's one NanoVNA."""
        if not self._busy.acquire(blocking=False):
            return {"ok": False, "error": "A sweep is already running"}
        try:
            return {"ok": True, **measure()}
        except (DeviceError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:  # a bug: say so on the page, keep the details for the log
            traceback.print_exc()
            return {"ok": False, "error": f"Unexpected error ({type(error).__name__}); details are in the log"}
        finally:
            self._busy.release()

def _points(value) -> int:
    """The page sends numbers or text; accept whole numbers only."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    if isinstance(value, int):  # true/false arrive as 1/0, which the 2-to-101 check refuses
        return value
    raise ValueError(f"Points must be a whole number, got {value!r}")


# What the self-test reads from the page, after opening the Cable tab and ticking its box (never
# clicking Check cable). Check cable enabled means the page reached Python.
_PROBE = """
document.getElementById('tab-cable').click();
const box = document.getElementById('no-antenna');
box.checked = true; box.dispatchEvent(new Event('change'));
({bands: document.getElementById('band').options.length,
  disabled: document.getElementById('sweep').disabled,
  live: document.getElementById('live').disabled,
  connection: document.getElementById('connection').textContent,
  cable: document.getElementById('check-cable').disabled})
"""


def self_test() -> int:
    """Open a small window, check the page reached Python, close it: 0 if it did. Prints what it saw
    as one JSON line. tests/test_window.py and the build check in CI run this. It gets no NanoVNA
    connection and an empty port list, so nothing can be swept."""
    import json
    import time

    import webview

    seen = {}

    def probe(window):
        for _ in range(100):  # up to 10 s for the page and the bridge
            time.sleep(0.1)
            try:
                seen.update(window.evaluate_js(_PROBE))
            except Exception as error:  # the page may not be loaded yet
                seen.update(error=str(error))
            if seen.get("bands", 0) > 1 and seen.get("disabled") is False and seen.get("connection") \
                    and seen.get("cable") is False:
                seen.pop("error", None)
                break
        window.destroy()

    window = webview.create_window(f"{APP_NAME} self-test", PAGE.as_uri(), js_api=Api(connect=None, ports=lambda: []),
                                   width=500, height=250)
    webview.start(probe, window)
    print(json.dumps(seen), flush=True)
    return 0 if seen.get("bands", 0) > 1 and seen.get("cable") is False and "error" not in seen else 1


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    import webview

    webview.create_window(APP_NAME, PAGE.as_uri(), js_api=Api(), width=1100, height=900, min_size=(480, 600))
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
