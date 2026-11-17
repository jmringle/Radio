"""The standalone app: dipstick in a native window (pywebview).

No web server runs. The page is loaded from a file:// address (pywebview starts its own local
HTTP server only for plain paths, checked in its source, 2026-11-15), and the page calls Python
through pywebview's bridge (window.pywebview.api), so no other web page can reach the NanoVNA.
pywebview loads only when a window opens, so tests and the command don't need it.
"""

import os
import sys
import threading
import urllib.parse
import urllib.request

from serial.tools import list_ports
import traceback
from pathlib import Path

from dipstick import balun
from dipstick.bands import BANDS, band_range
from dipstick.device import DeviceError, NanoVNA, find_port, nanovna_ports
from dipstick.measure import band_for_target, measure_band, measure_cable, measure_transformer, shown
from dipstick.plots import smith_svg, swr_svg
from dipstick.quiz import antenna_questions, cable_questions
from dipstick.scan import MAX_POINTS
from dipstick import settings as saved

APP_NAME = "Dipstick"  # the window title (the command stays lowercase: dipstick)
PAGE = Path(__file__).parent / "ui" / "index.html"
# The cable tab's labels, so errors name the field to fix (index.html must match).
_FIELDS = {"no_antenna": "tick No antenna connected", "vf": "Velocity factor", "length": "Length",
           "max_length": "Longest cable", "ratio": "Ratio", "resistor": "Resistor"}
# The Calibrate tab's choice for the transformer test's range (index.html must match): 1.8 to 54 MHz,
# the same 101 points, so the test sweeps exactly the calibrated frequencies.
WIDE = "wide"
CAL_ORDER = ("open", "short", "load")
# Both ports adds the S21 steps, in the order nanovna.com's calibration page gives (read 2026-11-17):
# isolation (the load on CH0, and a second one on CH1 if you have it), then a thru from CH0 to CH1.
CAL_ORDER_BOTH = (*CAL_ORDER, "isoln", "thru")
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


def connect_nanovna(port: str | None, ports=list_ports.comports, approved=()) -> NanoVNA:
    """Opens the NanoVNA. The app has no --port option, so its errors never suggest one.
    `approved`: (vendor, product) USB IDs the person said are their NanoVNA."""
    return NanoVNA.open(port or find_port(ports(), port_option=False, approved=approved))


def _usb_id_text(port) -> str:
    return f"{port.vid:04X}:{port.pid:04X}"


def _what_it_says(port) -> str:
    """How the device describes itself; pyserial says "n/a" when it doesn't."""
    for text in (port.description, port.product):
        if text and text != "n/a":
            return text
    return "USB serial"


def _usb_id_pair(text: str) -> tuple[int, int]:
    vendor, product = text.split(":")
    return int(vendor, 16), int(product, 16)


class Api:
    """What the page may call. pywebview exposes public methods and walks public attributes, so
    everything else here is private (a leading underscore)."""

    def __init__(self, connect=connect_nanovna, ports=list_ports.comports, settings_path: Path | None = None):
        self._ports = ports
        # The app's own connection looks at the IDs the person approved when it connects (they can
        # change while the app runs); a connection given by a test is used as it is.
        self._connect = (lambda port: connect_nanovna(port, ports, self._approved())) \
            if connect is connect_nanovna else connect
        self._busy = threading.Lock()
        self._calibration = None  # (band, the next step, both_ports) between calibration steps
        self._current_url = None  # the window's address, set by _open_window; checked before the NanoVNA
        self._cal_unfinished = False  # `cal reset` sent and `cal done` not yet: the NanoVNA's memory holds no calibration
        self._calibrated_band = None  # finished here (open, short, load): reports skip the reminder to calibrate
        self._settings_path = settings_path  # None: nothing saved (tests and the self-test)
        self._settings = saved.load(settings_path)
        self._saving = threading.Lock()  # not _busy: the setting can change during a sweep

    def bands(self) -> list[str]:
        return list(BANDS)

    def nanovna(self) -> dict:
        """Is a NanoVNA plugged in? Reads only the computer's list of USB serial ports; never opens
        one, so the page can ask every couple of seconds, even during a sweep."""
        found = nanovna_ports(self._ports(), self._approved())
        if len(found) == 1:
            return {"connected": True, "text": f"NanoVNA connected ({found[0]})"}
        if found:
            return {"connected": False, "text": f"More than one NanoVNA is plugged in ({', '.join(found)}); unplug one"}
        return {"connected": False, "text": "No NanoVNA found. Is it plugged in and switched on?"}

    def serial_ports(self) -> dict:
        """For the page's "Is your NanoVNA one of these?" choice: {"ports": [{"device", "id", "label"}],
        "remembered": [USB IDs]}. The USB serial ports that aren't already a NanoVNA, and the IDs the
        person approved earlier. Reads only the computer's port list; never opens a port."""
        approved = self._approved()
        known = set(nanovna_ports(self._ports(), approved))
        ports = [{"device": p.device, "id": _usb_id_text(p), "label": f"{p.device}: {_what_it_says(p)}"}
                 for p in self._ports() if p.vid is not None and p.pid is not None and p.device not in known]
        return {"ports": ports, "remembered": list(self._settings["ports"])}

    def use_port(self, device) -> dict:
        """The person says the USB serial port `device` is their NanoVNA: remember its USB ID, so any
        port with that ID counts as a NanoVNA from now on. Answers {"ok": True} or {"ok": False, error}.
        Never opens the port, and never picks one itself (T3)."""
        if refusal := self._left_page():
            return refusal
        match = [p for p in self._ports() if isinstance(device, str) and p.device == device
                 and p.vid is not None and p.pid is not None]
        if not match:
            return {"ok": False, "error": f"{shown(device)} isn't a USB serial port that's plugged in now"}
        usb_id = _usb_id_text(match[0])
        with self._saving:
            if usb_id not in self._settings["ports"] and len(self._settings["ports"]) >= saved.MAX_PORTS:
                return {"ok": False, "error": "Too many remembered ports; forget them first"}
            if usb_id not in self._settings["ports"]:
                self._settings["ports"] = [*self._settings["ports"], usb_id]
            return self._save_settings("the port choice")

    def forget_ports(self) -> dict:
        """Forget the USB IDs the person approved; only the NanoVNAs Dipstick knows by name are found again."""
        if refusal := self._left_page():
            return refusal
        with self._saving:
            self._settings["ports"] = []
            return self._save_settings("forgetting the port choice")

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
                                    calibrated=self._calibrated_band not in (None, WIDE))
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

    def transformer(self, no_antenna, ratio, resistor) -> dict:
        """Test an unun or voltage balun with a resistor on its output (a wide sweep: only when
        no_antenna is exactly true); answers {"ok": True, report, swr_svg} or {"ok": False, error}."""
        def measure():
            measured = measure_transformer(no_antenna, ratio, resistor, self._connect, names=_FIELDS,
                                           calibrated=self._calibrated_band == WIDE)
            return {"report": measured.report,
                    "swr_svg": swr_svg(measured.readings, f"{ratio} transformer", standalone=False, ham_bands=True)}
        return self._one_at_a_time(measure)

    def calibrate(self, band, step, no_antenna=False, both_ports=False) -> dict:
        """One calibration step over a band, or WIDE (the transformer test's range): "open" (which
        always starts over), then "short", then "load"; with both_ports, then "isoln" and "thru".
        The last step also applies the new calibration. both_ports is fixed at the open step.
        Answers {"ok": True, "next": the next step or None when finished} or {"ok": False, error}.
        Changes only the calibration in the NanoVNA's memory (never `save`), and leaves the NanoVNA
        sweeping the range it covers: so WIDE only when no_antenna is exactly true (T5)."""
        def measure():
            if not isinstance(both_ports, bool):
                raise ValueError(f"Both ports must be ticked or not, got {shown(both_ports)}")
            order = CAL_ORDER_BOTH if both_ports else CAL_ORDER
            if step not in order:
                raise ValueError(f"Unknown calibration step {shown(step)}")
            if not isinstance(band, str):
                raise ValueError("Choose a band")
            if band == WIDE:
                if no_antenna is not True:
                    raise ValueError(f"HF wide calibrates {balun.START_HZ / 1e6:g} to {balun.STOP_HZ / 1e6:g} MHz, "
                                     "outside the ham bands, and the NanoVNA keeps sweeping that range afterward. "
                                     "Disconnect any antenna, then tick No antenna connected.")
                start, stop = balun.START_HZ, balun.STOP_HZ
            else:
                start, stop = band_range(band)
            if step != "open":
                expected = self._calibration
                if expected is None:
                    raise ValueError("Start with the open standard")
                if expected[0] != band:
                    raise ValueError(f"This calibration is for {expected[0]}. Start with the open standard to calibrate {band}")
                if expected[2] != both_ports:
                    raise ValueError(f"This calibration is for {'both ports' if expected[2] else 'CH0 only'}. "
                                     "Start with the open standard to change that")
                if expected[1] != step:
                    raise ValueError(f"Measure the {'isolation' if expected[1] == 'isoln' else expected[1]} next")
            try:
                nano = self._connect(None)
                try:
                    if step == "open":
                        self._calibration = None
                        nano.ask("sweep", start, stop, balun.POINTS if band == WIDE else MAX_POINTS)  # a standard is measured over the NanoVNA's own sweep
                        self._cal_unfinished = True  # from here until `cal done`, even if `reset` fails partway
                        self._calibrated_band = None
                        nano.ask("cal", "reset")
                    nano.ask("cal", step, timeout_s=CAL_STEP_TIMEOUT_S)
                    if step == order[-1]:
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
            following = order.index(step) + 1
            self._calibration = (band, order[following], both_ports) if following < len(order) else None
            return {"next": self._calibration and self._calibration[1]}
        return self._one_at_a_time(measure)

    def settings(self) -> dict:
        """The saved choices the page shows: {"quiz": True or False}."""
        return {"quiz": self._settings["quiz"]}

    def set_quiz(self, on) -> dict:
        """Show the "Check yourself" questions or not; remembered for the next launch. Answers
        {"ok": True} or {"ok": False, error}."""
        if refusal := self._left_page():
            return refusal
        if not isinstance(on, bool):
            return {"ok": False, "error": f"Check yourself must be on or off, got {shown(on)}"}
        with self._saving:
            self._settings["quiz"] = on
            return self._save_settings("the Check yourself setting")

    def _save_settings(self, what: str) -> dict:
        """Writes the settings file (when there is one); the caller holds _saving."""
        if self._settings_path is None:
            return {"ok": True}
        try:
            saved.save(self._settings_path, self._settings)
        except OSError as error:
            return {"ok": False, "error": f"Couldn't save {what} ({error.strerror or error}), "
                                          "so it lasts only until you quit."}
        return {"ok": True}

    def _approved(self) -> tuple[tuple[int, int], ...]:
        return tuple(_usb_id_pair(text) for text in self._settings["ports"])

    def _left_page(self) -> dict | None:
        """The refusal when the window is showing something other than dipstick's own page."""
        if self._current_url is not None and not is_app_page(self._current_url()):
            return {"ok": False, "error": "Only Dipstick's own page can use the NanoVNA, and this window "
                                          "has left it. Close the window and open Dipstick again."}
        return None

    def _one_at_a_time(self, measure) -> dict:
        """pywebview runs each call from the page on its own thread, and there's one NanoVNA."""
        if refusal := self._left_page():
            return refusal
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
# clicking Check cable). Check cable enabled means the page reached Python; the Check yourself box
# enabled means the settings came back through the bridge.
_PROBE = """
document.getElementById('tab-cable').click();
const box = document.getElementById('no-antenna');
box.checked = true; box.dispatchEvent(new Event('change'));
({bands: document.getElementById('band').options.length,
  disabled: document.getElementById('sweep').disabled,
  live: document.getElementById('live').disabled,
  connection: document.getElementById('connection').textContent,
  cable: document.getElementById('check-cable').disabled,
  calibrate_bands: document.getElementById('cal-band').options.length,
  quiz_box: document.getElementById('quiz-on').disabled})
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
                    and seen.get("cable") is False and seen.get("quiz_box") is False:
                seen.pop("error", None)
                break
        seen.update(app_page=is_app_page(window.get_current_url()), guarded=api._current_url is not None)
        window.destroy()

    api = Api(connect=None, ports=lambda: [])
    window = _open_window(api, f"{APP_NAME} self-test", width=500, height=250)
    webview.start(probe, window)
    print(json.dumps(seen), flush=True)
    return 0 if seen.get("bands", 0) > 1 and seen.get("cable") is False and seen.get("quiz_box") is False \
        and "error" not in seen \
        and seen.get("app_page") is True and seen.get("guarded") is True else 1


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        code = self_test()
    else:
        import webview

        _open_window(Api(settings_path=saved.settings_file()), APP_NAME, width=1100, height=900, min_size=(480, 600))
        webview.start()
        code = 0
    # The window is closed: exit now, without waiting for other threads. pywebview runs each call from
    # the page on a non-daemon thread that hands its answer back through the window; one still running
    # when the window closes can wait forever, and Python would wait for it (beta.10's built app hung
    # after its self-test 3 runs in 5, 2026-11-16). Nothing left needs them: settings are written
    # whole before a call answers (and swapped in, so never half-written), and the OS closes the port.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
