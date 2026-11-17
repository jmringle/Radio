"""The transformer test (ununs and voltage baluns): a resistor on the output, port 1 on the input.

An ideal n:1 transformer with a resistor R on its output looks like R / n at its input, so with
R = 50 x n the NanoVNA should see 50 ohms: SWR 1. Readings here are made up from impedances whose
SWR is known: Z = 50 x s (purely resistive) has SWR s, for s at or above 1."""

import math

import pytest

from dipstick.balun import POINTS, START_HZ, STOP_HZ, analyze_transformer, ideal_swr
from dipstick.s11 import Z0, Reading, reading


def sweep(impedance_at):
    """Readings over the transformer sweep, with the impedance `impedance_at(hz)` gives."""
    readings = []
    for i in range(POINTS):
        hz = round(START_HZ + i * (STOP_HZ - START_HZ) / (POINTS - 1))
        z = impedance_at(hz)
        readings.append(reading(hz, 1 + 0j if z == math.inf else (z - Z0) / (z + Z0)))
    return readings


def rising(hz):
    """SWR 1 up to 15 MHz, then rising: 50 x (1 + 0.2 per MHz above 15), the high bands worse."""
    return Z0 * (1 + max(0.0, (hz - 15e6) / 1e6 * 0.2))


# --- what a perfect transformer would read with your resistor ---------------------------------

@pytest.mark.parametrize("ratio, ohms, swr", [
    ("49:1", 2450, 1.0),  # 2450 / 49 = 50
    ("49:1", 2700, 1.102),  # 2700 / 49 = 55.10 ohms: 55.10 / 50
    ("4:1", 180, 1.111),  # 180 / 4 = 45 ohms: 50 / 45
    ("1:1", 47, 1.064),  # 50 / 47
    ("9:1", 450, 1.0),
])
def test_ideal_swr_with_the_resistor_used(ratio, ohms, swr):
    assert ideal_swr(ratio, ohms) == pytest.approx(swr, abs=0.001)


# --- per band ---------------------------------------------------------------------------------

def test_every_hf_band_and_6m_in_order():
    result = analyze_transformer(sweep(lambda hz: Z0), "49:1", 2450)
    assert [b.band for b in result.bands] == ["160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]
    assert all(b.swr == pytest.approx(1.0) for b in result.bands)


def test_each_band_reads_the_sweep_point_nearest_its_middle():
    # Points are 0.522 MHz apart from 1.8 MHz: 40 m's middle (7.15) is nearest 7.020 (point 10),
    # 30 m's (10.125) nearest 10.152 (point 16), 6 m's (52) nearest 51.912 (point 96).
    by_band = {b.band: b.hz for b in analyze_transformer(sweep(lambda hz: Z0), "49:1", 2450).bands}
    assert by_band["40m"] == 7_020_000
    assert by_band["30m"] == 10_152_000
    assert by_band["6m"] == 51_912_000


def test_bands_where_it_matches_and_where_it_doesnt():
    result = analyze_transformer(sweep(rising), "49:1", 2450)
    swr = {b.band: b.swr for b in result.bands}
    assert swr["40m"] == pytest.approx(1.0) and swr["20m"] == pytest.approx(1.0)  # 14.328 MHz: below 15
    assert swr["15m"] == pytest.approx(2.2228)  # nearest point 21.114 MHz: 1 + 6.114 x 0.2
    assert swr["17m"] == pytest.approx(1.5964)  # 17.982 MHz: 1 + 2.982 x 0.2
    assert result.matched == ["160m", "80m", "40m", "30m", "20m", "17m"]  # SWR 2 or under
    assert result.unmatched == ["15m", "12m", "10m", "6m"]


def test_the_ideal_swr_comes_with_the_result():
    assert analyze_transformer(sweep(lambda hz: Z0), "49:1", 2700).ideal_swr == pytest.approx(1.102, abs=0.001)


# --- when the test can't say anything ---------------------------------------------------------

@pytest.mark.parametrize("z", [math.inf, 0.5, 800.0])  # open, a short, nothing like 50 ohms anywhere
def test_swr_over_10_everywhere_asks_about_the_resistor(z):
    with pytest.raises(ValueError, match="resistor connected"):
        analyze_transformer(sweep(lambda hz: z), "49:1", 2450)


def test_over_10_at_most_points_but_not_all_is_still_measured():
    result = analyze_transformer(sweep(lambda hz: Z0 if hz < 2.5e6 else 800.0), "49:1", 2450)
    assert result.matched == ["160m"]


def test_exactly_2_counts_as_matched():
    readings = [Reading(r.hz, r.s11, r.impedance, 2.0, r.return_loss_db) for r in sweep(lambda hz: 2 * Z0)]
    result = analyze_transformer(readings, "49:1", 2450)
    assert len(result.matched) == 10 and result.unmatched == []
