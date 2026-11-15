"""Cable checks from made-up ideal cables whose answers are known exactly.

An ideal cable of length L and velocity factor VF, open or shorted at the far end, reflects
everything there; the echo comes back delayed by 2L / (VF c) and weakened by twice the cable's
one-way loss. So S11 = (+1 open or -1 short) x 10^(-2 x loss / 20) x e^(-j 4 pi f L / (VF c))."""

import cmath
import math

import pytest

from dipstick.cable import analyze, sweep_for
from dipstick.s11 import reading

C = 299_792_458.0


def loss_db(hz, at_10mhz):
    return at_10mhz * math.sqrt(hz / 10e6)  # coax loss grows about with the square root of frequency


def cable(length_m, vf, end="open", at_10mhz=0.5, start=1_000_000, stop=80_000_000, points=101, mismatch=None):
    sign = 1 if end == "open" else -1
    readings = []
    for i in range(points):
        hz = round(start + i * (stop - start) / (points - 1))
        size = 10 ** (-2 * loss_db(hz, at_10mhz) / 20)
        s11 = sign * size * cmath.exp(-4j * math.pi * hz * length_m / (vf * C))
        if mismatch:
            s11 *= mismatch
        readings.append(reading(hz, s11))
    return readings


@pytest.mark.parametrize("length, vf", [(12.0, 0.66), (30.5, 0.85), (2.0, 0.66), (49.0, 0.66)])
def test_length_from_velocity_factor(length, vf):
    result = analyze(cable(length, vf), vf=vf)
    assert result.length_m == pytest.approx(length, rel=0.002)
    assert result.vf == vf


def test_velocity_factor_from_known_length():
    result = analyze(cable(15.2, 0.78), length_m=15.2)
    assert result.vf == pytest.approx(0.78, rel=0.002)
    assert result.length_m == 15.2


@pytest.mark.parametrize("end", ["open", "short"])
def test_open_or_short_at_the_far_end(end):
    assert analyze(cable(20.0, 0.66, end=end), vf=0.66).end == end


def test_loss_is_half_the_return_loss_at_the_report_frequencies():
    result = analyze(cable(20.0, 0.66, at_10mhz=0.5), vf=0.66)
    # Reported at the reading nearest each frequency (790 kHz apart here), so allow a little.
    for mhz, expected in ((7, loss_db(7e6, 0.5)), (14, loss_db(14e6, 0.5)), (28, loss_db(28e6, 0.5)), (50, loss_db(50e6, 0.5))):
        assert result.loss_db[mhz * 1_000_000] == pytest.approx(expected, abs=0.02)


def test_loss_frequencies_outside_the_sweep_are_left_out():
    result = analyze(cable(20.0, 0.66, stop=30_000_000), vf=0.66)
    assert sorted(result.loss_db) == [7_000_000, 14_000_000, 28_000_000]


def test_a_matched_far_end_cant_be_measured():
    # A dummy load (or an antenna) at the end: almost nothing comes back.
    result = analyze(cable(20.0, 0.66, mismatch=0.05), vf=0.66)
    assert result.end == "matched" and result.length_m is None and result.loss_db == {}


def test_a_clean_line_fits_and_a_messy_one_is_flagged():
    assert analyze(cable(20.0, 0.66), vf=0.66).clean
    readings = cable(20.0, 0.66)
    # Something resonant at the end (like an antenna) bends the phase: no longer a straight line.
    bent = [reading(r.hz, r.s11 * cmath.exp(1j * 1.5 * math.sin(r.hz / 4e6))) for r in readings]
    assert not analyze(bent, vf=0.66).clean


def test_needs_vf_or_length_not_both():
    with pytest.raises(ValueError, match="velocity factor or"):
        analyze(cable(10.0, 0.66))
    with pytest.raises(ValueError, match="velocity factor or"):
        analyze(cable(10.0, 0.66), vf=0.66, length_m=10.0)


@pytest.mark.parametrize("kwargs", [{"vf": 0}, {"vf": 1.01}, {"vf": float("nan")}, {"length_m": 0}, {"length_m": -3},
                                    {"length_m": float("inf")}])
def test_impossible_values_are_refused(kwargs):
    with pytest.raises(ValueError):
        analyze(cable(10.0, 0.66), **kwargs)


# --- choosing the sweep ----------------------------------------------------------------------

def test_the_sweep_keeps_each_step_under_half_a_turn_for_the_longest_cable():
    # The phase must turn less than pi per step, or a long cable would look short (aliasing).
    start, stop, points = sweep_for(max_length_m=50, vf=0.66)
    step = (stop - start) / (points - 1)
    delay = 50 / (0.66 * C)
    assert 4 * math.pi * step * delay < math.pi * 0.85  # with a margin
    assert (start, points) == (1_000_000, 101)


def test_short_cables_get_a_wider_sweep_but_not_past_200_mhz():
    assert sweep_for(max_length_m=2, vf=0.66)[1] == 200_000_000


def test_a_known_length_plans_for_the_slowest_likely_cable():
    # With --length the velocity factor is unknown: assume it could be as low as 0.5.
    assert sweep_for(max_length_m=20, vf=None) == sweep_for(max_length_m=20, vf=0.5)


def test_a_too_long_cable_is_measured_wrong_without_a_longer_sweep():
    # 120 m on a sweep planned for 50 m aliases: that's why --max-length exists.
    readings = cable(120.0, 0.66, stop=sweep_for(max_length_m=50, vf=0.66)[1])
    assert analyze(readings, vf=0.66).length_m != pytest.approx(120.0, rel=0.05)


@pytest.mark.parametrize("max_length", [0, -1, 2001, float("nan")])
def test_max_length_limits(max_length):
    with pytest.raises(ValueError, match="max"):
        sweep_for(max_length_m=max_length, vf=0.66)
