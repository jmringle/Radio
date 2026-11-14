"""SWR from a feedpoint impedance. Expected values are worked by hand from
SWR = (1 + |G|) / (1 - |G|), G = (Z - Z0) / (Z + Z0), not by calling the code's own formula."""

import math

import pytest

from antenna_model.swr import swr


@pytest.mark.parametrize("z, expected", [
    (50, 1.0),         # matched
    (100, 2.0),        # pure resistance: SWR is the ratio, either way round
    (25, 2.0),
    (50 + 50j, 2.618),  # |G| = 50 / 111.8 = 0.447
    (73, 1.46),        # a free-space half-wave dipole on 50-ohm coax
])
def test_known_values(z, expected):
    assert swr(z) == pytest.approx(expected, abs=0.005)


def test_another_line_impedance():
    assert swr(450, z0=450) == pytest.approx(1.0)  # ladder line


@pytest.mark.parametrize("z", [0, 1e-12j, 100j, -100j])
def test_no_resistance_reflects_everything(z):
    # A short, or a pure reactance: no power is accepted, so the SWR is infinite.
    assert swr(z) == math.inf


@pytest.mark.parametrize("z, z0", [(-1 + 0j, 50), (50, 0), (50, -50)])
def test_impossible_inputs_are_refused(z, z0):
    # Negative resistance would mean the antenna makes power; Z0 must be positive.
    with pytest.raises(ValueError):
        swr(z, z0)


@pytest.mark.parametrize("z", [complex(math.nan, 0), complex(0, math.inf)])
def test_non_numbers_are_refused(z):
    with pytest.raises(ValueError):
        swr(z)
