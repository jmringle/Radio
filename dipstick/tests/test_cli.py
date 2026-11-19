"""The dipstick command end to end, with a fake NanoVNA (README acceptance criteria: output,
exit codes, failure)."""

import subprocess
import sys
from pathlib import Path

import pytest
from fakes import FakeLink, recorded
from test_analysis import antenna

from dipstick.cli import main
from dipstick.device import DeviceError, NanoVNA

SETTINGS = b"sweep\r\n1500000 30000000 101\r\nch> "
RESTORE = b"sweep 1500000 30000000 101"


@pytest.fixture(autouse=True)
def in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # plots go to ./output: keep them out of the repo


def fake_nano(scan_command, scan_reply):
    return NanoVNA(FakeLink({b"sweep": SETTINGS, scan_command: scan_reply, RESTORE: RESTORE + b"\r\nch> "}))


def reply_for(command, readings):
    body = b"".join(f"{r.hz} {r.s11.real:.9f} {r.s11.imag:.9f} \r\n".encode() for r in readings)
    return command + b"\r\n" + body + b"ch> "


def run(capsys, argv, nano=None, error=None):
    opened = []

    def connect(port):
        opened.append(port)
        if error:
            raise error
        return nano

    code = main(argv, connect=connect)
    out, err = capsys.readouterr()
    return code, out, err, opened


def test_your_recorded_open_port_says_nothing_is_connected(capsys):
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    code, out, err, _ = run(capsys, ["40m", "--points", "11"], nano)
    assert code == 0 and err == ""
    assert out.startswith("40m: SWR")
    assert "nothing connected" in out


def test_a_good_antenna_end_to_end(capsys):
    command = b"scan 7000000 7300000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(7_153_000, 60_000)))
    code, out, _, _ = run(capsys, ["40m"], nano)
    assert code == 0
    assert "40m: best match SWR 1.00 at 7.153 MHz (excellent)" in out
    assert "No trim needed" in out
    assert nano.link.written[-1] == RESTORE + b"\r"  # the NanoVNA's settings went back
    assert nano.link.closed


def test_target_frequency(capsys):
    command = b"scan 7000000 7300000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(7_153_000, 60_000)))
    _, out, _, _ = run(capsys, ["40m", "--target", "7.074"], nano)
    assert "Lengthen the antenna about 1.1% (about 8.8 in / 22 cm; on a dipole, 4.4 in / 11 cm on each end) " \
           "to move the best match to 7.074 MHz" in out


def test_a_frequency_instead_of_a_band_sweeps_its_band_and_trims_for_it(capsys):
    # dipstick 915: a 915 MHz LoRa antenna (MeshCore, Meshtastic), swept across 33 cm (902-928).
    command = b"scan 902000000 928000000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(910_420_000, 3_000_000, start=902_000_000, stop=928_000_000)))
    code, out, _, _ = run(capsys, ["915"], nano)
    assert code == 0 and out.startswith("33cm: best match")
    assert "to move the best match to 915.000 MHz" in out


def test_any_frequency_in_a_band_works(capsys):
    command = b"scan 144000000 148000000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(146_520_000, 500_000, start=144_000_000, stop=148_000_000)))
    _, out, _, _ = run(capsys, ["146.52"], nano)
    assert out.startswith("2m:") and "No trim needed: the best match is within 0.5% of 146.520 MHz" in out


def test_port_is_passed_through(capsys):
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    *_, opened = run(capsys, ["40m", "--points", "11", "--port", "/dev/cu.usbmodem9"], nano)
    assert opened == ["/dev/cu.usbmodem9"]


def test_no_port_means_find_it(capsys):
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    *_, opened = run(capsys, ["40m", "--points", "11"], nano)
    assert opened == [None]


def test_a_device_problem_is_one_line_and_exit_2(capsys):
    code, out, err, _ = run(capsys, ["40m"], error=DeviceError("No NanoVNA found. Is it plugged in?"))
    assert (code, out) == (2, "")
    assert err == "dipstick: No NanoVNA found. Is it plugged in?\n"


@pytest.mark.parametrize("argv, words", [
    (["41m"], "41m"),                              # not a band
    (["60m"], "60m"),                              # channels, not a band
    (["40m", "--target", "14.074"], "target"),     # outside the band
    (["40m", "--target", "7.0.74"], "target"),     # not a number
    (["40m", "--target", "nan"], "target"),
    (["40m", "--points", "1"], "2 to 101"),
    (["40m", "--points", "500"], "2 to 101"),
    (["100"], "100 MHz isn't in an amateur band"),  # FM broadcast
    (["5.3305"], "isn't in an amateur band"),        # a 60 m channel: dipstick doesn't sweep 60 m
    (["915", "--target", "920"], "915 is already the target"),
    (["915.1234567"], "915.1234567"),                 # finer than 1 Hz
])
def test_bad_arguments_are_refused_before_touching_the_nanovna(capsys, argv, words):
    code, out, err, opened = run(capsys, argv)
    assert code == 2 and out == "" and words in err
    assert opened == []  # never connected


def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2


def test_the_installed_command_runs():
    command = Path(sys.executable).parent / "dipstick"
    result = subprocess.run([command, "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "40m" in result.stdout


def test_plots_are_saved_and_listed(capsys, tmp_path):
    command = b"scan 7000000 7300000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(7_153_000, 60_000)))
    _, out, _, _ = run(capsys, ["40m", "--out", str(tmp_path / "plots")], nano)
    saved = sorted((tmp_path / "plots").glob("40m-*.svg"))
    assert [p.name.rsplit("-", 1)[1] for p in saved] == ["smith.svg", "swr.svg"]
    assert all(p.read_text().startswith("<svg") for p in saved)
    assert "Plots: " in out and str(saved[0].parent) in out


def test_plots_go_to_output_by_default(capsys, tmp_path):
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    run(capsys, ["40m", "--points", "11"], nano)
    assert len(list((tmp_path / "output").glob("40m-*.svg"))) == 2


def test_a_folder_that_cant_be_written_is_one_line_and_exit_2(capsys, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    nano = fake_nano(b"scan 7000000 7300000 11 3", recorded("scan_40m_11_3"))
    code, _, err, _ = run(capsys, ["40m", "--points", "11", "--out", str(blocker)], nano)
    assert code == 2 and err.startswith("dipstick: ") and err.count("\n") == 1


# --- the trim in inches from the antenna's real length (2026-11-19) ---------------------------------

def test_antenna_length_gives_the_trim_in_inches_from_it(capsys):
    command = b"scan 7000000 7300000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(7_051_000, 60_000)))
    code, out, _, _ = run(capsys, ["40m", "--target", "7.150", "--antenna-length", "66ft"], nano)
    assert code == 0
    assert "(about 11 in / 28 cm; on a dipole, 5.5 in / 14 cm off each end)" in out
    assert "From the antenna length you gave: 66.0 ft (20.12 m)." in out


def test_with_no_antenna_length_the_inches_are_an_estimate_naming_the_option(capsys):
    command = b"scan 7000000 7300000 101 3"
    nano = fake_nano(command, reply_for(command, antenna(7_051_000, 60_000)))
    _, out, _, _ = run(capsys, ["40m", "--target", "7.150"], nano)
    assert "468 / MHz rule of thumb" in out and "(--antenna-length)" in out


@pytest.mark.parametrize("length, words", [
    ("abc", "must be a length like"), ("0", "above 0"), ("-5", "must be a length like"),
    ("201m", "at most 200 m"), ("7000000\rclearconfig", "must be a length like"),
])
def test_a_bad_antenna_length_is_refused_before_connecting(capsys, length, words):
    code, _, err, opened = run(capsys, ["40m", "--antenna-length", length], nano=None)
    assert code == 2 and "--antenna-length" in err and words in err
    assert opened == []
