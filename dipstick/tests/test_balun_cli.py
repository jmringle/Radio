"""`dipstick balun`: the safety gate, the checks made before connecting, the report and the plot,
end to end with a fake NanoVNA."""

import pytest
from fakes import FakeLink
from test_balun import Z0, rising, sweep

from dipstick.cli import main
from dipstick.device import NanoVNA

SETTINGS = b"sweep\r\n7000000 7300000 101\r\nch> "
RESTORE = b"sweep 7000000 7300000 101"
SCAN = b"scan 1800000 54000000 101 3"


@pytest.fixture(autouse=True)
def in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def fake_nano(readings):
    body = b"".join(f"{r.hz} {r.s11.real:.9f} {r.s11.imag:.9f} \r\n".encode() for r in readings)
    link = FakeLink({b"sweep": SETTINGS, SCAN: SCAN + b"\r\n" + body + b"ch> ", RESTORE: RESTORE + b"\r\nch> "})
    return NanoVNA(link)


def run(capsys, argv, nano=None):
    opened = []

    def connect(port):
        opened.append(port)
        return nano

    code = main(["balun", *argv], connect=connect)
    out, err = capsys.readouterr()
    return code, out, err, opened


# --- checked before connecting ----------------------------------------------------------------

def test_refused_without_no_antenna_and_nothing_is_sent(capsys):
    code, out, err, opened = run(capsys, ["--ratio", "49:1"])
    assert code == 2 and out == "" and opened == []
    assert "--no-antenna" in err and "1.8 to 54 MHz" in err and "antenna wire off" in err


@pytest.mark.parametrize("ratio", ["2:1", "49", "49:1 ", "", "1:49"])
def test_unknown_ratios_are_refused_before_connecting(capsys, ratio):
    code, _, err, opened = run(capsys, ["--no-antenna", "--ratio", ratio])
    assert code == 2 and opened == []
    assert "--ratio must be one of 1:1, 4:1, 9:1, 49:1" in err


def test_a_ratio_is_required(capsys):
    with pytest.raises(SystemExit):
        run(capsys, ["--no-antenna"])


@pytest.mark.parametrize("resistor, ohms", [("2450", 2450), ("2.45k", 2450), ("2.7K", 2700), ("2450 ohms", 2450),
                                            ("1634", 1634), ("3675", 3675)])
def test_resistor_values_that_are_close_enough(capsys, resistor, ohms):
    code, out, err, _ = run(capsys, ["--no-antenna", "--ratio", "49:1", "--resistor", resistor], fake_nano(sweep(lambda hz: Z0)))
    assert code == 0, err
    assert f"{ohms}-ohm resistor" in out


@pytest.mark.parametrize("resistor", ["1600", "3700", "50", "abc", "-2450", "2450x", "0", "1e4"])
def test_resistors_too_far_off_or_not_numbers_are_refused_before_connecting(capsys, resistor):
    code, _, err, opened = run(capsys, ["--no-antenna", "--ratio", "49:1", "--resistor", resistor])
    assert code == 2 and opened == []
    assert "--resistor" in err and "2450" in err


def test_a_long_pasted_resistor_is_cut_short_in_the_error(capsys):
    _, _, err, _ = run(capsys, ["--no-antenna", "--ratio", "49:1", "--resistor", "9" * 500])
    assert "…" in err and len(err) < 300


def test_the_resistor_defaults_to_50_times_the_ratio(capsys):
    code, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "4:1"], fake_nano(sweep(lambda hz: Z0)))
    assert code == 0 and "4:1 transformer, 200-ohm resistor" in out


# --- the report -------------------------------------------------------------------------------

def test_the_answer_comes_first(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(rising)))
    assert out.splitlines()[0] == ("49:1 transformer, 2450-ohm resistor: SWR 2 or under on 160m, 80m, 40m, 30m, "
                                   "20m, 17m; above 2 on 15m, 12m, 10m, 6m.")


def test_every_band_gets_a_line(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(rising)))
    assert "  40m     7.020 MHz  SWR 1.00  excellent" in out
    assert "  17m    17.982 MHz  SWR 1.60  good" in out
    assert "  15m    21.114 MHz  SWR 2.22  high" in out


def test_matched_everywhere(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "1:1"], fake_nano(sweep(lambda hz: Z0)))
    assert out.splitlines()[0] == "1:1 transformer, 50-ohm resistor: SWR 2 or under on every band from 160m to 6m."


def test_matched_nowhere(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "1:1"], fake_nano(sweep(lambda hz: 3 * Z0)))
    assert out.splitlines()[0] == "1:1 transformer, 50-ohm resistor: SWR above 2 on every band from 160m to 6m."


def test_an_off_value_resistor_says_what_perfect_would_read(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1", "--resistor", "2.7k"], fake_nano(sweep(lambda hz: Z0)))
    assert "even a perfect 49:1 reads SWR 1.10" in out


def test_the_exact_resistor_says_nothing_about_perfect(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(lambda hz: Z0)))
    assert "even a perfect" not in out


def test_a_49_to_1_warns_about_stray_capacitance_on_the_high_bands(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(lambda hz: Z0)))
    assert "stray capacitance" in out


def test_a_1_to_1_has_no_stray_capacitance_warning(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "1:1"], fake_nano(sweep(lambda hz: Z0)))
    assert "stray capacitance" not in out


def test_the_report_reminds_to_calibrate_over_the_whole_range(capsys):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(lambda hz: Z0)))
    assert "1.8 to 54 MHz" in out and "Calibrate" in out


def test_nothing_on_the_output_is_an_error_not_a_report(capsys):
    code, out, err, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(lambda hz: float("inf"))))
    assert code == 2 and out == "" and "resistor connected" in err


# --- the sweep and the plot -------------------------------------------------------------------

def test_sweeps_once_and_puts_the_nanovnas_sweep_back(capsys):
    nano = fake_nano(sweep(lambda hz: Z0))
    run(capsys, ["--no-antenna", "--ratio", "49:1"], nano)
    assert nano.link.written == [b"sweep\r", SCAN + b"\r", RESTORE + b"\r"]
    assert nano.link.closed


def test_saves_the_swr_plot_with_the_ham_bands_shaded(capsys, tmp_path):
    _, out, _, _ = run(capsys, ["--no-antenna", "--ratio", "49:1"], fake_nano(sweep(lambda hz: Z0)))
    saved = list((tmp_path / "output").glob("balun-49to1-*-swr.svg"))
    assert len(saved) == 1 and str(saved[0].name) in out
    svg = saved[0].read_text()
    assert svg.count('class="ham-band"') == 10
    assert "49:1 transformer" in svg
