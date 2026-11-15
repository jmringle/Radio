"""The Python side of the app: what the window's page may call (window.pywebview.api).

Tested directly with the fake NanoVNA: no window, no hardware. Every answer is a plain dict the
page can show; nothing is raised into the page."""

import threading

import pytest
from fakes import FakeLink, recorded
from test_analysis import antenna

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


def test_the_page_can_only_reach_public_methods():
    # pywebview exposes an object's public methods (and walks its public attributes): keep the
    # connection and lock private so the page can't reach them.
    public = {name for name in vars(Api(connect=None)) if not name.startswith("_")}
    assert public == set()
    assert {name for name in dir(Api) if not name.startswith("_")} == {"bands", "sweep"}
