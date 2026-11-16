"""`dipstick cable`: the safety gate, the wording, and the command end to end with a fake NanoVNA."""

import pytest
from fakes import FakeLink
from test_cable import cable, loss_db

from dipstick.cable import sweep_for
from dipstick.cli import main
from dipstick.device import NanoVNA

SETTINGS = b"sweep\r\n140000000 150000000 101\r\nch> "
RESTORE = b"sweep 140000000 150000000 101"


@pytest.fixture(autouse=True)
def in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def fake_nano(readings):
    start, stop, points = readings[0].hz, readings[-1].hz, len(readings)
    command = f"scan {start} {stop} {points} 3".encode()
    body = b"".join(f"{r.hz} {r.s11.real:.9f} {r.s11.imag:.9f} \r\n".encode() for r in readings)
    return NanoVNA(FakeLink({b"sweep": SETTINGS, command: command + b"\r\n" + body + b"ch> ",
                             RESTORE: RESTORE + b"\r\nch> "}))


def run(capsys, argv, nano=None):
    opened = []

    def connect(port):
        opened.append(port)
        return nano

    code = main(argv, connect=connect)
    out, err = capsys.readouterr()
    return code, out, err, opened


def planned(length, vf, end="open", max_length=50, plan_vf=0.66):
    start, stop, _ = sweep_for(max_length_m=max_length, vf=plan_vf)
    return cable(length, vf, end=end, start=start, stop=stop)


# --- the safety gate (T5) --------------------------------------------------------------------

def test_refused_without_no_antenna_and_nothing_is_sent(capsys):
    code, out, err, opened = run(capsys, ["cable", "--vf", "0.66"])
    assert code == 2 and out == "" and opened == []
    assert "--no-antenna" in err and "outside the ham bands" in err


# --- end to end ------------------------------------------------------------------------------

def test_length_of_an_open_cable(capsys):
    nano = fake_nano(planned(12.0, 0.66))
    code, out, err, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], nano)
    assert code == 0 and err == ""
    assert "Far end: open" in out
    assert "Length: 12.00 m (39.4 ft) at velocity factor 0.66" in out
    assert nano.link.written[-1] == RESTORE + b"\r" and nano.link.closed


def test_velocity_factor_from_a_known_length_in_feet(capsys):
    # 50 ft = 15.24 m; the sweep is planned for VF 0.5 because the VF is what's unknown.
    nano = fake_nano(planned(15.24, 0.78, plan_vf=None))
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--length", "50ft"], nano)
    assert "Velocity factor: 0.78 (for a 15.24 m / 50.0 ft cable)" in out


def test_a_short_at_the_end_is_named(capsys):
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(planned(8.0, 0.66, end="short")))
    assert "Far end: short" in out


def test_loss_line(capsys):
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(planned(20.0, 0.66)))
    assert "Loss, one way: 7 MHz 0.4" in out and "| 50 MHz 1.1" in out  # 0.5 dB at 10 MHz, rising with sqrt(f)
    assert "return loss" in out  # the explanation


def test_the_sweep_and_its_limit_are_shown(capsys):
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(planned(20.0, 0.66)))
    assert "Measurable up to 50 m" in out and "--max-length" in out


def test_max_length_changes_the_sweep(capsys):
    nano = fake_nano(planned(90.0, 0.66, max_length=100))
    code, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66", "--max-length", "100"], nano)
    assert code == 0 and "Length: 90.00 m" in out and "Measurable up to 100 m" in out


def test_a_matched_end_says_it_cant_measure(capsys):
    readings = [type(r)(r.hz, r.s11 * 0.05, r.impedance, r.swr, r.return_loss_db) for r in planned(10.0, 0.66)]
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(readings))
    assert "Nothing comes back from the far end" in out and "Length:" not in out


def test_a_messy_phase_is_warned_about(capsys):
    import cmath
    import math
    from dipstick.s11 import reading
    readings = [reading(r.hz, r.s11 * cmath.exp(1j * 1.5 * math.sin(r.hz / 4e6))) for r in planned(20.0, 0.66)]
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(readings))
    assert "doesn't look like a plain cable" in out


@pytest.mark.parametrize("argv, words", [
    (["cable", "--no-antenna"], "--vf or --length"),
    (["cable", "--no-antenna", "--vf", "0.66", "--length", "10"], "--vf or --length"),
    (["cable", "--no-antenna", "--vf", "1.5"], "velocity factor"),
    (["cable", "--no-antenna", "--vf", "abc"], "velocity factor"),
    (["cable", "--no-antenna", "--length", "ten"], "--length"),
    (["cable", "--no-antenna", "--length", "-5"], "--length"),
    (["cable", "--no-antenna", "--length", "10yd"], "--length"),
    (["cable", "--no-antenna", "--length", "2001"], "--length"),
    (["cable", "--no-antenna", "--vf", "0.66", "--max-length", "0"], "max"),
    (["cable", "--no-antenna", "--vf", "0.66", "--max-length", "7000ft"], "max"),
])
def test_bad_arguments_never_connect(capsys, argv, words):
    code, out, err, opened = run(capsys, argv)
    assert code == 2 and out == "" and words in err and opened == []


def test_band_command_still_works(capsys):
    code, _, err, opened = run(capsys, ["41m"])
    assert code == 2 and "41m" in err and opened == []


def test_help_mentions_cable(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "dipstick cable --help" in capsys.readouterr().out


def test_loss_helper_matches_the_model():
    assert loss_db(10e6, 0.5) == 0.5


# --- UI review 2026-11-16: the answer first, then what the NanoVNA measured -----------------------

def test_the_first_line_is_the_answer_for_a_length(capsys):
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(planned(12.0, 0.66)))
    assert out.splitlines()[0] == "Cable: 12.00 m (39.4 ft) long, far end open"


def test_the_first_line_is_the_answer_for_a_velocity_factor(capsys):
    nano = fake_nano(planned(15.24, 0.78, plan_vf=None))  # planned for an unknown VF, as above
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--length", "50ft"], nano)
    assert out.splitlines()[0] == "Cable: velocity factor 0.78, far end open"


def test_the_first_line_says_when_nothing_echoes(capsys):
    readings = [type(r)(r.hz, r.s11 * 0.05, r.impedance, r.swr, r.return_loss_db) for r in planned(10.0, 0.66)]
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(readings))
    assert out.splitlines()[0] == "Cable: no echo from the far end"


def test_says_what_the_nanovna_measured_and_why_the_antenna_is_off(capsys):
    _, out, _, _ = run(capsys, ["cable", "--no-antenna", "--vf", "0.66"], fake_nano(planned(12.0, 0.66)))
    assert "What the NanoVNA measured: 101 frequencies from 1.000 to " in out
    assert "echo" in out and "outside the ham bands" in out
