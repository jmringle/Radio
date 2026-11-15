"""Antenna sweeps stay inside one amateur band (README acceptance criteria, radio rules).
Band edges: 47 CFR 97.301(a) and (b), Region 2."""

import pytest

from dipstick.bands import band_range, check_antenna_sweep


@pytest.mark.parametrize("band, low, high", [
    ("160m", 1_800_000, 2_000_000), ("80m", 3_500_000, 4_000_000), ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000), ("20m", 14_000_000, 14_350_000), ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000), ("12m", 24_890_000, 24_990_000), ("10m", 28_000_000, 29_700_000),
    ("6m", 50_000_000, 54_000_000), ("2m", 144_000_000, 148_000_000), ("1.25m", 222_000_000, 225_000_000),
    ("70cm", 420_000_000, 450_000_000), ("33cm", 902_000_000, 928_000_000), ("23cm", 1_240_000_000, 1_300_000_000),
])
def test_band_edges(band, low, high):
    assert band_range(band) == (low, high)


@pytest.mark.parametrize("band", ["60m", "11m", "", "40M"])
def test_unknown_bands(band):
    # 60 m is five channels, not a band (97.303(h)); 11 m is CB, not amateur.
    with pytest.raises(ValueError, match="band"):
        band_range(band)


@pytest.mark.parametrize("start, stop", [(7_000_000, 7_300_000), (7_000_000, 7_000_001), (146_000_000, 146_100_000)])
def test_sweeps_inside_a_band_are_allowed(start, stop):
    check_antenna_sweep(start, stop)  # no error


@pytest.mark.parametrize("start, stop", [
    (6_999_999, 7_300_000),    # 1 Hz below 40 m
    (7_000_000, 7_300_001),    # 1 Hz above
    (7_000_000, 14_350_000),   # starts and ends in bands, crosses everything between
    (5_000_000, 6_000_000),    # no band at all
    (7_300_000, 7_000_000),    # backwards
    (7_100_000, 7_100_000),    # a single point isn't a sweep
])
def test_sweeps_that_leave_a_band_are_refused(start, stop):
    with pytest.raises(ValueError, match="amateur band"):
        check_antenna_sweep(start, stop)
