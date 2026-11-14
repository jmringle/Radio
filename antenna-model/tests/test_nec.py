"""NEC2 through PyNEC, checked against textbook antenna values: a thin half-wave dipole in free
space is about 73 + j42 ohms, and resonates a few percent shorter than a half wavelength, near
70 ohms (standard antenna theory, e.g. the ARRL Antenna Book). These prove the NEC2 setup is
right before any model of a real antenna is trusted."""

import pytest

from antenna_model.nec import dipole_impedance

C = 299.792458  # speed of light, m per microsecond: wavelength in m = C / MHz
MHZ = 14.2
WAVELENGTH = C / MHZ
THIN = WAVELENGTH * 1e-5  # wire radius: thin enough to act like the textbook's ideal wire


def test_a_half_wave_dipole_is_about_73_ohms_and_inductive():
    z = dipole_impedance(MHZ, WAVELENGTH / 2, THIN)
    assert 70 < z.real < 80
    assert 35 < z.imag < 50  # a full half wave is slightly too long: inductive (+j)


def test_a_slightly_shorter_dipole_is_nearly_resonant():
    z = dipole_impedance(MHZ, 0.485 * WAVELENGTH, THIN)
    assert 65 < z.real < 75
    assert abs(z.imag) < 20  # near resonance: almost no reactance


def test_too_short_is_capacitive():
    assert dipole_impedance(MHZ, 0.45 * WAVELENGTH, THIN).imag < -50


@pytest.mark.parametrize("mhz, length, radius", [
    (0, 10.0, 0.001), (-14.2, 10.0, 0.001), (14.2, 0, 0.001), (14.2, 10.0, 0), (14.2, 10.0, 6.0),
    (float("nan"), 10.0, 0.001), (14.2, float("inf"), 0.001),
])
def test_impossible_dimensions_are_refused(mhz, length, radius):
    # radius 6.0 on a 10 m wire: fatter than a segment is long, outside NEC2's thin-wire model.
    with pytest.raises(ValueError):
        dipole_impedance(mhz, length, radius)
