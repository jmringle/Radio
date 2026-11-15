"""The Python side of the app: what the window's page may call (window.pywebview.api).

Tested directly with the fake NanoVNA: no window, no hardware. Every answer is a plain dict the
page can show; nothing is raised into the page."""

import threading

import pytest
from fakes import FakeLink, UnpluggedLink, recorded
from test_analysis import antenna
from test_cable_cli import fake_nano as fake_cable_nano
from test_cable_cli import planned
from test_device import Port

from dipstick.app import Api
from dipstick.device import DeviceError, NanoVNA

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
    assert "Best match: SWR 1.00 at 7.153 MHz" in answer["report"]
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
    assert "Best match: SWR 1.00 at 146.520 MHz" in answer["report"]


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


def test_status_more_than_one():
    other = Port("/dev/cu.usbmodem402", 0x0483, 0x5740, "NanoVNA-H")
    answer = status([NANO, other])
    assert answer["connected"] is False
    assert answer["text"] == "More than one NanoVNA is plugged in (/dev/cu.usbmodem401, /dev/cu.usbmodem402); unplug one"


def test_status_never_connects():
    def connect(port):
        raise AssertionError("status must not open the port")
    Api(connect=connect, ports=lambda: [NANO]).nanovna()


def test_the_page_can_only_reach_public_methods():
    # pywebview exposes an object's public methods (and walks its public attributes): keep the
    # connection and lock private so the page can't reach them.
    public = {name for name in vars(Api(connect=None)) if not name.startswith("_")}
    assert public == set()
    assert {name for name in dir(Api) if not name.startswith("_")} == {"bands", "cable", "nanovna", "sweep"}


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
])
def test_cable_short_lengths_in_inches_or_with_a_leading_point(length, said):
    meters = {".6": 0.6, "18.5in": 0.4699}.get(length, 0.1524)
    answer = cable_api(fake_cable_nano(planned(meters, 0.78, plan_vf=None))).cable(True, "", length, "50")
    assert f"Velocity factor: 0.78 (for a {said} cable)" in answer["report"], answer


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
