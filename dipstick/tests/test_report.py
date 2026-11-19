"""The band report's wording and advice: every number comes with what it means."""

import math

import pytest

from test_analysis import antenna

from dipstick.analysis import summarize
from dipstick.report import report, report_parts, tuner_need
from dipstick.s11 import reading


def text(f0, half_width=60_000, target=7_150_000, **kwargs):
    return report(summarize(antenna(f0, half_width, **kwargs), target_hz=target), "40m")


# UI review 2026-11-16: the answer first (the best match, then what to do), then what the NanoVNA
# measured, then the rest. Lines that explain start with two spaces; the app shows them dimmer.

def test_the_first_two_lines_are_the_answer():
    first, second = text(7_051_000).splitlines()[:2]
    assert first == "40m: best match SWR 1.00 at 7.051 MHz (excellent)"
    assert second.startswith("Shorten the antenna about 1.4% (about 11 in")


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
    assert "2:1 bandwidth (no tuner needed): 7.090-7.210 MHz (120 kHz)" in out
    assert "No trim needed" in out


def test_the_band_at_a_glance():
    assert "Across the band: 7.000 MHz SWR 4.92 | 7.150 MHz SWR 1.00 | 7.300 MHz SWR 4.92" in text(7_150_000)


def test_reactance_crossing_is_explained_as_the_radio_end():
    out = text(7_150_000)
    assert "X = 0 at 7.150 MHz" in out
    assert "radio's end of the coax" in out


def test_too_long_says_shorten_with_the_percent():
    out = text(7_051_000)
    assert "Shorten the antenna about 1.4% (about 11 in" in out and "to move the best match to 7.150 MHz" in out


def test_too_short_says_lengthen():
    out = text(7_249_000, target=7_074_000)
    assert "Lengthen the antenna about 2.5% (about 19 in / 49 cm; on a dipole, 9.6 in / 24 cm on each end) " \
           "to move the best match to 7.074 MHz" in out


def test_best_match_below_the_band():
    out = text(6_900_000, half_width=200_000)
    assert "below the band" in out and "too long" in out
    assert "Shorten the antenna at least 2.1% (at least 17 in" in out  # 7.000 / 7.150 = 0.979: the edge is a lower bound
    assert "doesn't sweep outside the band" in out
    assert "X = 0 at" not in out  # none in the band
    assert "No point in the band has X = 0" in out


def test_best_match_above_the_band():
    out = text(7_400_000, half_width=200_000)
    assert "above the band" in out and "too short" in out and "Lengthen the antenna at least" in out


def test_never_reaches_two_to_one():
    out = text(7_150_000, r=200)
    assert "(high: needs a wide-range external tuner)" in out  # SWR 4.0
    assert "2:1 bandwidth (no tuner needed): none; SWR never gets down to 2:1 in this band (lowest 4.00)" in out
    assert "3:1 bandwidth (most built-in tuners): none" in out


def test_two_to_one_running_into_one_edge():
    assert "2:1 bandwidth (no tuner needed): 7.000-7.111 MHz (111 kHz, and it may go lower)" in text(7_051_000)


def test_two_to_one_across_the_whole_band():
    assert "2:1 bandwidth (no tuner needed): the whole band (7.000-7.300 MHz, and maybe beyond)" in text(7_150_000, half_width=1_000_000)


def test_ratings():
    assert "(good)" in text(7_150_000, r=90)   # SWR 1.8
    assert "(high: within most built-in tuners)" in text(7_150_000, r=125)  # SWR 2.5
    assert "(high: needs a wide-range external tuner)" in text(7_150_000, r=400)  # SWR 8
    assert "(poor: beyond most tuners: check the antenna, coax and connectors)" in text(7_150_000, r=450)  # SWR 9


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


# --- display review 2026-11-19: a short Tune section first, everything else in More detail -------
# The app shows the Tune section and folds More detail away; the command prints both (report()).

def parts(f0, half_width=60_000, target=7_150_000, band="40m", calibrated=False, **kwargs):
    return report_parts(summarize(antenna(f0, half_width, **kwargs), target_hz=target), band, calibrated=calibrated)


def test_the_tune_section_is_only_what_you_act_on():
    tune, _ = parts(7_051_000)
    assert tune.splitlines() == [
        "40m: best match SWR 1.00 at 7.051 MHz (excellent)",
        "Shorten the antenna about 1.4% (about 11 in / 28 cm; on a dipole, 5.5 in / 14 cm off each end) "
        "to move the best match to 7.150 MHz.",
        "  Inches assume a half-wave wire, a dipole or an end-fed on its main band (about 66.4 ft at 7.051 MHz, "
        "from the 468 / MHz rule of thumb); for any other antenna, give its length (--antenna-length).",
        "At 7.150 MHz now: SWR 3.03, needs a wide-range external tuner.",
        "2:1 bandwidth (no tuner needed): 7.000-7.111 MHz (111 kHz, and it may go lower)",
        "3:1 bandwidth (most built-in tuners): 7.000-7.149 MHz (149 kHz, and it may go lower)",
        "Calibration: the NanoVNA's current one. For the most accurate numbers, recalibrate for 40m (the app's Calibrate tab).",
    ]


def test_more_detail_keeps_every_explanation():
    _, detail = parts(7_051_000)
    for kept in ("What the NanoVNA measured: 101 frequencies", "tiny test signal", "Across the band:",
                 "1.0 is a perfect match", "start cutting power above about 2:1", "an antenna you can trim",
                 "A fixed antenna", "made over a different", "For the curious, impedance:", "X = 0 at"):
        assert kept in detail
    assert "Shorten the antenna" not in detail and "3:1 bandwidth (most" not in detail  # said once, in Tune


def test_more_detail_says_what_a_tuners_range_really_is():
    _, detail = parts(7_150_000)
    assert "impedance range" in detail and "doesn't fix the antenna" in detail and "your own tuner's manual" in detail


def test_the_command_prints_both_sections_tune_first():
    tune, detail = parts(7_051_000)
    assert text(7_051_000) == tune + "\n" + detail


def test_just_calibrated_leaves_out_both_calibration_parts():
    tune, detail = parts(7_150_000, calibrated=True)
    assert "Calibration" not in tune and "calibration" not in detail.lower()


def test_a_band_that_works_without_a_tuner_skips_the_3_to_1_line():
    tune, _ = parts(7_150_000, half_width=1_000_000)
    assert "3:1" not in tune and "At 7.150 MHz now: SWR 1.00, no tuner needed." in tune


def test_three_to_one_across_the_whole_band():
    tune, _ = parts(7_150_000, half_width=130_000)  # 2:1 is 7.020-7.280; 3:1 runs past both edges
    assert "3:1 bandwidth (most built-in tuners): the whole band (7.000-7.300 MHz, and maybe beyond)" in tune


def test_the_target_line_reads_the_swr_where_you_operate():
    tune, _ = parts(7_150_000, target=7_249_000)  # 99 kHz off: X = 58.3 ohms, SWR 3.03
    assert "At 7.249 MHz now: SWR 3.03, needs a wide-range external tuner." in tune


def test_flat_keeps_what_to_check_in_the_tune_section():
    tune, _ = parts(7_150_000, half_width=5_000_000, r=250)
    assert "No clear dip" in tune and "counterpoise" in tune


def test_best_at_an_edge_keeps_the_trim_in_tune_and_the_why_in_detail():
    tune, detail = parts(6_900_000, half_width=200_000)
    assert "Shorten the antenna at least 2.1%" in tune
    assert "doesn't sweep outside the band" in detail


def test_nothing_connected_tune_is_the_problem_and_detail_the_measurement():
    readings = [reading(7_000_000 + i * 30_000, complex(0.9999, -0.0003)) for i in range(11)]
    tune, detail = report_parts(summarize(readings, target_hz=7_150_000), "40m")
    assert "Check the connection" in tune and "tuner" not in tune
    assert detail.startswith("What the NanoVNA measured")


@pytest.mark.parametrize("swr, band, words", [
    (1.0, "40m", "no tuner needed"),
    (2.0, "40m", "no tuner needed"),
    (2.01, "40m", "within most built-in tuners"),
    (3.0, "40m", "within most built-in tuners"),
    (3.01, "40m", "needs a wide-range external tuner"),
    (8.0, "40m", "needs a wide-range external tuner"),
    (8.01, "40m", "beyond most tuners: check the antenna, coax and connectors"),
    (math.inf, "40m", "beyond most tuners: check the antenna, coax and connectors"),
    (3.0, "6m", "within most built-in tuners"),
    (3.01, "6m", "beyond most tuners: check the antenna, coax and connectors"),  # LDG: 16-150 ohms on 6 m
    (2.0, "2m", "no tuner needed"),
    (2.01, "2m", "most VHF and UHF radios have no tuner: trim or fix the antenna"),
    (2.5, "70cm", "most VHF and UHF radios have no tuner: trim or fix the antenna"),
])
def test_tuner_words_at_each_boundary(swr, band, words):
    assert tuner_need(swr, band) == words


def test_vhf_has_no_3_to_1_line():
    readings = antenna(146_000_000, 1_000_000, start=144_000_000, stop=148_000_000)
    tune, _ = report_parts(summarize(readings, target_hz=146_000_000), "2m")
    assert "2:1 bandwidth" in tune and "3:1" not in tune


# --- inches as well as percent (2026-11-19) ---------------------------------------------------------
# With no length given, a half-wave wire is assumed: 468 / MHz feet (the usual rule of thumb), at the
# best match's frequency, since the percent is of the antenna as it is now.

def test_a_given_length_gives_inches_from_it_not_the_estimate():
    s = summarize(antenna(7_051_000, 60_000), target_hz=7_150_000)
    tune, _ = report_parts(s, "40m", length_m=20.1168)  # 66 ft
    assert "Shorten the antenna about 1.4% (about 11 in / 28 cm; on a dipole, 5.5 in / 14 cm off each end)" in tune
    assert "From the antenna length you gave: 66.0 ft (20.12 m)." in tune
    assert "468" not in tune


def test_a_short_antenna_gets_tenths_of_an_inch():
    readings = antenna(146_000_000, 1_000_000, start=144_000_000, stop=148_000_000)
    s = summarize(readings, target_hz=147_000_000)
    tune, _ = report_parts(s, "2m", length_m=0.5)  # a 2 m whip: 0.68% of 50 cm
    assert "Shorten the antenna about 0.7% (about 0.1 in / 0.3 cm" in tune


def test_the_hint_names_the_apps_field_when_asked():
    s = summarize(antenna(7_051_000, 60_000), target_hz=7_150_000)
    tune, _ = report_parts(s, "40m", length_name="Antenna length")
    assert "give its length (Antenna length)" in tune


def test_no_trim_needed_and_flat_have_no_inches():
    assert " in /" not in parts(7_150_000)[0]
    assert " in /" not in parts(7_150_000, half_width=5_000_000, r=250)[0]
