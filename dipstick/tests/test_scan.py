"""Sweeping a range (README acceptance criteria: leaves the NanoVNA as it found it, failure;
threat model T4, T5).

Found on the NanoVNA-H, firmware 1.2.43 (2026-11-15): `scan` replaces the NanoVNA's own
frequency list and point count, while `sweep` keeps reporting the old start and stop. So the
settings are read before the scan and put back after it, whatever happens in between."""

import math

import pytest
from fakes import FakeLink, UnpluggedLink, recorded

from dipstick.device import DeviceError, NanoVNA
from dipstick.scan import scan

SETTINGS = b"sweep\r\n1500000 30000000 101\r\nch> "  # yours, as recorded
RESTORE = b"sweep 1500000 30000000 101"
RESTORED = RESTORE + b"\r\nch> "  # the real reply to a sweep with arguments: echo, no answer
SCAN_40M = b"scan 7000000 7300000 11 3"


def scan_reply(lines):
    return SCAN_40M + b"\r\n" + b"".join(line + b" \r\n" for line in lines) + b"ch> "


def nano_with(scan_bytes, **replies):
    return NanoVNA(FakeLink({b"sweep": SETTINGS, SCAN_40M: scan_bytes, RESTORE: RESTORED, **replies}))


def test_a_recorded_40m_scan():
    nano = nano_with(recorded("scan_40m_11_3"))
    readings = scan(nano, 7_000_000, 7_300_000, 11)
    assert [r.hz for r in readings] == list(range(7_000_000, 7_300_001, 30_000))
    first = readings[0]
    assert first.s11 == complex(0.999913408, -0.000303635)
    assert first.swr > 1000  # an open port: almost everything comes back


def test_settings_are_read_first_and_put_back_last():
    nano = nano_with(recorded("scan_40m_11_3"))
    scan(nano, 7_000_000, 7_300_000, 11)
    assert nano.link.written == [b"sweep\r", SCAN_40M + b"\r", RESTORE + b"\r"]


def test_settings_are_put_back_even_when_the_scan_reply_is_bad():
    nano = nano_with(scan_reply([b"7000000 nan 0"]))
    with pytest.raises(DeviceError):
        scan(nano, 7_000_000, 7_300_000, 11)
    assert nano.link.written[-1] == RESTORE + b"\r"


def test_a_failed_restore_says_what_to_set_by_hand():
    nano = NanoVNA(FakeLink({b"sweep": SETTINGS, SCAN_40M: recorded("scan_40m_11_3"), RESTORE: b""}),
                   timeout_s=0.5, read_timeout_s=0.25)
    with pytest.raises(DeviceError, match="1.5 to 30 MHz, 101 points"):
        scan(nano, 7_000_000, 7_300_000, 11)


def test_unplugged_mid_scan_says_what_to_set_by_hand():
    # The NanoVNA-H runs on its battery, so it stays on with the scan's settings.
    nano = NanoVNA(UnpluggedLink({b"sweep": SETTINGS}, unplug_on=b"scan"))
    with pytest.raises(DeviceError, match=r"(?s)disconnected.*set it by hand: 1.5 to 30 MHz, 101 points"):
        scan(nano, 7_000_000, 7_300_000, 11)


def test_a_failed_restore_doesnt_hide_the_scan_error():
    # Both went wrong: report the scan's problem, and still say what to set by hand.
    nano = NanoVNA(FakeLink({b"sweep": SETTINGS, SCAN_40M: scan_reply(with_line(0, b"junk")), RESTORE: b""}),
                   timeout_s=0.5, read_timeout_s=0.25)
    with pytest.raises(DeviceError, match=r"(?s)line 1 .*1.5 to 30 MHz, 101 points"):
        scan(nano, 7_000_000, 7_300_000, 11)


# --- what may be scanned (checked before anything is sent) ------------------------------------

@pytest.mark.parametrize("start, stop", [(6_999_999, 7_300_000), (7_000_000, 14_350_000), (5_000_000, 6_000_000)])
def test_antenna_scans_stay_inside_one_band(start, stop):
    nano = nano_with(b"")
    with pytest.raises(ValueError, match="amateur band"):
        scan(nano, start, stop, 11)
    assert nano.link.written == []  # refused before touching the NanoVNA (T5)


def test_a_wide_scan_needs_no_antenna_said_out_loud():
    wide = b"scan 50000 30000000 11 3"
    lines = [f"{f} 0.5 0".encode() for f in range(50_000, 30_000_001, 2_995_000)]
    nano = NanoVNA(FakeLink({b"sweep": SETTINGS, wide: wide + b"\r\n" + b"".join(l + b" \r\n" for l in lines) + b"ch> ",
                             RESTORE: RESTORED}))
    assert len(scan(nano, 50_000, 30_000_000, 11, no_antenna=True)) == 11


@pytest.mark.parametrize("points", [1, 0, 102, 1000])
def test_points_from_2_to_101(points):
    with pytest.raises(ValueError, match="2 to 101"):
        scan(nano_with(b""), 7_000_000, 7_300_000, points)


# --- the reply, line by line (T4) -------------------------------------------------------------

GOOD = [f"{7_000_000 + 30_000 * i} 0.5 0.1".encode() for i in range(11)]


def with_line(index, line):
    lines = list(GOOD)
    lines[index] = line
    return lines


@pytest.mark.parametrize("lines, words", [
    (GOOD[:10], "10 lines"),                                 # one missing
    (GOOD + [GOOD[-1]], "12 lines"),                         # one extra
    (with_line(3, b"7090000 0.5"), "line 4"),                # a number missing
    (with_line(3, b"7090000 0.5 0.1 0.2"), "line 4"),        # one too many
    (with_line(3, b"7090000 0.5 abc"), "line 4"),            # not a number
    (with_line(3, b"7090000 inf 0"), "line 4"),              # not finite
    (with_line(3, b"7090000 1e999 0"), "line 4"),            # overflows to infinity
    (with_line(3, b"7090000 0x1p-1 0"), "line 4"),           # Python would read hex floats; the NanoVNA never sends them
    (with_line(3, b"7090000.5 0.5 0.1"), "line 4"),          # frequency not whole
    (with_line(3, b"7000000 0.5 0.1"), "line 4"),            # frequencies out of order
    (with_line(10, b"7300001 0.5 0.1"), "line 11"),          # outside the range asked for
    (with_line(0, b"6999999 0.5 0.1"), "line 1"),
    (with_line(5, b"7150000 3.0 0"), "line 6"),              # |S11| 3: can't be real
])
def test_bad_lines_are_refused_with_their_line_number(lines, words):
    with pytest.raises(DeviceError, match=words):
        scan(nano_with(scan_reply(lines)), 7_000_000, 7_300_000, 11)


def test_good_lines_give_readings():
    readings = scan(nano_with(scan_reply(GOOD)), 7_000_000, 7_300_000, 11)
    assert readings[0].impedance == pytest.approx(50 * (1.5 + 0.1j) / (0.5 - 0.1j))
    assert all(not math.isnan(r.swr) for r in readings)


def test_bad_settings_reply_stops_before_scanning():
    # Without the old settings there's nothing to put back, so don't change them at all.
    nano = NanoVNA(FakeLink({b"sweep": b"sweep\r\nwhat\r\nch> "}))
    with pytest.raises(DeviceError, match="sweep settings"):
        scan(nano, 7_000_000, 7_300_000, 11)
    assert nano.link.written == [b"sweep\r"]
