"""The band report's wording and advice: every number comes with what it means."""

from test_analysis import antenna

from dipstick.analysis import summarize
from dipstick.report import report
from dipstick.s11 import reading


def text(f0, half_width=60_000, target=7_150_000, **kwargs):
    return report(summarize(antenna(f0, half_width, **kwargs), target_hz=target), "40m")


# UI review 2026-11-16: the answer first (the best match, then what to do), then what the NanoVNA
# measured, then the rest. Lines that explain start with two spaces; the app shows them dimmer.

def test_the_first_two_lines_are_the_answer():
    first, second = text(7_051_000).splitlines()[:2]
    assert first == "40m: best match SWR 1.00 at 7.051 MHz (excellent)"
    assert second == "Shorten the antenna about 1.4% to move the best match to 7.150 MHz."


def test_says_what_the_nanovna_measured_and_from_where():
    out = text(7_150_000)
    assert "What the NanoVNA measured: 101 frequencies from 7.000 to 7.300 MHz" in out
    assert "tiny test signal" in out and "through this coax" in out


def test_no_trim_needed_skips_the_how_to_trim_explanation():
    out = text(7_150_000)
    assert "No trim needed" in out
    assert "an antenna you can trim" not in out


def test_impedance_comes_last_as_extra_reading():
    out = text(7_150_000)
    assert out.index("For the curious") > out.index("2:1 bandwidth")
    assert out.index("For the curious") < out.index("X = 0 at")


def test_a_well_matched_antenna():
    out = text(7_150_000)
    assert "best match SWR 1.00 at 7.150 MHz (excellent)" in out
    assert "1.0 is a perfect match" in out  # the explanation of SWR
    assert "2:1 bandwidth: 7.090-7.210 MHz (120 kHz)" in out
    assert "No trim needed" in out


def test_the_band_at_a_glance():
    assert "Across the band: 7.000 MHz SWR 4.92 | 7.150 MHz SWR 1.00 | 7.300 MHz SWR 4.92" in text(7_150_000)


def test_reactance_crossing_is_explained_as_the_radio_end():
    out = text(7_150_000)
    assert "X = 0 at 7.150 MHz" in out
    assert "radio's end of the coax" in out


def test_too_long_says_shorten_with_the_percent():
    out = text(7_051_000)
    assert "Shorten the antenna about 1.4% to move the best match to 7.150 MHz" in out


def test_too_short_says_lengthen():
    assert "Lengthen the antenna about 2.5% to move the best match to 7.074 MHz" in text(7_249_000, target=7_074_000)


def test_best_match_below_the_band():
    out = text(6_900_000, half_width=200_000)
    assert "below the band" in out and "too long" in out
    assert "Shorten the antenna at least 2.1%" in out  # 7.000 / 7.150 = 0.979: the edge is a lower bound
    assert "doesn't sweep outside the band" in out
    assert "X = 0 at" not in out  # none in the band
    assert "No point in the band has X = 0" in out


def test_best_match_above_the_band():
    out = text(7_400_000, half_width=200_000)
    assert "above the band" in out and "too short" in out and "Lengthen the antenna at least" in out


def test_never_reaches_two_to_one():
    out = text(7_150_000, r=200)
    assert "(high: you'll need a tuner)" in out  # SWR 4.0
    assert "never gets down to 2:1" in out


def test_two_to_one_running_into_one_edge():
    assert "2:1 bandwidth: 7.000-7.111 MHz (111 kHz, and it may go lower)" in text(7_051_000)


def test_two_to_one_across_the_whole_band():
    assert "2:1 bandwidth: the whole band (7.000-7.300 MHz, and maybe beyond)" in text(7_150_000, half_width=1_000_000)


def test_ratings():
    assert "(good)" in text(7_150_000, r=90)   # SWR 1.8
    assert "(high: you'll need a tuner)" in text(7_150_000, r=125)  # SWR 2.5
    assert "(poor" in text(7_150_000, r=400)   # SWR 8


def test_nothing_connected_says_check_the_connection_and_gives_no_advice():
    readings = [reading(7_000_000 + i * 30_000, complex(0.9999, -0.0003)) for i in range(11)]
    out = report(summarize(readings, target_hz=7_150_000), "40m")
    assert "nothing connected" in out and "Check the connection" in out
    assert "Shorten" not in out and "Lengthen" not in out and "2:1 bandwidth" not in out


def test_an_open_port_says_all_of_the_signal_comes_back():
    readings = [reading(7_000_000 + i * 30_000, complex(1.0002, 0)) for i in range(11)]  # noise just over 1
    out = report(summarize(readings, target_hz=7_150_000), "40m")
    assert "SWR is infinite everywhere: all of the signal comes back." in out and "lowest" not in out


def test_calibration_reminder():
    assert "recalibrate" in text(7_150_000)


def test_no_calibration_reminder_just_after_calibrating():
    assert "recalibrate" not in report(summarize(antenna(7_150_000, 60_000), target_hz=7_150_000), "40m", calibrated=True)


def test_a_flat_curve_says_no_clear_dip_and_gives_no_trim_advice():
    # Like the 2m HT antenna (2026-11-15): SWR about 5 everywhere, no dip to move.
    out = text(7_150_000, half_width=5_000_000, r=250)
    assert "No clear dip: SWR stays between 5.00 and 5.0" in out
    assert "resonant well outside" in out and "counterpoise" in out
    assert "Shorten" not in out and "Lengthen" not in out and "No trim needed" not in out


def test_a_flat_curve_beats_the_best_at_an_edge_advice():
    out = text(6_000_000, half_width=5_000_000, r=250)  # lowest SWR at the low edge, but barely
    assert "No clear dip" in out and "below the band" not in out


def test_a_real_dip_with_high_swr_still_gets_trim_advice():
    out = text(7_051_000, half_width=20_000, r=130)  # best SWR 2.6, climbing far higher at the edges
    assert "No clear dip" not in out and "Shorten the antenna about 1.4%" in out


def test_a_low_flat_curve_is_not_called_a_problem():
    assert "No clear dip" not in text(7_150_000, half_width=5_000_000)  # SWR about 1.0 everywhere


def test_trim_advice_says_it_is_for_antennas_you_can_trim():
    out = text(7_051_000)
    assert "an antenna you can trim (a wire dipole or end-fed, or an adjustable whip)" in out
    assert "A fixed antenna (a rubber duck or a bought whip) can't be trimmed" in out


def test_flat_means_the_highest_swr_is_under_a_quarter_above_the_lowest():
    assert "No clear dip: SWR stays between 3.00 and 3.64" in text(7_150_000, half_width=80_000, r=150)  # 1.22x
    assert "No clear dip" not in text(7_150_000, half_width=70_000, r=150)  # 3.00 to 3.84: 1.28x, a dip
