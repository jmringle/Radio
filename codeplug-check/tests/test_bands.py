"""Band edges: 47 CFR 97.301(a), ITU Region 2 (eCFR, up to date as of 2026-11-12)."""

import pytest

from codeplug_check.bands import band_for


@pytest.mark.parametrize("hz, band", [
    (144_000_000, "2m"), (146_520_000, "2m"), (148_000_000, "2m"),  # edges are inside
    (222_000_000, "1.25m"), (225_000_000, "1.25m"),
    (420_000_000, "70cm"), (446_000_000, "70cm"), (450_000_000, "70cm"),
    (50_000_000, "6m"), (902_000_000, "33cm"), (1_300_000_000, "23cm"),
])
def test_amateur_frequencies_name_their_band(hz, band):
    assert band_for(hz) == band


@pytest.mark.parametrize("hz", [
    143_999_999, 148_000_001,  # one hertz outside 2 m
    419_999_999, 450_000_001,
    219_500_000,  # 1.25 m's 219-220 MHz: fixed digital message forwarding only, 97.303(l)
    462_562_500,  # GMRS channel 1 (Part 95): not amateur
    162_550_000,  # NOAA weather: receive only
    0,
])
def test_anything_else_is_outside_the_amateur_bands(hz):
    assert band_for(hz) is None
