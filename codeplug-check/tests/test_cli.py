"""The codeplug-check command (README acceptance criteria: output, exit codes, T2)."""

import subprocess
import sys
from pathlib import Path

import pytest

from codeplug_check.cli import main

HEADER = ("Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,"
          "CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE")


def row(loc, name, freq, duplex="", offset="0.000000", tone=""):
    return f"{loc},{name},{freq},{duplex},{offset},{tone},100.0,100.0,023,NN,023,Tone->Tone,FM,5.00,,5W,,,,,"


@pytest.fixture
def csv_file(tmp_path):
    def write(*lines):
        path = tmp_path / "channels.csv"
        path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
        return path
    return write


def run(capsys, *args):
    code = main([str(a) for a in args])
    out, err = capsys.readouterr()
    return code, out, err


def test_a_clean_file(capsys, csv_file):
    code, out, err = run(capsys, csv_file(row(1, "CALL", "146.520000"), row(2, "RPT", "146.940000", "-", "0.600000", "Tone")))
    assert (code, out, err) == (0, "channels.csv: 2 channels checked, no problems found.\n", "")


def test_findings_are_grouped_by_severity_and_errors_exit_1(capsys, csv_file):
    code, out, _ = run(capsys, csv_file(
        row(1, "RPT", "146.940000", "+", "0.600000", "Tone"),  # wrong direction: warning
        row(2, "GMRS 1", "462.562500"),  # transmit on outside the bands: error
        row(3, "RPT", "146.940000", "+", "0.600000", "Tone"),  # duplicate of location 1: note (+ its warning)
    ))
    assert code == 1
    assert out == (
        "channels.csv: 3 channels checked\n"
        "\n"
        "Errors (1)\n"
        '  line 3, location 2 "GMRS 1": This channel transmits on 462.562 MHz, outside the amateur bands '
        "(47 CFR 97.301); set Duplex to off for receive-only\n"
        "\n"
        "Warnings (2)\n"
        '  line 2, location 1 "RPT": Offset +0.600 MHz; the band plan has -0.600 MHz for outputs 146.610-146.970\n'
        '  line 4, location 3 "RPT": Offset +0.600 MHz; the band plan has -0.600 MHz for outputs 146.610-146.970\n'
        "\n"
        "Notes (1)\n"
        '  line 4, location 3 "RPT": Same frequencies, tones and mode as location 1 (line 2)\n'
    )


def test_warnings_and_notes_alone_exit_0(capsys, csv_file):
    code, out, _ = run(capsys, csv_file(row(1, "RPT", "146.940000", "-", "0.600000")))  # no tone
    assert code == 0 and "Warnings (1)" in out and "Errors" not in out


def test_an_unreadable_row_is_an_error_and_the_rest_is_still_checked(capsys, csv_file):
    code, out, _ = run(capsys, csv_file(row(1, "BAD", "146.940000", "minus"), row(2, "GMRS", "462.562500")))
    assert code == 1
    assert "channels.csv: 1 channel checked, 1 row couldn't be read\n" in out
    assert "Errors (2)\n  line 2: Duplex 'minus' isn't one of: blank, +, -, split, off\n  line 3, location 2" in out


@pytest.mark.parametrize("name", ["missing.csv", "notchirp.csv"])
def test_a_file_that_cant_be_checked_exits_2_with_one_line(capsys, tmp_path, name):
    if name == "notchirp.csv":
        (tmp_path / name).write_text("Channel,RX Freq\n1,146.52\n")
    code, out, err = run(capsys, tmp_path / name)
    assert code == 2 and out == ""
    assert err.startswith("codeplug-check: ") and err.count("\n") == 1


def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2


@pytest.mark.parametrize("name", ["\x1b[2J\x1b[HWIPED", "RPT\u202eTXET", "BELL\x07", "NUL\x00X", "FAKE\u2028line 9"])
def test_control_characters_in_names_never_reach_the_terminal(capsys, csv_file, name):
    # T2: a downloaded file could clear the screen (ANSI escapes) or reorder text (U+202E) when printed.
    code, out, _ = run(capsys, csv_file(row(1, name, "462.562500")))
    assert code == 1
    assert not any(ch in out for ch in "\x1b\u202e\x07\x00\u2028")
    assert "\ufffd" in out  # replaced, so you can see something was there


def test_the_installed_command_runs(csv_file):
    command = Path(sys.executable).parent / "codeplug-check"
    result = subprocess.run([command, csv_file(row(1, "CALL", "146.520000"))], capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, "channels.csv: 1 channel checked, no problems found.\n")
