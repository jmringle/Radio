"""`dipstick balun --loss`: the safety gate, the connection choice and the report, end to end with a
fake NanoVNA."""

import math

import pytest
from test_balun_cli import run
from test_choke_cli import SCAN, fake_nano
from test_loss import sweep


@pytest.fixture(autouse=True)
def in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_refused_without_no_antenna_and_nothing_is_sent(capsys):
    code, out, err, opened = run(capsys, ["--loss", "direct"])
    assert code == 2 and out == "" and opened == []
    assert "--no-antenna" in err and "1.8 to 54 MHz" in err


@pytest.mark.parametrize("args", [["--loss"], ["--loss", "pair"], ["--loss", "direct", "--choke"],
                                  ["--loss", "direct", "--ratio", "1:1"]])
def test_a_bad_or_clashing_choice_is_refused(capsys, args):
    with pytest.raises(SystemExit):
        run(capsys, ["--no-antenna", *args])


def test_loss_with_a_resistor_is_refused_before_connecting(capsys):
    code, _, err, opened = run(capsys, ["--no-antenna", "--loss", "direct", "--resistor", "50"])
    assert code == 2 and opened == [] and "--resistor is for the transformer test" in err


def test_back_to_back_reads_the_calibration_sweeps_and_halves(capsys):
    nano, link = fake_nano(sweep(lambda hz: 0.6))
    code, out, err, _ = run(capsys, ["--no-antenna", "--loss", "back-to-back"], nano)
    assert code == 0 and err == "" and link.closed
    assert link.written[:3] == [b"cal\r", b"sweep\r", SCAN + b"\r"]
    assert out.startswith("Through loss, each of two transformers back to back: most 0.30 dB")


def test_nothing_arriving_is_an_error(capsys):
    nano, link = fake_nano(sweep(lambda hz: math.inf))
    code, out, err, _ = run(capsys, ["--no-antenna", "--loss", "direct"], nano)
    assert code == 2 and out == "" and "between CH0 and CH1" in err and link.closed
