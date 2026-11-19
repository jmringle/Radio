"""The Python side of the app: what the window's page may call (window.pywebview.api).

Tested directly with the fake NanoVNA: no window, no hardware. Every answer is a plain dict the
page can show; nothing is raised into the page."""

import threading
from pathlib import PurePosixPath

import pytest
from fakes import FakeLink, UnpluggedLink, recorded
from test_analysis import antenna
from test_balun import Z0, rising, sweep as transformer_sweep
from test_cable_cli import fake_nano as fake_cable_nano
from test_cable_cli import planned
from test_device import Port

from dipstick.app import PAGE, Api, connect_nanovna, is_app_page
from dipstick.settings import settings_file
from dipstick.device import DeviceError, NanoVNA
from dipstick.s11 import reading

SETTINGS = b"sweep\r\n1500000 30000000 101\r\nch> "
RESTORE = b"sweep 1500000 30000000 101"


def fake_nano(scan_command, scan_reply):
    return NanoVNA(FakeLink({b"sweep": SETTINGS, scan_command: scan_reply, RESTORE: RESTORE + b"\r\nch> "}))


def reply_for(command, readings):
    body = b"".join(f"{r.hz} {r.s11.real:.9f} {r.s11.imag:.9f} \r\n".encode() for r in readings)
    return command + b"\r\n" + body + b"ch> "


def good_40m():
    command = b"scan 7000000 7300000 101 3"
    return fake_nano(command, reply_for(command, antenna(7_153_000, 60_000)))


def test_bands_for_the_picker():
    bands = Api(connect=None).bands()
    assert bands[:3] == ["160m", "80m", "40m"] and "70cm" in bands and "60m" not in bands


def test_a_sweep_returns_the_report_and_both_plots():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "", 101)
    assert answer["ok"] is True
    assert "best match SWR 1.00 at 7.153 MHz" in answer["report"]
    assert answer["swr_svg"].startswith("<svg") and answer["smith_svg"].startswith("<svg")


def test_the_plots_have_no_inline_styles_for_the_window():
    # The window's Content Security Policy blocks inline styles; its stylesheet colors the plots.
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "", 101)
    assert "<style" not in answer["swr_svg"] and "<style" not in answer["smith_svg"]


def test_a_target_alone_picks_the_band():
    # 146.520 MHz is in 2 m (144-148). Readings 40 kHz apart; 146.520 is reading 63.
    command = b"scan 144000000 148000000 101 3"
    readings = antenna(146_520_000, 500_000, start=144_000_000, stop=148_000_000)
    nano = fake_nano(command, reply_for(command, readings))
    answer = Api(connect=lambda port: nano).sweep("", "146.520", 101)
    assert answer["ok"] is True and answer["band"] == "2m"
    assert "best match SWR 1.00 at 146.520 MHz" in answer["report"]


def test_the_answer_names_the_band_swept():
    assert Api(connect=lambda port: good_40m()).sweep("40m", "", 101)["band"] == "40m"


def test_the_target_is_used():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "7.074", 101)
    assert "to move the best match to 7.074 MHz" in answer["report"]


def test_points_may_arrive_as_text_from_the_page():
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    assert Api(connect=lambda port: nano).sweep("40m", "", "11")["ok"] is True


@pytest.mark.parametrize("band, target, points, words", [
    ("41m", "", 101, "41m"),
    ("40m", "14.074", 101, "outside the band"),
    ("40m", "abc", 101, "target"),
    ("40m", "", 500, "2 to 101"),
    ("40m", "", "lots", "Points"),
    ("40m", "", True, "Points"),
    ("40m", "", 50.5, "Points"),
    (None, "", 101, "band"),
    ("", "", 101, "Choose a band, or type a target frequency"),
    ("", "27.185", 101, "27.185 MHz isn't in an amateur band"),   # CB channel 19
    ("", "5.3305", 101, "isn't in an amateur band"),              # 60 m: channels, left out
    ("", "146.5.2", 101, "target"),
])
def test_bad_requests_are_answered_never_raised_and_never_connect(band, target, points, words):
    connected = []
    api = Api(connect=lambda port: connected.append(port))
    answer = api.sweep(band, target, points)
    assert answer == {"ok": False, "error": answer["error"]}
    assert words in answer["error"]
    assert connected == []


def test_device_errors_come_back_as_messages():
    def no_nanovna(port):
        raise DeviceError("No NanoVNA found. Is it plugged in?")
    assert Api(connect=no_nanovna).sweep("40m", "", 101) == {"ok": False, "error": "No NanoVNA found. Is it plugged in?"}


def test_unplugged_mid_sweep_is_explained_not_unexpected():
    nano = NanoVNA(UnpluggedLink({b"sweep": SETTINGS}, unplug_on=b"scan"))
    answer = Api(connect=lambda port: nano).sweep("40m", "", 101)
    assert answer["ok"] is False
    assert "The NanoVNA disconnected" in answer["error"]
    assert "set it by hand: 1.5 to 30 MHz, 101 points" in answer["error"]


def test_an_unexpected_error_is_a_message_too(capsys):
    def broken(port):
        raise RuntimeError("bug")
    answer = Api(connect=broken).sweep("40m", "", 101)
    assert answer["ok"] is False and "Unexpected error" in answer["error"] and "RuntimeError" in answer["error"]
    assert "bug" in capsys.readouterr().err  # the details go to the log, not the page


def test_only_one_sweep_at_a_time():
    # pywebview runs each call from the page on its own thread, so two clicks can overlap.
    started, release = threading.Event(), threading.Event()

    def slow(port):
        started.set()
        release.wait(5)
        return good_40m()

    api = Api(connect=slow)
    results = {}
    first = threading.Thread(target=lambda: results.update(first=api.sweep("40m", "", 101)))
    first.start()
    assert started.wait(5)
    results["second"] = api.sweep("40m", "", 101)
    release.set()
    first.join(5)
    assert results["second"] == {"ok": False, "error": "A sweep is already running"}
    assert results["first"]["ok"] is True


# --- is a NanoVNA plugged in? (the page asks every couple of seconds) --------------------------
# Only the computer's list of USB serial ports is read: the port is never opened, so asking can't
# disturb a sweep or send the NanoVNA anything.

NANO = Port("/dev/cu.usbmodem401", 0x0483, 0x5740, "NanoVNA-H")
RADIO = Port("/dev/cu.usbserial-1410", 0x10C4, 0xEA60, "CP2102 USB to UART")


def status(ports):
    return Api(connect=None, ports=lambda: ports).nanovna()


def test_status_connected_names_the_port():
    assert status([RADIO, NANO]) == {"connected": True, "text": "NanoVNA connected (/dev/cu.usbmodem401)"}


def test_status_not_found():
    assert status([RADIO]) == {"connected": False, "text": "No NanoVNA found. Is it plugged in and switched on?"}


def test_status_names_a_nanovna_with_original_firmware():
    # See test_device.py: the original firmware's generic USB name. The header says which port
    # it may be and to choose it in the picker below; it still isn't connected by itself (T3).
    original = Port("/dev/cu.usbmodem1", 0x0483, 0x5740, "ChibiOS/RT Virtual COM Port")
    answer = status([RADIO, original])
    assert answer["connected"] is False
    assert "original NanoVNA firmware" in answer["text"] and "/dev/cu.usbmodem1" in answer["text"]
    assert "--port" not in answer["text"]


def test_status_more_than_one():
    other = Port("/dev/cu.usbmodem402", 0x0483, 0x5740, "NanoVNA-H")
    answer = status([NANO, other])
    assert answer["connected"] is False
    assert answer["text"] == "More than one NanoVNA is plugged in (/dev/cu.usbmodem401, /dev/cu.usbmodem402); unplug one"


def test_a_sweep_with_two_nanovnas_says_unplug_one_not_use_port():
    # The app has no --port option, so the command's advice would be no help here.
    other = Port("/dev/cu.usbmodem402", 0x0483, 0x5740, "NanoVNA-H")
    api = Api(connect=lambda port: connect_nanovna(port, ports=lambda: [NANO, other]))
    for answer in (api.sweep("40m", "", 101), api.cable(True, "0.66", "", "50")):
        assert answer == {"ok": False, "error": "Found more than one NanoVNA "
                                                "(/dev/cu.usbmodem401, /dev/cu.usbmodem402); unplug one"}


def test_a_sweep_with_no_nanovna_never_mentions_port():
    api = Api(connect=lambda port: connect_nanovna(port, ports=lambda: [RADIO]))
    for answer in (api.sweep("40m", "", 101), api.cable(True, "0.66", "", "50")):
        assert answer == {"ok": False, "error": "No NanoVNA found. Is it plugged in and switched on? "
                                                "Serial ports: /dev/cu.usbserial-1410."}


def test_status_never_connects():
    def connect(port):
        raise AssertionError("status must not open the port")
    Api(connect=connect, ports=lambda: [NANO]).nanovna()


def test_the_page_can_only_reach_public_methods():
    # pywebview exposes an object's public methods (and walks its public attributes): keep the
    # connection and lock private so the page can't reach them.
    public = {name for name in vars(Api(connect=None)) if not name.startswith("_")}
    assert public == set()
    assert {name for name in dir(Api) if not name.startswith("_")} == {"bands", "cable", "calibrate", "choke", "forget_ports", "loss", "nanovna",
                                                                         "serial_ports", "set_detail", "set_quiz", "settings", "sweep",
                                                                         "transformer", "use_port"}


# --- the cable check: a wide sweep, so only with no antenna connected (T5) ---------------------

def cable_api(nano):
    return Api(connect=lambda port: nano)


@pytest.mark.parametrize("no_antenna", [False, None, "true", 1, "yes"])
def test_cable_refused_unless_no_antenna_is_exactly_true(no_antenna):
    # Only the checkbox's own true counts: never a truthy look-alike from a bug in the page.
    connected = []
    answer = Api(connect=lambda port: connected.append(port)).cable(no_antenna, "0.66", "", "50")
    assert answer["ok"] is False and "outside the ham bands" in answer["error"]
    assert "No antenna connected" in answer["error"] and "--" not in answer["error"]
    assert connected == []


def test_cable_length_with_the_smith_chart():
    answer = cable_api(fake_cable_nano(planned(12.0, 0.66))).cable(True, "0.66", "", "50")
    assert answer["ok"] is True
    assert "Length: 12.00 m (39.4 ft) at velocity factor 0.66" in answer["report"]
    assert answer["smith_svg"].startswith("<svg") and "<style" not in answer["smith_svg"]


def test_cable_velocity_factor_from_a_length_in_feet():
    answer = cable_api(fake_cable_nano(planned(15.24, 0.78, plan_vf=None))).cable(True, "", "50ft", "50")
    assert "Velocity factor: 0.78 (for a 15.24 m / 50.0 ft cable)" in answer["report"]


def test_cable_report_names_the_apps_field_not_the_option():
    answer = cable_api(fake_cable_nano(planned(20.0, 0.66))).cable(True, "0.66", "", "50")
    assert "Measurable up to 50 m with this sweep; for a longer cable raise Longest cable." in answer["report"]
    assert "--" not in answer["report"]


@pytest.mark.parametrize("length, said", [
    (".6", "0.60 m / 2.0 ft"),        # a leading point, like the velocity factor allows
    ("6in", "0.15 m / 0.5 ft"),       # 6 inches = 0.1524 m
    ("6 in", "0.15 m / 0.5 ft"),
    ('6"', "0.15 m / 0.5 ft"),
    ("6 inch", "0.15 m / 0.5 ft"),
    ("6 inches", "0.15 m / 0.5 ft"),
    ("18.5in", "0.47 m / 1.5 ft"),    # 0.4699 m
    ("6 IN", "0.15 m / 0.5 ft"),      # units in any case (QA 2026-11-16)
    ("6In", "0.15 m / 0.5 ft"),
    ("6 Inches", "0.15 m / 0.5 ft"),
])
def test_cable_short_lengths_in_inches_or_with_a_leading_point(length, said):
    meters = {".6": 0.6, "18.5in": 0.4699}.get(length, 0.1524)
    answer = cable_api(fake_cable_nano(planned(meters, 0.78, plan_vf=None))).cable(True, "", length, "50")
    assert f"Velocity factor: 0.78 (for a {said} cable)" in answer["report"], answer


def test_feet_in_capitals_are_feet():
    connected = []
    Api(connect=lambda port: connected.append(port)).cable(True, "", "2001FT", "50")
    assert connected  # accepted as 2001 ft (610 m); as meters, or as an unknown unit, it never connects


# A pasted wall of text comes back cut short, not in full (QA 2026-11-16, F1).
JUNK = "1" * 300


@pytest.mark.parametrize("call", [
    lambda api: api.sweep("40m", JUNK, 101),          # outside the band
    lambda api: api.sweep("40m", "x" + JUNK, 101),    # not a frequency
    lambda api: api.sweep("40m", "", "x" + JUNK),     # points
    lambda api: api.cable(True, "x" + JUNK, "", "50"),
    lambda api: api.cable(True, "", "x" + JUNK, "50"),
    lambda api: api.cable(True, "", JUNK, "50"),      # a number, but too long a cable
    lambda api: api.cable(True, "0.66", "", "x" + JUNK),
    lambda api: api.calibrate("40m", "x" + JUNK),
], ids=["target-outside", "target-junk", "points", "vf", "length-junk", "length-huge", "longest", "cal-step"])
def test_long_input_is_cut_short_in_the_error(call):
    error = call(Api(connect=lambda port: pytest.fail("never connects")))["error"]
    assert JUNK[:60] not in error and "…" in error, error
    assert len(error) < 200, error


def test_short_input_is_echoed_whole():
    assert "got 'abc'" in Api(connect=None).sweep("40m", "abc", 101)["error"]


@pytest.mark.parametrize("vf, length, longest, words", [
    ("", "", "50", "Give Velocity factor or Length (one of them)"),
    ("  ", "  ", "50", "Give Velocity factor or Length"),
    ("0.66", "10", "50", "Give Velocity factor or Length"),
    ("1.5", "", "50", "Velocity factor must be a velocity factor above 0 and at most 1"),
    ("abc", "", "50", "Velocity factor must be"),
    ("", "ten", "50", "Length must be a length like 15.2"),
    ("", "2001", "50", "Length must be above 0 and at most 2000 m"),
    ("", "6.", "50", "Length must be a length like 15.2 (meters), 50ft or 6in"),
    ("", ".", "50", "Length must be a length"),
    ("", "6 yd", "50", "Length must be a length"),
    ("", "6inchs", "50", "Length must be a length"),
    ("", "0in", "50", "Length must be above 0"),
    ("0.66", "", "0", "Longest cable must be above 0"),
    ("0.66", "", "", "Longest cable must be a length"),
    ("0.66", "", "7000ft", "Longest cable must be above 0 and at most 2000 m"),
    (0.66, "", "50", "Velocity factor must be typed as text"),
    ("0.66", "", None, "Longest cable must be a length"),
])
def test_cable_bad_settings_are_explained_in_the_apps_words_and_never_connect(vf, length, longest, words):
    connected = []
    answer = Api(connect=lambda port: connected.append(port)).cable(True, vf, length, longest)
    assert answer == {"ok": False, "error": answer["error"]}
    assert words in answer["error"] and "--" not in answer["error"]
    assert connected == []


def test_cable_unplugged_mid_sweep():
    nano = NanoVNA(UnpluggedLink({b"sweep": SETTINGS}, unplug_on=b"scan"))
    answer = cable_api(nano).cable(True, "0.66", "", "50")
    assert answer["ok"] is False and "The NanoVNA disconnected" in answer["error"]
    assert "set it by hand: 1.5 to 30 MHz, 101 points" in answer["error"]


def test_cable_and_band_sweeps_take_turns():
    # One NanoVNA: a cable check can't start while a band sweep is running.
    started, release = threading.Event(), threading.Event()

    def slow(port):
        started.set()
        release.wait(5)
        return good_40m()

    api = Api(connect=slow)
    results = {}
    first = threading.Thread(target=lambda: results.update(band=api.sweep("40m", "", 101)))
    first.start()
    assert started.wait(5)
    results["cable"] = api.cable(True, "0.66", "", "50")
    release.set()
    first.join(5)
    assert results["cable"] == {"ok": False, "error": "A sweep is already running"}
    assert results["band"]["ok"] is True


def test_cable_unexpected_error_is_a_message(capsys):
    def broken(port):
        raise RuntimeError("bug")
    answer = Api(connect=broken).cable(True, "0.66", "", "50")
    assert answer["ok"] is False and "Unexpected error (RuntimeError)" in answer["error"]


# Calibrating (the Calibrate tab): open, short, load, in that order, over one band. Only the
# calibration in the NanoVNA's memory changes; nothing is saved (no `save`), so switching it off
# and on brings the saved calibration back.
def echo(*commands):
    return {c: c + b"\r\nch> " for c in commands}


class Calibrator:
    """A fake NanoVNA per step, recording everything sent across steps."""

    def __init__(self, link_class=FakeLink, **kwargs):
        self.sent, self.connects = [], 0
        self.link_class, self.kwargs = link_class, kwargs

    def __call__(self, port):
        self.connects += 1
        link = self.link_class(echo(b"", b"sweep 7000000 7300000 101", b"sweep 14000000 14350000 101",
                                    b"sweep 1800000 54000000 101",
                                    *(b"cal " + s for s in (b"reset", b"open", b"short", b"load", b"isoln", b"thru", b"done"))),
                               **self.kwargs)
        link.written = self.sent
        return NanoVNA(link)

    def commands(self):
        return [c.removesuffix(b"\r") for c in self.sent if c != b"\r"]  # \r alone: the connect sync


def test_calibrating_open_short_load_over_the_band():
    nano = Calibrator()
    api = Api(connect=nano)
    assert api.calibrate("40m", "open") == {"ok": True, "next": "short"}
    assert api.calibrate("40m", "short") == {"ok": True, "next": "load"}
    assert api.calibrate("40m", "load") == {"ok": True, "next": None}
    assert nano.commands() == [b"sweep 7000000 7300000 101", b"cal reset", b"cal open",
                               b"cal short", b"cal load", b"cal done"]
    assert not any(c.startswith((b"save", b"recall")) for c in nano.commands())


def test_open_always_starts_over():
    nano = Calibrator()
    api = Api(connect=nano)
    api.calibrate("40m", "open")
    api.calibrate("40m", "short")
    assert api.calibrate("20m", "open") == {"ok": True, "next": "short"}
    assert nano.commands()[-3:] == [b"sweep 14000000 14350000 101", b"cal reset", b"cal open"]
    assert api.calibrate("20m", "short") == {"ok": True, "next": "load"}


@pytest.mark.parametrize("before, step, words", [
    ([], "short", "Start with the open"),
    ([], "load", "Start with the open"),
    (["open"], "load", "Measure the short next"),
    (["open", "short", "load"], "short", "Start with the open"),  # finished: a new calibration starts with open
])
def test_steps_out_of_order_are_refused_and_never_connect(before, step, words):
    nano = Calibrator()
    api = Api(connect=nano)
    for done in before:
        api.calibrate("40m", done)
    connects = nano.connects
    answer = api.calibrate("40m", step)
    assert answer["ok"] is False and words in answer["error"]
    assert nano.connects == connects


def test_changing_band_partway_is_refused():
    nano = Calibrator()
    api = Api(connect=nano)
    api.calibrate("40m", "open")
    answer = api.calibrate("20m", "short")
    assert answer["ok"] is False and "40m" in answer["error"] and "Start with the open" in answer["error"]


@pytest.mark.parametrize("band, step", [("60m", "open"), ("", "open"), (None, "open"), (7, "open"),
                                        ("40m", "save"), ("40m", "thru"), ("40m", "done"), ("40m", "reset"),
                                        ("40m", ""), ("40m", None), ("40m", 1), ("40m", "open\rsave 0")])
def test_bad_calibration_requests_are_answered_and_never_connect(band, step):
    nano = Calibrator()
    answer = Api(connect=nano).calibrate(band, step)
    assert answer["ok"] is False and answer["error"]
    assert nano.connects == 0


def test_a_failed_step_can_be_tried_again():
    nano = Calibrator()
    api = Api(connect=nano)
    api.calibrate("40m", "open")
    api._connect = Calibrator(UnpluggedLink, unplug_on=b"cal short")
    answer = api.calibrate("40m", "short")
    assert answer["ok"] is False and "The NanoVNA disconnected" in answer["error"]
    api._connect = nano
    assert api.calibrate("40m", "short") == {"ok": True, "next": "load"}


# After `cal reset` the NanoVNA's calibration in memory is unfinished until `cal done`; a failed step
# must say how to get the saved one back (QA 2026-11-16). Power cycling reloads the saved calibration
# (firmware source read 2026-11-15, see the README).
POWER_CYCLE = "switch the NanoVNA off and on"


@pytest.mark.parametrize("fails_on, done_before", [(b"cal open", []), (b"cal short", ["open"]),
                                                   (b"cal load", ["open", "short"])])
def test_a_step_failing_after_the_reset_says_how_to_get_the_saved_calibration_back(fails_on, done_before):
    api = Api(connect=Calibrator())
    for step in done_before:
        api.calibrate("40m", step)
    api._connect = Calibrator(UnpluggedLink, unplug_on=fails_on)
    answer = api.calibrate("40m", fails_on.decode().split()[1])
    assert answer["ok"] is False and "The NanoVNA disconnected" in answer["error"]
    assert POWER_CYCLE in answer["error"]


def test_a_failure_before_the_reset_leaves_the_calibration_alone_and_says_nothing_of_it():
    api = Api(connect=Calibrator(UnpluggedLink, unplug_on=b"sweep"))
    answer = api.calibrate("40m", "open")
    assert answer["ok"] is False and "The NanoVNA disconnected" in answer["error"]
    assert POWER_CYCLE not in answer["error"]


def test_a_finished_calibration_is_not_called_unfinished_later():
    api = Api(connect=Calibrator())
    for step in ("open", "short", "load"):
        api.calibrate("40m", step)
    api._connect = Calibrator(UnpluggedLink, unplug_on=b"sweep")
    assert POWER_CYCLE not in api.calibrate("40m", "open")["error"]


# --- both ports: isolation and thru after the load, for the S21 tests (nanovna.com calibration page,
# read 2026-11-17: open, short, load, isoln, thru, done; with one load, it stays on CH0 for isoln) ---

BOTH = ("open", "short", "load", "isoln", "thru")


def test_calibrating_both_ports_adds_isolation_and_thru_and_applies_after_thru():
    nano = Calibrator()
    api = Api(connect=nano)
    nexts = [api.calibrate("40m", step, False, True) for step in BOTH]
    assert nexts == [{"ok": True, "next": n} for n in ("short", "load", "isoln", "thru", None)]
    assert nano.commands() == [b"sweep 7000000 7300000 101", b"cal reset", b"cal open", b"cal short",
                               b"cal load", b"cal isoln", b"cal thru", b"cal done"]


def test_calibrating_both_ports_over_hf_wide():
    api = Api(connect=Calibrator())
    assert [api.calibrate("wide", step, True, True)["next"] for step in BOTH] == ["short", "load", "isoln", "thru", None]


@pytest.mark.parametrize("before, step, both_ports, words", [
    ([], "isoln", True, "Start with the open"),
    (["open", "short"], "isoln", True, "Measure the load next"),
    (["open", "short", "load"], "thru", True, "Measure the isolation next"),
    (["open", "short"], "load", False, "Start with the open"),     # switched to one port partway
    (["open"], "short", False, "Start with the open"),
])
def test_both_ports_steps_out_of_order_or_switched_partway_are_refused(before, step, both_ports, words):
    nano = Calibrator()
    api = Api(connect=nano)
    for done in before:
        api.calibrate("40m", done, False, True)
    connects = nano.connects
    answer = api.calibrate("40m", step, False, both_ports)
    assert answer["ok"] is False and words in answer["error"]
    assert nano.connects == connects


def test_switching_to_both_ports_partway_is_refused():
    api = Api(connect=Calibrator())
    api.calibrate("40m", "open")
    answer = api.calibrate("40m", "short", False, True)
    assert answer["ok"] is False and "Start with the open" in answer["error"]


@pytest.mark.parametrize("both_ports", [1, "true", None, "yes"])
def test_both_ports_must_be_exactly_true_or_false(both_ports):
    nano = Calibrator()
    answer = Api(connect=nano).calibrate("40m", "open", False, both_ports)
    assert answer["ok"] is False and "Both ports" in answer["error"]
    assert nano.connects == 0


@pytest.mark.parametrize("fails_on, done_before", [(b"cal isoln", BOTH[:3]), (b"cal thru", BOTH[:4])])
def test_a_two_port_step_failing_says_how_to_get_the_saved_calibration_back(fails_on, done_before):
    api = Api(connect=Calibrator())
    for step in done_before:
        api.calibrate("40m", step, False, True)
    api._connect = Calibrator(UnpluggedLink, unplug_on=fails_on)
    answer = api.calibrate("40m", fails_on.decode().split()[1], False, True)
    assert answer["ok"] is False and POWER_CYCLE in answer["error"]


def test_after_the_load_a_two_port_calibration_is_not_finished():
    # The NanoVNA isn't corrected until `cal done`, after the thru: the sweep report keeps its reminder.
    api = Api(connect=Calibrator())
    for step in BOTH[:3]:
        api.calibrate("40m", step, False, True)
    assert api._calibrated_band is None


class MeasuringLink(FakeLink):
    """Quiet for 30 reads (7.5 s at the 0.25 s read timeout, past the usual 5 s) while measuring a standard."""

    def write(self, data):
        self.quiet = 30 if data.startswith((b"cal open", b"cal short", b"cal load", b"cal isoln", b"cal thru")) else 0
        return super().write(data)

    def read(self, size=1):
        if getattr(self, "quiet", 0):
            self.quiet -= 1
            return b""
        return super().read(size)


def test_calibration_steps_wait_longer_for_the_measurement():
    # The NanoVNA answers a step only after sweeping the standard, which is slower than a reply.
    assert Api(connect=Calibrator(MeasuringLink)).calibrate("40m", "open") == {"ok": True, "next": "short"}


def test_two_port_steps_wait_longer_too():
    api = Api(connect=Calibrator(MeasuringLink))
    assert [api.calibrate("40m", step, False, True)["ok"] for step in BOTH] == [True] * 5


def test_calibrating_and_sweeping_take_turns():
    started, release = threading.Event(), threading.Event()

    def slow(port):
        started.set()
        release.wait(5)
        return good_40m()

    api = Api(connect=slow)
    results = {}
    first = threading.Thread(target=lambda: results.update(band=api.sweep("40m", "", 101)))
    first.start()
    assert started.wait(5)
    results["cal"] = api.calibrate("40m", "open")
    release.set()
    first.join(5)
    assert results["cal"] == {"ok": False, "error": "A sweep is already running"}


def test_a_failed_open_means_starting_over():
    # The open step resets the calibration in memory first, so after it fails nothing is half done.
    api = Api(connect=Calibrator())
    api.calibrate("40m", "open")
    api._connect = Calibrator(UnpluggedLink, unplug_on=b"cal open")
    assert api.calibrate("40m", "open")["ok"] is False
    assert "Start with the open" in api.calibrate("40m", "short")["error"]


# --- only dipstick's own page may reach the NanoVNA (security review 2026-11-16) -----------------
# pywebview gives its bridge to whatever page the window shows, and on macOS a dropped file or a link
# dragged in from a browser navigates the window (checked in a real window: both pages could call
# Python). Such a page could send `cal reset` or a wide cable sweep with an antenna on. So every call
# that reaches the NanoVNA first checks the window is still on index.html.

@pytest.mark.parametrize("url", [
    PAGE.as_uri(),
    PAGE.as_uri() + "#section",                         # same page
    "file://localhost" + PAGE.as_uri().removeprefix("file://"),
])
def test_the_app_page_is_recognized(url):
    assert is_app_page(url)


@pytest.mark.parametrize("url", [
    None, "", "about:blank",
    "http://127.0.0.1:8000/index.html",                 # a web page, even a local one
    "https://example.com/" + PAGE.as_uri(),
    PAGE.with_name("other.html").as_uri(),              # another file beside it
    (PAGE.parent.parent / "index.html").as_uri(),       # same name, another folder
    "file://example.com" + PAGE.as_uri().removeprefix("file://"),  # a file on another machine
    "data:text/html,<p>hi</p>",
])
def test_anything_else_is_not_the_app_page(url):
    assert not is_app_page(url)


def test_a_page_in_a_folder_with_spaces_is_recognized(tmp_path):
    page = tmp_path / "My Apps" / "index.html"
    page.parent.mkdir()
    page.write_text("")
    assert "%20" in page.as_uri()
    assert is_app_page(page.as_uri(), page)


@pytest.mark.parametrize("call", [
    lambda api: api.sweep("40m", "", 101),
    lambda api: api.cable(True, "0.66", "", "50"),
    lambda api: api.calibrate("40m", "open"),
    lambda api: api.transformer(True, "49:1", ""),
    lambda api: api.calibrate("wide", "open", True),
    lambda api: api.choke(True),
    lambda api: api.loss(True, "direct"),
], ids=["sweep", "cable", "calibrate", "transformer", "calibrate wide", "choke", "loss"])
def test_another_page_is_refused_and_never_connects(call):
    api = Api(connect=lambda port: pytest.fail("never connects"))
    api._current_url = lambda: "http://127.0.0.1:8000/evil.html"
    answer = call(api)
    assert answer["ok"] is False and "Only Dipstick's own page" in answer["error"]


def test_the_app_page_gets_through_the_check():
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    api = Api(connect=lambda port: nano)
    api._current_url = lambda: PAGE.as_uri()
    assert api.sweep("40m", "", 11)["ok"] is True


# --- UI review 2026-11-16: the target on the plot, and the recalibrate reminder only when it helps --

def test_the_swr_plot_marks_the_target():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "7.074", 101)
    assert 'class="target"' in answer["swr_svg"] and "target 7.074" in answer["swr_svg"]


def calibrated_then_swept(steps):
    cal = Calibrator()
    nano = [cal]
    api = Api(connect=lambda port: nano[0](port))
    for step in steps:
        assert api.calibrate("40m", step)["ok"] is True
    nano[0] = lambda port: good_40m()
    return api.sweep("40m", "", 101)["report"]


def test_never_calibrated_here_the_report_reminds_you_to():
    assert "recalibrate" in calibrated_then_swept([])


def test_just_calibrated_the_report_leaves_out_the_reminder():
    # The page adds its own note if the band swept isn't the one calibrated.
    assert "recalibrate" not in calibrated_then_swept(["open", "short", "load"])


def test_a_calibration_started_and_not_finished_brings_the_reminder_back():
    # `cal reset` was sent at the open step: the NanoVNA holds no calibration until load finishes.
    cal = Calibrator()
    nano = [cal]
    api = Api(connect=lambda port: nano[0](port))
    for step in ("open", "short", "load", "open"):
        api.calibrate("40m", step)
    nano[0] = lambda port: good_40m()
    assert "recalibrate" in api.sweep("40m", "", 101)["report"]


# --- Phase 4: "Check yourself" questions travel with the answer -----------------------------------

def test_a_sweep_answer_carries_its_questions():
    quiz = Api(connect=lambda port: good_40m()).sweep("40m", "", 101)["quiz"]
    assert 1 <= len(quiz) <= 3
    for q in quiz:
        assert set(q) == {"ask", "choices", "answer", "why"}
        assert isinstance(q["choices"], list) and 0 <= q["answer"] < len(q["choices"])


def test_nothing_connected_carries_no_questions():
    command = b"scan 7000000 7300000 101 3"
    readings = [reading(7_000_000 + i * 3000, complex(0.9999, -0.0003)) for i in range(101)]  # an open port
    nano = fake_nano(command, reply_for(command, readings))
    assert Api(connect=lambda port: nano).sweep("40m", "", 101)["quiz"] == []


def test_a_cable_answer_carries_its_questions():
    answer = Api(connect=lambda port: fake_cable_nano(planned(12.0, 0.66))).cable(True, "0.66", "", "50 m")
    assert answer["ok"] is True and 1 <= len(answer["quiz"]) <= 2


# --- turning "Check yourself" off and on (2026-11-16): remembered in a small settings file -----------
# The file is input like any other: anyone with the account can edit it, and a crash or a full disk
# can leave half of it. Anything odd falls back to the default (on), never an error.

def test_check_yourself_starts_on(tmp_path):
    assert Api(connect=None, settings_path=tmp_path / "settings.json").settings() == {"quiz": True, "detail": False}


def test_turning_it_off_is_remembered_by_the_next_launch(tmp_path):
    path = tmp_path / "dipstick" / "settings.json"  # the folder doesn't exist yet
    assert Api(connect=None, settings_path=path).set_quiz(False) == {"ok": True}
    assert Api(connect=None, settings_path=path).settings() == {"quiz": False, "detail": False}
    assert Api(connect=None, settings_path=path).set_quiz(True) == {"ok": True}
    assert Api(connect=None, settings_path=path).settings() == {"quiz": True, "detail": False}


@pytest.mark.parametrize("on", ["false", 0, 1, None, [], {"quiz": False}])
def test_only_true_or_false_is_accepted(tmp_path, on):
    path = tmp_path / "settings.json"
    api = Api(connect=None, settings_path=path)
    answer = api.set_quiz(on)
    assert answer["ok"] is False and "on or off" in answer["error"]
    assert api.settings() == {"quiz": True, "detail": False}
    assert not path.exists()


@pytest.mark.parametrize("content", [
    b"", b"{", b"not json", b"[false]", b'"quiz"', b'{"quiz": "no"}', b'{"quiz": 0}', b'{"quiz": null}',
    b"\xff\xfe\x00", b'{"quiz": false' + b" " * 5000 + b"}",  # undecodable; too big to be ours
], ids=["empty", "half", "text", "list", "string", "word", "zero", "null", "bytes", "huge"])
def test_a_broken_or_strange_file_means_on(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    assert Api(connect=None, settings_path=path).settings() == {"quiz": True, "detail": False}


# --- More detail: open or closed, remembered like the quiz box (display review 2026-11-19) ---------

def test_a_sweep_answers_the_tune_section_and_the_detail_apart():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "", 101)
    assert answer["report"].startswith("40m: best match SWR 1.00 at 7.153 MHz")
    assert "bandwidth (no tuner needed)" in answer["report"] and "For the curious" not in answer["report"]
    assert answer["detail"].startswith("What the NanoVNA measured") and "For the curious" in answer["detail"]


def test_a_sweep_takes_the_antennas_length_for_inches():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "7.074", 101, "66 ft")
    assert "From the antenna length you gave: 66.0 ft" in answer["report"]


def test_with_no_length_the_estimate_names_the_apps_field():
    answer = Api(connect=lambda port: good_40m()).sweep("40m", "7.074", 101, "")
    assert "give its length (Antenna length)" in answer["report"]


@pytest.mark.parametrize("length, words", [("long", "must be a length like"), (66, "typed as text"),
                                           ("999m", "at most 200 m")])
def test_a_bad_antenna_length_is_explained_in_the_apps_words_and_never_connects(length, words):
    opened = []
    answer = Api(connect=lambda port: opened.append(port)).sweep("40m", "", 101, length)
    assert answer["ok"] is False and "Antenna length" in answer["error"] and words in answer["error"]
    assert opened == []


def test_more_detail_starts_closed_and_is_remembered(tmp_path):
    path = tmp_path / "settings.json"
    assert Api(connect=None, settings_path=path).set_detail(True) == {"ok": True}
    assert Api(connect=None, settings_path=path).settings() == {"quiz": True, "detail": True}
    assert Api(connect=None, settings_path=path).set_detail(False) == {"ok": True}
    assert Api(connect=None, settings_path=path).settings()["detail"] is False


@pytest.mark.parametrize("on", ["true", 1, None, [], {"detail": True}])
def test_more_detail_takes_only_true_or_false(tmp_path, on):
    path = tmp_path / "settings.json"
    api = Api(connect=None, settings_path=path)
    answer = api.set_detail(on)
    assert answer["ok"] is False and "open or closed" in answer["error"]
    assert api.settings()["detail"] is False and not path.exists()


@pytest.mark.parametrize("content", [b'{"detail": "yes"}', b'{"detail": 1}', b'{"detail": null}', b'[true]'])
def test_an_odd_detail_in_the_file_means_closed(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    assert Api(connect=None, settings_path=path).settings()["detail"] is False


def test_another_page_cant_open_more_detail(tmp_path):
    path = tmp_path / "settings.json"
    api = Api(connect=None, settings_path=path)
    api._current_url = lambda: "http://127.0.0.1:8000/evil.html"
    assert "Only Dipstick's own page" in api.set_detail(True)["error"]
    assert not path.exists()


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"quiz": false, "port": "/dev/evil"}')
    assert Api(connect=None, settings_path=path).settings() == {"quiz": False, "detail": False}


def test_a_settings_folder_that_cant_be_read_means_on(tmp_path):
    path = tmp_path / "settings.json"
    path.mkdir()  # a folder where the file should be
    assert Api(connect=None, settings_path=path).settings() == {"quiz": True, "detail": False}


def test_a_failed_save_says_so_and_still_applies_until_quit(tmp_path):
    blocker = tmp_path / "dipstick"
    blocker.write_text("a file where the folder should be")
    api = Api(connect=None, settings_path=blocker / "settings.json")
    answer = api.set_quiz(False)
    assert answer["ok"] is False and "Couldn't save" in answer["error"] and "until you quit" in answer["error"]
    assert api.settings() == {"quiz": False, "detail": False}


def test_with_no_settings_file_nothing_is_saved_but_it_works():
    # The self-test and these tests use no file, so they never change the real one.
    api = Api(connect=None)
    assert api.set_quiz(False) == {"ok": True}
    assert api.settings() == {"quiz": False, "detail": False}


def test_another_page_cant_change_the_setting(tmp_path):
    path = tmp_path / "settings.json"
    api = Api(connect=None, settings_path=path)
    api._current_url = lambda: "http://127.0.0.1:8000/evil.html"
    assert "Only Dipstick's own page" in api.set_quiz(False)["error"]
    assert not path.exists()


def test_it_can_be_changed_during_a_sweep(tmp_path):
    api = Api(connect=None, settings_path=tmp_path / "settings.json")
    answers = []
    api._busy.acquire()  # a sweep is running
    try:
        # In a thread, so a set_quiz that waits for the sweep fails here instead of hanging the run.
        worker = threading.Thread(target=lambda: answers.append(api.set_quiz(False)), daemon=True)
        worker.start()
        worker.join(timeout=2)
        assert answers == [{"ok": True}]
    finally:
        api._busy.release()


@pytest.mark.parametrize("platform, env, expected", [
    ("darwin", {}, "/home/n0call/Library/Application Support/dipstick/settings.json"),
    ("win32", {"APPDATA": "C:/Users/n0call/AppData/Roaming"}, "C:/Users/n0call/AppData/Roaming/dipstick/settings.json"),
    ("win32", {}, "/home/n0call/AppData/Roaming/dipstick/settings.json"),
    ("linux", {}, "/home/n0call/.config/dipstick/settings.json"),
    ("linux", {"XDG_CONFIG_HOME": "/srv/config"}, "/srv/config/dipstick/settings.json"),
    ("linux", {"XDG_CONFIG_HOME": "relative/dir"}, "/home/n0call/.config/dipstick/settings.json"),  # the XDG spec ignores a relative one
])
def test_the_settings_file_lives_where_each_system_keeps_settings(platform, env, expected):
    assert settings_file(platform, env, home=lambda: PurePosixPath("/home/n0call")).as_posix() == expected


# --- a NanoVNA with a generic USB chip (CH340): the person says it's theirs, once (2026-11-16) ---------

CH340 = Port("COM7", 0x1A86, 0x7523, None, "USB-SERIAL CH340 (COM7)")  # a clone, as Windows reports it


def test_a_ch340_is_not_guessed_at():
    # The CH340 is also in radio cables (T3), so it's a choice for the person, never a match.
    assert status([CH340])["connected"] is False
    api = Api(connect=None, ports=lambda: [CH340, RADIO])
    assert api.serial_ports() == {"ports": [
        {"device": "COM7", "id": "1A86:7523", "label": "COM7: USB-SERIAL CH340 (COM7)"},
        {"device": "/dev/cu.usbserial-1410", "id": "10C4:EA60", "label": "/dev/cu.usbserial-1410: CP2102 USB to UART"}],
        "remembered": []}


def test_serial_ports_leaves_out_ports_without_a_usb_id_and_known_nanovnas():
    bluetooth = Port("/dev/cu.Bluetooth-Incoming-Port")
    assert Api(connect=None, ports=lambda: [bluetooth, NANO, CH340]).serial_ports()["ports"] == [
        {"device": "COM7", "id": "1A86:7523", "label": "COM7: USB-SERIAL CH340 (COM7)"}]


def test_choosing_the_port_is_remembered_across_launches(tmp_path):
    path = tmp_path / "dipstick" / "settings.json"
    api = Api(connect=None, ports=lambda: [CH340, RADIO], settings_path=path)
    assert api.use_port("COM7") == {"ok": True}
    assert api.nanovna() == {"connected": True, "text": "NanoVNA connected (COM7)"}
    again = Api(connect=None, ports=lambda: [CH340, RADIO], settings_path=path)  # the next launch
    assert again.nanovna() == {"connected": True, "text": "NanoVNA connected (COM7)"}
    assert again.serial_ports() == {"ports": [{"device": "/dev/cu.usbserial-1410", "id": "10C4:EA60",
                                               "label": "/dev/cu.usbserial-1410: CP2102 USB to UART"}],
                                    "remembered": ["1A86:7523"]}
    assert again.settings() == {"quiz": True, "detail": False}  # the page never sees the remembered ports


def test_a_sweep_connects_to_the_remembered_port(monkeypatch):
    # Never open a real port: a computer running the tests may have a real COM7, and this one did
    # (a CH340 that wasn't a NanoVNA, 2026-11-17), so the test sent it a carriage return.
    tried = []

    def no_real_port(cls, port, read_timeout_s=0.25):
        tried.append(port)
        raise DeviceError(f"Can't open {port}: not in tests")
    monkeypatch.setattr(NanoVNA, "open", classmethod(no_real_port))
    api = Api(connect=connect_nanovna, ports=lambda: [CH340])
    assert "No NanoVNA found" in api.sweep("40m", "", 101)["error"]
    assert tried == []  # not approved yet: nothing opened (T3)
    assert api.use_port("COM7") == {"ok": True}
    assert "Can't open COM7" in api.sweep("40m", "", 101)["error"]
    assert tried == ["COM7"]


def test_use_port_only_for_a_usb_serial_port_that_is_plugged_in(tmp_path):
    api = Api(connect=None, ports=lambda: [CH340, Port("/dev/cu.Bluetooth-Incoming-Port")], settings_path=tmp_path / "s.json")
    for device in ("COM9", "/dev/cu.Bluetooth-Incoming-Port", None, 7, ["COM7"]):
        assert api.use_port(device)["ok"] is False
    assert api.serial_ports()["remembered"] == []
    assert not (tmp_path / "s.json").exists()


def test_forget_ports():
    api = Api(connect=None, ports=lambda: [CH340])
    api.use_port("COM7")
    assert api.forget_ports() == {"ok": True}
    assert api.nanovna()["connected"] is False
    assert api.serial_ports()["remembered"] == []


def test_a_settings_file_with_odd_ports_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"ports": ["1a86:7523", "1A86:7523", "1A86:7523", 7, "../etc", "0483:5740", '
                    '"0483:5740 ", "0483:5740 bad\\u0007", "1A86:7523 USB Serial", "0483:5740 ' + "x" * 65 + '", '
                    '"0483:5740 ChibiOS/RT Virtual COM Port"]}')
    # A plain 0483:5740 (ST's generic ID, saved by builds before 2026-11-17) would accept any STM32
    # gadget, so it's dropped: the person picks the NanoVNA again. A name goes only with that ID.
    assert Api(connect=None, settings_path=path).serial_ports()["remembered"] == [
        "1A86:7523", "0483:5740 ChibiOS/RT Virtual COM Port"]


def test_the_port_choice_is_refused_when_the_window_has_left_the_page():
    api = Api(connect=None, ports=lambda: [CH340])
    api._current_url = lambda: "https://example.com/"
    assert "Only Dipstick's own page" in api.use_port("COM7")["error"]
    assert "Only Dipstick's own page" in api.forget_ports()["error"]


# --- the transformer test (Balun tab): a wide sweep, so only with no antenna connected (T5) --------

TRANSFORMER_SCAN = b"scan 1800000 54000000 101 3"


def transformer_nano(impedance_at=lambda hz: Z0):
    return fake_nano(TRANSFORMER_SCAN, reply_for(TRANSFORMER_SCAN, transformer_sweep(impedance_at)))


@pytest.mark.parametrize("no_antenna", [False, None, "true", 1, "yes"])
def test_transformer_refused_unless_no_antenna_is_exactly_true(no_antenna):
    answer = Api(connect=lambda port: pytest.fail("never connects")).transformer(no_antenna, "49:1", "")
    assert answer["ok"] is False and "outside the ham bands" in answer["error"]
    assert "No antenna connected" in answer["error"] and "--" not in answer["error"]


def test_transformer_returns_the_report_and_the_plot_for_the_window():
    answer = Api(connect=lambda port: transformer_nano(rising)).transformer(True, "49:1", "")
    assert answer["ok"] is True
    assert answer["report"].startswith("49:1 transformer, 2450-ohm resistor: SWR 2 or under on 160m")
    assert 'class="ham-band"' in answer["swr_svg"] and "<style>" not in answer["swr_svg"]


@pytest.mark.parametrize("ratio, resistor, words", [
    ("2:1", "", "Ratio must be one of 1:1, 4:1, 9:1, 49:1"),
    (None, "", "Ratio must be one of"),
    (49, "", "Ratio must be one of"),
    ("49:1", "50", "Resistor must be close to 2450 ohms"),
    ("49:1", "abc", "Resistor must be ohms like 2450"),
    ("49:1", 2450, "Resistor must be typed as text"),
])
def test_transformer_bad_settings_are_explained_in_the_apps_words_and_never_connect(ratio, resistor, words):
    answer = Api(connect=lambda port: pytest.fail("never connects")).transformer(True, ratio, resistor)
    assert answer["ok"] is False and words in answer["error"] and "--" not in answer["error"]


def test_transformer_waits_its_turn():
    api = Api(connect=lambda port: pytest.fail("never connects"))
    api._busy.acquire()
    assert api.transformer(True, "49:1", "") == {"ok": False, "error": "A sweep is already running"}


def test_transformer_nothing_on_the_output_is_a_message():
    answer = Api(connect=lambda port: transformer_nano(lambda hz: float("inf"))).transformer(True, "49:1", "")
    assert answer["ok"] is False and "resistor connected" in answer["error"]


# --- the choke test (Balun tab): S21 through a current balun, wide, so only with no antenna (T5) -----

def choke_nano(z=2000):
    from test_choke import sweep as choke_sweep
    from test_choke_cli import fake_nano as fake_choke_nano
    return fake_choke_nano(choke_sweep(lambda hz: z))[0]


@pytest.mark.parametrize("no_antenna", [False, None, "true", 1, "yes"])
def test_choke_refused_unless_no_antenna_is_exactly_true(no_antenna):
    answer = Api(connect=lambda port: pytest.fail("never connects")).choke(no_antenna)
    assert answer["ok"] is False and "outside the ham bands" in answer["error"]
    assert "No antenna connected" in answer["error"] and "--" not in answer["error"]


def test_choke_returns_the_report():
    answer = Api(connect=lambda port: choke_nano()).choke(True)
    assert answer["ok"] is True and answer["report"].startswith("Choke: good on 160m, ")


def test_choke_waits_its_turn():
    api = Api(connect=lambda port: pytest.fail("never connects"))
    api._busy.acquire()
    assert api.choke(True) == {"ok": False, "error": "A sweep is already running"}


def test_choke_with_nothing_arriving_is_a_message():
    answer = Api(connect=lambda port: choke_nano(float("inf"))).choke(True)
    assert answer["ok"] is False and "between CH0 and CH1" in answer["error"]


@pytest.mark.parametrize("band, steps, reminds", [
    ("wide", BOTH, False),                         # HF wide with both ports: what the choke test needs
    ("wide", ("open", "short", "load"), True),     # no thru
    ("40m", BOTH, True),                           # both ports, but only over 40 m
])
def test_the_choke_report_reminds_unless_calibrated_both_ports_over_hf_wide(band, steps, reminds):
    nano = [Calibrator()]
    api = Api(connect=lambda port: nano[0](port))
    for step in steps:
        assert api.calibrate(band, step, True, steps == BOTH)["ok"] is True
    nano[0] = lambda port: choke_nano()
    assert ("Calibrate tab" in api.choke(True)["report"]) is reminds


def loss_nano(db=0.4):
    from test_choke_cli import fake_nano as fake_two_port_nano
    from test_loss import sweep as loss_sweep
    return fake_two_port_nano(loss_sweep(lambda hz: db))[0]


@pytest.mark.parametrize("no_antenna", [False, None, "true", 1, "yes"])
def test_loss_refused_unless_no_antenna_is_exactly_true(no_antenna):
    answer = Api(connect=lambda port: pytest.fail("never connects")).loss(no_antenna, "direct")
    assert answer["ok"] is False and "outside the ham bands" in answer["error"]
    assert "No antenna connected" in answer["error"] and "--" not in answer["error"]


@pytest.mark.parametrize("connection", ["", "pair", "Direct", None, 2, ["direct"], "x" * 10_000])
def test_loss_refuses_any_other_connection_before_connecting(connection):
    answer = Api(connect=lambda port: pytest.fail("never connects")).loss(True, connection)
    assert answer["ok"] is False and "direct or back-to-back" in answer["error"]
    assert len(answer["error"]) < 300  # long text from the page is cut short, not echoed whole


@pytest.mark.parametrize("connection, first", [
    ("direct", "Through loss, direct: most 0.40 dB"),
    ("back-to-back", "Through loss, each of two transformers back to back: most 0.20 dB"),
])
def test_loss_returns_the_report(connection, first):
    answer = Api(connect=lambda port: loss_nano()).loss(True, connection)
    assert answer["ok"] is True and answer["report"].startswith(first)


def test_loss_waits_its_turn():
    api = Api(connect=lambda port: pytest.fail("never connects"))
    api._busy.acquire()
    assert api.loss(True, "direct") == {"ok": False, "error": "A sweep is already running"}


def test_the_loss_report_reminds_unless_calibrated_both_ports_over_hf_wide():
    nano = [Calibrator()]
    api = Api(connect=lambda port: nano[0](port))
    nano[0] = lambda port: loss_nano()
    assert "Calibrate tab" in api.loss(True, "direct")["report"]
    nano[0] = Calibrator()
    for step in BOTH:
        assert api.calibrate("wide", step, True, True)["ok"] is True
    nano[0] = lambda port: loss_nano()
    assert "Calibrate tab" not in api.loss(True, "direct")["report"]


# --- calibrating over the transformer test's range (HF wide) --------------------------------------

def test_calibrating_hf_wide_covers_the_transformer_sweep_exactly():
    nano = Calibrator()
    api = Api(connect=nano)
    for step, following in (("open", "short"), ("short", "load"), ("load", None)):
        assert api.calibrate("wide", step, True) == {"ok": True, "next": following}
    assert nano.commands() == [b"sweep 1800000 54000000 101", b"cal reset", b"cal open",
                               b"cal short", b"cal load", b"cal done"]


@pytest.mark.parametrize("no_antenna", [False, None, "true", 1])
@pytest.mark.parametrize("step", ["open", "short", "load"])
def test_calibrating_hf_wide_refused_unless_no_antenna_is_exactly_true(no_antenna, step):
    # After calibrating, the NanoVNA keeps sweeping the range on its own: never with an antenna on.
    nano = Calibrator()
    api = Api(connect=nano)
    if step != "open":
        api.calibrate("wide", "open", True)
        if step == "load":
            api.calibrate("wide", "short", True)
    sent = list(nano.commands())
    answer = api.calibrate("wide", step, no_antenna)
    assert answer["ok"] is False and "No antenna connected" in answer["error"]
    assert nano.commands() == sent


def test_a_band_calibration_needs_no_box():
    assert Api(connect=Calibrator()).calibrate("40m", "open")["ok"] is True


def test_after_calibrating_hf_wide_the_transformer_report_leaves_out_the_reminder():
    nano = [Calibrator()]
    api = Api(connect=lambda port: nano[0](port))
    for step in ("open", "short", "load"):
        api.calibrate("wide", step, True)
    nano[0] = lambda port: transformer_nano()
    assert "Calibrate tab" not in api.transformer(True, "49:1", "")["report"]


def test_after_calibrating_a_band_the_transformer_report_still_reminds():
    nano = [Calibrator()]
    api = Api(connect=lambda port: nano[0](port))
    for step in ("open", "short", "load"):
        api.calibrate("40m", step)
    nano[0] = lambda port: transformer_nano()
    assert "Calibrate tab" in api.transformer(True, "49:1", "")["report"]


def test_after_calibrating_hf_wide_a_band_sweep_still_reminds():
    # 0.522 MHz between calibration points: a band sweep is better calibrated over its own band.
    nano = [Calibrator()]
    api = Api(connect=lambda port: nano[0](port))
    for step in ("open", "short", "load"):
        api.calibrate("wide", step, True)
    nano[0] = lambda port: good_40m()
    assert "recalibrate" in api.sweep("40m", "", 101)["report"]


# --- the generic ST ID: a NanoVNA with the original firmware (2026-11-17) -----------------------------
# 0483:5740 is ST's generic ID, also on tinySAs and other STM32 gadgets, so choosing a port with it
# remembers the device's name too: approving the NanoVNA must not approve a tinySA plugged in later (T3).

ORIGINAL_FW = Port("/dev/cu.usbmodem1", 0x0483, 0x5740, "ChibiOS/RT Virtual COM Port", "ChibiOS/RT Virtual COM Port")
TINYSA = Port("/dev/cu.usbmodem9", 0x0483, 0x5740, "tinySA", "tinySA")


def test_choosing_the_generic_st_id_remembers_the_name(tmp_path):
    path = tmp_path / "settings.json"
    api = Api(connect=None, ports=lambda: [ORIGINAL_FW], settings_path=path)
    assert api.serial_ports()["ports"] == [{"device": "/dev/cu.usbmodem1", "id": "0483:5740 ChibiOS/RT Virtual COM Port",
                                            "label": "/dev/cu.usbmodem1: ChibiOS/RT Virtual COM Port"}]
    assert api.use_port("/dev/cu.usbmodem1") == {"ok": True}
    assert api.serial_ports()["remembered"] == ["0483:5740 ChibiOS/RT Virtual COM Port"]
    again = Api(connect=None, ports=lambda: [ORIGINAL_FW], settings_path=path)  # the next launch
    assert again.nanovna() == {"connected": True, "text": "NanoVNA connected (/dev/cu.usbmodem1)"}


def test_approving_the_original_firmware_does_not_approve_a_tinysa(tmp_path):
    path = tmp_path / "settings.json"
    Api(connect=None, ports=lambda: [ORIGINAL_FW], settings_path=path).use_port("/dev/cu.usbmodem1")
    later = Api(connect=None, ports=lambda: [TINYSA], settings_path=path)
    assert later.nanovna()["connected"] is False
    assert [p["device"] for p in later.serial_ports()["ports"]] == ["/dev/cu.usbmodem9"]  # still offered, not taken


def test_a_sweep_never_opens_a_tinysa_after_approving_the_original_firmware(monkeypatch, tmp_path):
    tried = []

    def no_real_port(cls, port, read_timeout_s=0.25):
        tried.append(port)
        raise DeviceError(f"Can't open {port}: not in tests")
    monkeypatch.setattr(NanoVNA, "open", classmethod(no_real_port))
    path = tmp_path / "settings.json"
    Api(connect=None, ports=lambda: [ORIGINAL_FW], settings_path=path).use_port("/dev/cu.usbmodem1")
    api = Api(connect=connect_nanovna, ports=lambda: [TINYSA], settings_path=path)
    assert "No NanoVNA found" in api.sweep("40m", "", 101)["error"]
    assert tried == []


def test_the_generic_st_id_with_no_usable_name_is_refused(tmp_path):
    for name in (None, "n/a", "caf\u00e9 VNA", "x" * 65):
        port = Port("/dev/cu.usbmodem7", 0x0483, 0x5740, name, name or "n/a")
        api = Api(connect=None, ports=lambda: [port], settings_path=tmp_path / "s.json")
        answer = api.use_port("/dev/cu.usbmodem7")
        assert answer["ok"] is False and "name" in answer["error"], name
        assert api.serial_ports()["remembered"] == []


def test_on_windows_a_port_whose_name_cant_be_read_is_not_remembered(monkeypatch, tmp_path):
    # No serial number, so Windows can't give the device's own name; its port label must not stand in.
    monkeypatch.setattr("dipstick.device.sys.platform", "win32")
    port = Port("COM5", 0x0483, 0x5740, None, "USB Serial Device (COM5)")
    api = Api(connect=None, ports=lambda: [port], settings_path=tmp_path / "s.json")
    answer = api.use_port("COM5")
    assert answer["ok"] is False and "name" in answer["error"]
    assert api.serial_ports()["remembered"] == []
