"""The band report's wording and advice: every number comes with what it means."""

from test_analysis import antenna

from dipstick.analysis import summarize
from dipstick.report import report
from dipstick.s11 import reading


def text(f0, half_width=60_000, target=7_150_000, **kwargs):
    return report(summarize(antenna(f0, half_width, **kwargs), target_hz=target), "40m")


def test_heading_names_the_band_and_points():
    assert text(7_150_000).splitlines()[0] == "40m: 7.000-7.300 MHz, 101 points"


def test_a_well_matched_antenna():
    out = text(7_150_000)
    assert "Best match: SWR 1.00 at 7.150 MHz (excellent)" in out
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
