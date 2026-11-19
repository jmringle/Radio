"""The numbers in a band report, from made-up antennas whose answers are known exactly.

The test antenna: R = 50 ohms and a reactance that grows steadily with frequency, X = 0 at f0
(like a dipole near resonance). Then SWR = 1.0 at f0, and SWR = 2.0 where |X| = 35.36 ohms
(|S11| = 1/3 there: 9 X^2 = 100^2 + X^2), so the 2:1 points are where k (f - f0) = +/-35.36."""

import math

import pytest

from dipstick.analysis import summarize
from dipstick.s11 import reading

X_AT_2_TO_1 = 100 / math.sqrt(8)  # 35.355 ohms


def antenna(f0, half_width, start=7_000_000, stop=7_300_000, points=101, r=50.0):
    """Readings for the test antenna: 2:1 points `half_width` Hz either side of f0."""
    k = X_AT_2_TO_1 / half_width  # ohms per Hz
    step = (stop - start) / (points - 1)
    readings = []
    for i in range(points):
        hz = round(start + i * step)
        z = complex(r, k * (hz - f0))
        readings.append(reading(hz, (z - 50) / (z + 50)))
    return readings


def test_resonant_mid_band():
    s = summarize(antenna(7_150_000, 60_000), target_hz=7_150_000)
    assert s.best.hz == 7_150_000 and s.best.swr == pytest.approx(1.0)
    assert s.best_at_edge is None
    assert s.two_to_one == pytest.approx((7_090_000, 7_210_000), abs=1_500)  # interpolated between 3 kHz steps
    assert (s.two_to_one_reaches_low, s.two_to_one_reaches_high) == (False, False)
    assert s.zero_reactance == pytest.approx([7_150_000], abs=1)
    assert s.trim_percent == pytest.approx(0.0)


def test_edges_and_middle():
    s = summarize(antenna(7_150_000, 60_000), target_hz=7_150_000)
    assert [r.hz for r in (s.low, s.middle, s.high)] == [7_000_000, 7_150_000, 7_300_000]
    # 150 kHz off: X = 35.36 x 150/60 = 88.4 ohms; |S11| = 88.4 / |100 + j88.4| = 0.6623; SWR = 4.92
    assert s.low.swr == pytest.approx(4.92, abs=0.01) and s.high.swr == pytest.approx(4.92, abs=0.01)


def test_resonant_below_target_means_too_long():
    # Best match at 7.051 MHz (readings are 3 kHz apart), target 7.150: 7.051 / 7.150 = 0.98615,
    # so about 1.38% too long.
    s = summarize(antenna(7_051_000, 60_000), target_hz=7_150_000)
    assert s.best.hz == 7_051_000
    assert s.trim_percent == pytest.approx(-1.385, abs=0.001)  # negative: shorten


def test_resonant_above_target_means_too_short():
    # 7.249 / 7.074 = 1.02474: about 2.47% too short.
    s = summarize(antenna(7_249_000, 60_000), target_hz=7_074_000)
    assert s.trim_percent == pytest.approx(2.474, abs=0.001)  # positive: lengthen


def test_best_match_below_the_band():
    # Resonant at 6.9 MHz: inside the band SWR only rises, so the true best is somewhere below.
    s = summarize(antenna(6_900_000, 200_000), target_hz=7_150_000)
    assert s.best.hz == 7_000_000 and s.best_at_edge == "low"
    assert s.zero_reactance == []


def test_best_match_above_the_band():
    assert summarize(antenna(7_400_000, 200_000), target_hz=7_150_000).best_at_edge == "high"


def test_two_to_one_runs_off_the_band():
    # Very wide antenna (a broadband one): 2:1 everywhere in the band.
    s = summarize(antenna(7_150_000, 1_000_000), target_hz=7_150_000)
    assert s.two_to_one == (7_000_000, 7_300_000)
    assert (s.two_to_one_reaches_low, s.two_to_one_reaches_high) == (True, True)


def test_never_reaches_two_to_one():
    s = summarize(antenna(7_150_000, 60_000, r=200), target_hz=7_150_000)  # 200 ohms: SWR 4 at best
    assert s.best.swr == pytest.approx(4.0)
    assert s.two_to_one is None


def test_nothing_connected():
    # An open port, like the recorded scan: everything comes back at every frequency.
    readings = [reading(7_000_000 + i * 30_000, complex(0.9999, -0.0003)) for i in range(11)]
    s = summarize(readings, target_hz=7_150_000)
    assert s.nothing_connected
    assert s.trim_percent is None and s.two_to_one is None


def test_a_good_antenna_is_not_nothing_connected():
    assert not summarize(antenna(7_150_000, 60_000), target_hz=7_150_000).nothing_connected


def test_target_outside_the_sweep_is_refused():
    with pytest.raises(ValueError, match="target"):
        summarize(antenna(7_150_000, 60_000), target_hz=14_074_000)


def test_too_few_readings():
    with pytest.raises(ValueError, match="2 readings"):
        summarize(antenna(7_150_000, 60_000)[:1], target_hz=7_000_000)


def test_nothing_connected_starts_above_swr_10():
    # R = 450 ohms: SWR 9, a bad antenna but an antenna. R = 800: SWR 16, treated as nothing there.
    assert not summarize(antenna(7_150_000, 60_000, r=450), target_hz=7_150_000).nothing_connected
    assert summarize(antenna(7_150_000, 60_000, r=800), target_hz=7_150_000).nothing_connected


def test_two_to_one_is_interpolated_between_coarse_readings():
    # 11 points, 30 kHz apart; the true 2:1 points (7.100 and 7.200) fall between readings.
    # Without interpolation the answer would be the nearest inside readings, 7.120 and 7.180.
    s = summarize(antenna(7_150_000, 50_000, points=11), target_hz=7_150_000)
    assert s.two_to_one == pytest.approx((7_100_000, 7_200_000), abs=5_000)


def test_two_to_one_next_to_an_infinite_reading_stops_at_the_good_one():
    readings = [reading(7_000_000, complex(1, 0)), reading(7_030_000, complex(0, 0)), reading(7_060_000, complex(1, 0))]
    assert summarize(readings, target_hz=7_030_000).two_to_one == (7_030_000, 7_030_000)


def test_reactance_crossing_between_readings():
    # X is a straight line in frequency here, so interpolating finds 7.1515 MHz exactly.
    s = summarize(antenna(7_151_500, 60_000), target_hz=7_150_000)
    assert s.zero_reactance == pytest.approx([7_151_500], abs=1)


# --- what a tuner can reach (display review 2026-11-19) ---------------------------------------
# For the test antenna SWR = 3 where |S11| = 1/2: 4 X^2 = 100^2 + X^2, so |X| = 57.74 ohms,
# 57.74 / 35.36 = 1.633 times as far from f0 as the 2:1 points.

def test_three_to_one_range_is_wider_than_two_to_one():
    s = summarize(antenna(7_150_000, 60_000), target_hz=7_150_000)
    assert s.three_to_one == pytest.approx((7_052_020, 7_247_980), abs=1_500)
    assert (s.three_to_one_reaches_low, s.three_to_one_reaches_high) == (False, False)


def test_three_to_one_running_into_an_edge():
    s = summarize(antenna(7_051_000, 60_000), target_hz=7_150_000)
    assert s.three_to_one[0] == 7_000_000 and s.three_to_one_reaches_low and not s.three_to_one_reaches_high


def test_no_three_to_one_when_the_best_is_worse():
    s = summarize(antenna(7_150_000, 60_000, r=200), target_hz=7_150_000)  # SWR 4 at best
    assert s.three_to_one is None and not s.three_to_one_reaches_low and not s.three_to_one_reaches_high


def test_the_reading_at_the_target_is_the_nearest_one():
    s = summarize(antenna(7_150_000, 60_000), target_hz=7_074_000)  # readings at 7.072 and 7.075
    assert s.at_target.hz == 7_075_000


def test_spans_under_a_limit_find_every_stretch():
    from dipstick.analysis import spans
    readings = antenna(7_150_000, 60_000)
    [found] = spans(readings, 2.0)
    assert found == pytest.approx((7_090_000, 7_210_000), abs=1_500)
    assert spans(antenna(7_150_000, 60_000, r=200), 2.0) == []  # SWR 4 at best
    # Two dips: under 2 around 7.05 and 7.25, over 2 between.
    two_dips = antenna(7_050_000, 30_000)[:51] + antenna(7_250_000, 30_000)[51:]
    assert len(spans(two_dips, 2.0)) == 2
    assert spans(antenna(7_150_000, 1_000_000), 2.0) == [(7_000_000, 7_300_000)]  # the whole band
