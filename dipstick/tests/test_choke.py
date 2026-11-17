"""The choke test (a current balun's choking): the choke in series between CH0 and CH1.

A series impedance Z between two 50-ohm ports lets S21 = 2 x 50 / (2 x 50 + Z) through (the
circuit itself; K6JCA's series-through method). Readings here are made up from Zs that way, and
the code works the other way back, so each expected Z below is the one the reading was made from."""

import math

import pytest

from dipstick.balun import POINTS, START_HZ, STOP_HZ, analyze_choke, choke_impedance, choke_rating
from dipstick.report import choke_report
from dipstick.s21 import through


def s21_for(z):
    return 100 / (100 + z)


def sweep(z_at):
    """S21 over the 1.8-54 MHz sweep, with the choke impedance `z_at(hz)` gives (inf: nothing through)."""
    out = []
    for i in range(POINTS):
        hz = round(START_HZ + i * (STOP_HZ - START_HZ) / (POINTS - 1))
        z = z_at(hz)
        out.append(through(hz, 0j if z == math.inf else complex(s21_for(z))))
    return out


@pytest.mark.parametrize("z", [100, 1000, 1000 + 1000j, 250 - 4000j])
def test_choke_impedance_comes_back_from_s21(z):
    assert choke_impedance(complex(s21_for(z))) == pytest.approx(complex(z))


@pytest.mark.parametrize("z, rating", [
    (5, "beneath"),           # 0.4 dB: too little to measure precisely (under about 12 ohms)
    (400, "weak"),            # under Palomar's 500-ohm minimum
    (499, "weak"),
    (500, "fair"),            # |Z| at Palomar's minimum, R under G3TXQ's 1000
    (300 + 600j, "fair"),     # |Z| 671: still fair, R is only 300
    (200 + 5000j, "fair"),    # mostly reactance: big |Z|, little R, which is what chokes
    (999, "fair"),
    (1000, "good"),           # R at G3TXQ's 1000 ohms
    (1000 + 3000j, "good"),
    (4999, "good"),
    (5000, "plenty"),         # K9YC: 5K is plenty for a matched, balanced antenna
    (9000, "plenty"),         # 39.1 dB: still inside what the setup measures
    (20000, "beyond"),        # 46 dB: deeper than this setup measures reliably
])
def test_choke_rating(z, rating):
    s21 = complex(s21_for(z))
    assert choke_rating(choke_impedance(s21), through(7_000_000, s21).loss_db) == rating


def test_analyze_choke_takes_each_band_middle():
    result = analyze_choke(sweep(lambda hz: 2000 if hz < 20e6 else 300))
    assert [b.band for b in result.bands] == ["160m", "80m", "40m", "30m", "20m", "17m", "15m",
                                              "12m", "10m", "6m"]
    forty = result.bands[2]
    assert forty.hz == 7_020_000 and forty.z == pytest.approx(2000) and forty.rating == "good"
    assert result.bands[-1].rating == "weak"


def test_nothing_arriving_anywhere_is_an_error_not_plenty():
    # An unconnected CH1 reads like a perfect choke: say so instead.
    with pytest.raises(ValueError, match="between CH0 and CH1"):
        analyze_choke(sweep(lambda hz: math.inf))


def test_one_deep_band_is_fine():
    result = analyze_choke(sweep(lambda hz: math.inf if hz < 3e6 else 2000))
    assert result.bands[0].rating == "beyond" and result.bands[1].rating == "good"


# --- the report in plain words ------------------------------------------------------------------


def mixed():
    """Plenty low down, good in the middle, weak on 6 m: a typical ferrite choke's shape."""
    return analyze_choke(sweep(lambda hz: 6000 if hz < 8e6 else 1500 if hz < 40e6 else 300 + 200j))


def test_report_answer_first_grouped_by_rating():
    first = choke_report(mixed(), calibrated=True, thru=True).splitlines()[0]
    assert first == "Choke: plenty on 160m, 80m, 40m; good on 30m, 20m, 17m, 15m, 12m, 10m; weak on 6m."


def test_report_band_lines_show_r_and_z():
    text = choke_report(mixed(), calibrated=True, thru=True)
    assert "  40m     7.020 MHz  R 6,000 ohms  |Z| 6,000 ohms  plenty" in text
    assert "  6m     51.912 MHz  R 300 ohms  |Z| 361 ohms  weak" in text


def test_report_names_each_guideline_and_that_r_does_the_choking():
    text = choke_report(mixed(), calibrated=True, thru=True)
    for words in ("Palomar", "500 ohms", "G3TXQ", "1,000 ohms", "K9YC", "5,000 ohms", "rules of thumb",
                  "R, the resistive part", "stray capacitance"):
        assert words in text


def test_unresolvable_readings_say_so_instead_of_a_number():
    text = choke_report(analyze_choke(sweep(lambda hz: math.inf if hz < 3e6 else 5)), calibrated=True, thru=True)
    assert "  160m    1.800 MHz  over about 10,000 ohms: more than this setup measures" in text
    assert "  80m     3.888 MHz  under about 12 ohms: too little to measure precisely" in text


def test_report_reminds_to_calibrate_both_ports_unless_done_here():
    assert "Both ports" not in choke_report(mixed(), calibrated=True, thru=True)
    reminder = choke_report(mixed(), calibrated=False, thru=True)
    assert "HF wide" in reminder and "Both ports" in reminder and "aren't corrected" not in reminder


def test_report_warns_loudly_when_the_nanovna_has_no_thru_calibration():
    text = choke_report(mixed(), calibrated=True, thru=False)
    assert "aren't corrected" in text and "Both ports" in text
