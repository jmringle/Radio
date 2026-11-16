"""The standalone app: dipstick in a native window (pywebview).

No web server runs. The page is loaded from a file:// address (pywebview starts its own local
HTTP server only for plain paths, checked in its source, 2026-11-15), and the page calls Python
through pywebview's bridge (window.pywebview.api), so no other web page can reach the NanoVNA.
pywebview loads only when a window opens, so tests and the command don't need it.
"""

import sys
import threading
import urllib.parse
import urllib.request

from serial.tools import list_ports
import traceback
from pathlib import Path

from dipstick.bands import BANDS, band_range
from dipstick.device import DeviceError, NanoVNA, find_port, nanovna_ports
from dipstick.measure import band_for_target, measure_band, measure_cable, shown
from dipstick.plots import smith_svg, swr_svg
from dipstick.quiz import antenna_questions, cable_questions
from dipstick.scan import MAX_POINTS

APP_NAME = "Dipstick"  # the window title (the command stays lowercase: dipstick)
PAGE = Path(__file__).parent / "ui" / "index.html"
# The cable tab's labels, so errors name the field to fix (index.html must match).
_FIELDS = {"no_antenna": "tick No antenna connected", "vf": "Velocity factor", "length": "Length",
           "max_length": "Longest cable"}
CAL_ORDER = ("open", "short", "load")
# A calibration step answers only after the NanoVNA has swept the standard once, at 100 Hz
# bandwidth or narrower (hugen79/NanoVNA-H cal_collect, read 2026-11-15): slower than a reply.
CAL_STEP_TIMEOUT_S = 20.0


def is_app_page(url, page: Path = PAGE) -> bool:
    """True only for dipstick's own page as a local file. pywebview gives its bridge to whatever page
    the window shows, and a dropped file or a link dragged in from a browser navigates the window
    (security review 2026-11-16), so calls that reach the NanoVNA check this first. Compares real
    paths, not text: Windows writes file:///C:/..., and spaces arrive as %20."""
    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
        return False
    try:
        return Path(urllib.request.url2pathname(parts.path)).resolve() == page.resolve()
    except (OSError, ValueError):
        return False


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
        self._calibration = None  # (band, the next step) between calibration steps
        self._current_url = None  # the window's address, set by _open_window; checked before the NanoVNA
        self._cal_unfinished = False  # `cal reset` sent and `cal done` not yet: the NanoVNA's memory holds no calibration
        self._calibrated_band = None  # finished here (open, short, load): reports skip the reminder to calibrate

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
            measured = measure_band(band, text, _points(points), self._connect,
                                    calibrated=self._calibrated_band is not None)
            # The window's stylesheet colors the plots (its security policy blocks inline styles).
            return {"band": band, "report": measured.report,
                    "swr_svg": swr_svg(measured.readings, band, standalone=False, target_hz=measured.target_hz),
                    "smith_svg": smith_svg(measured.readings, standalone=False),
                    "quiz": _quiz(antenna_questions(measured.summary))}
        return self._one_at_a_time(measure)

    def cable(self, no_antenna, vf, length, max_length) -> dict:
        """Check a coax cable (a wide sweep: only when no_antenna is exactly true); answers
        {"ok": True, report, smith_svg} or {"ok": False, error}."""
        def measure():
            measured = measure_cable(no_antenna, vf, length, max_length, self._connect, names=_FIELDS)
            return {"report": measured.report, "smith_svg": smith_svg(measured.readings, standalone=False, cable=True),
                    "quiz": _quiz(cable_questions(measured.result))}
        return self._one_at_a_time(measure)

    def calibrate(self, band, step) -> dict:
        """One calibration step over a band: "open" (which always starts over), then "short", then
        "load", which also applies the new calibration. Answers {"ok": True, "next": the next step
        or None when finished} or {"ok": False, error}. Changes only the calibration in the
        NanoVNA's memory (never `save`), and leaves the NanoVNA sweeping the band it covers."""
        def measure():
            if step not in CAL_ORDER:
                raise ValueError(f"Unknown calibration step {shown(step)}")
            if not isinstance(band, str):
                raise ValueError("Choose a band")
            start, stop = band_range(band)
            if step != "open":
                expected = self._calibration
                if expected is None:
                    raise ValueError("Start with the open standard")
                if expected[0] != band:
                    raise ValueError(f"This calibration is for {expected[0]}. Start with the open standard to calibrate {band}")
                if expected[1] != step:
                    raise ValueError(f"Measure the {expected[1]} next")
            try:
                nano = self._connect(None)
                try:
                    if step == "open":
                        self._calibration = None
                        nano.ask("sweep", start, stop, MAX_POINTS)  # a standard is measured over the NanoVNA's own sweep
                        self._cal_unfinished = True  # from here until `cal done`, even if `reset` fails partway
                        self._calibrated_band = None
                        nano.ask("cal", "reset")
                    nano.ask("cal", step, timeout_s=CAL_STEP_TIMEOUT_S)
                    if step == "load":
                        nano.ask("cal", "done")
                        self._cal_unfinished = False
                        self._calibrated_band = band
                finally:
                    nano.close()
            except DeviceError as error:
                if self._cal_unfinished:
                    raise DeviceError(f"{error} The NanoVNA's calibration is unfinished: try this step "
                                      "again, or switch the NanoVNA off and on to go back to its saved "
                                      "calibration.") from None
                raise
            following = CAL_ORDER.index(step) + 1
            self._calibration = (band, CAL_ORDER[following]) if following < len(CAL_ORDER) else None
            return {"next": self._calibration and self._calibration[1]}
        return self._one_at_a_time(measure)

    def _one_at_a_time(self, measure) -> dict:
        """pywebview runs each call from the page on its own thread, and there's one NanoVNA."""
        if self._current_url is not None and not is_app_page(self._current_url()):
            return {"ok": False, "error": "Only Dipstick's own page can use the NanoVNA, and this window "
                                          "has left it. Close the window and open Dipstick again."}
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

def _quiz(questions) -> list[dict]:
    """The page's "Check yourself" questions, as plain dicts and lists for pywebview's bridge."""
    return [{"ask": q.ask, "choices": list(q.choices), "answer": q.answer, "why": q.why} for q in questions]


def _points(value) -> int:
    """The page sends numbers or text; accept whole numbers only."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    if isinstance(value, int):  # true/false arrive as 1/0, which the 2-to-101 check refuses
        return value
    raise ValueError(f"Points must be a whole number, got {shown(value)}")


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
  cable: document.getElementById('check-cable').disabled,
  calibrate_bands: document.getElementById('cal-band').options.length})
"""


def _open_window(api: Api, title: str, **size):
    """The window, with the only-our-page check wired to its address: every window goes through here,
    so none can exist without it."""
    import webview

    window = webview.create_window(title, PAGE.as_uri(), js_api=api, **size)
    api._current_url = window.get_current_url
    return window


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
        seen.update(app_page=is_app_page(window.get_current_url()), guarded=api._current_url is not None)
        window.destroy()

    api = Api(connect=None, ports=lambda: [])
    window = _open_window(api, f"{APP_NAME} self-test", width=500, height=250)
    webview.start(probe, window)
    print(json.dumps(seen), flush=True)
    return 0 if seen.get("bands", 0) > 1 and seen.get("cable") is False and "error" not in seen \
        and seen.get("app_page") is True and seen.get("guarded") is True else 1


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    import webview

    _open_window(Api(), APP_NAME, width=1100, height=900, min_size=(480, 600))
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
