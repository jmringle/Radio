"""`dipstick balun --choke`: the safety gate, the calibration check and the report, end to end with
a fake NanoVNA."""

import math

import pytest
from fakes import FakeLink
from test_balun_cli import RESTORE, SETTINGS, run
from test_choke import sweep

from dipstick.device import NanoVNA

SCAN = b"scan 1800000 54000000 101 5"
TWO_PORT = b"load isoln Es Er Et cal'ed "


@pytest.fixture(autouse=True)
def in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def fake_nano(throughs, status=TWO_PORT):
    body = b"".join(f"{t.hz} {t.s21.real:.9f} {t.s21.imag:.9f} \r\n".encode() for t in throughs)
    link = FakeLink({b"cal": b"cal\r\n" + status + b"\r\nch> ", b"sweep": SETTINGS,
                     SCAN: SCAN + b"\r\n" + body + b"ch> ", RESTORE: RESTORE + b"\r\nch> "})
    return NanoVNA(link), link


def test_refused_without_no_antenna_and_nothing_is_sent(capsys):
    code, out, err, opened = run(capsys, ["--choke"])
    assert code == 2 and out == "" and opened == []
    assert "--no-antenna" in err and "1.8 to 54 MHz" in err


def test_choke_and_ratio_together_are_refused(capsys):
    with pytest.raises(SystemExit):
        run(capsys, ["--no-antenna", "--choke", "--ratio", "1:1"])


def test_choke_with_a_resistor_is_refused_before_connecting(capsys):
    code, _, err, opened = run(capsys, ["--no-antenna", "--choke", "--resistor", "50"])
    assert code == 2 and opened == [] and "--resistor is for the transformer test" in err


def test_reads_the_calibration_then_sweeps_s21_and_puts_the_sweep_back(capsys):
    nano, link = fake_nano(sweep(lambda hz: 2000))
    code, out, err, _ = run(capsys, ["--no-antenna", "--choke"], nano)
    assert code == 0 and err == ""
    assert link.written == [b"cal\r", b"sweep\r", SCAN + b"\r", RESTORE + b"\r"]
    assert out.startswith("Choke: good on 160m, ")
    assert "aren't corrected" not in out and "Both ports" in out  # the command can't know the range
    assert link.closed


def test_no_thru_in_the_calibration_is_a_loud_warning(capsys):
    nano, _ = fake_nano(sweep(lambda hz: 2000), status=b"load open short Es Er cal'ed ")
    code, out, _, _ = run(capsys, ["--no-antenna", "--choke"], nano)
    assert code == 0 and "aren't corrected" in out


def test_nothing_arriving_is_an_error(capsys):
    nano, link = fake_nano(sweep(lambda hz: math.inf))
    code, out, err, _ = run(capsys, ["--no-antenna", "--choke"], nano)
    assert code == 2 and out == "" and "between CH0 and CH1" in err and link.closed


def test_a_garbled_calibration_status_is_an_error_before_sweeping(capsys):
    nano, link = fake_nano(sweep(lambda hz: 2000), status=b"usage: cal [load|open|short]")
    code, _, err, _ = run(capsys, ["--no-antenna", "--choke"], nano)
    assert code == 2 and "calibration status" in err and link.written == [b"cal\r"] and link.closed
