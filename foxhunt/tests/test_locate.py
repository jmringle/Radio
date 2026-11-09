"""Sweep fit and probability map (README: acceptance criteria, phase 2b). Coordinates are made up
(open country, not anyone's address); true bearings come from the same flat-earth geometry."""
import math

import numpy as np
import pytest

from foxhunt.locate import ASSUMED_PM_DEG, MAP_NEEDS, fit_sweep, probability_map, spot_bearing, summarize

LAT0, LON0 = 40.0, -100.0


def yagi(heading, toward, k=8, peak=-40.0):
    """A level from a cardioid yagi pointed at heading, fox at toward."""
    shape = (1 + math.cos(math.radians(heading - toward))) / 2
    return peak + max(10 * k * math.log10(shape) if shape > 0 else -99, -20)


def sweep(toward, headings, noise_db=0.0, seed=1):
    rng = np.random.default_rng(seed)
    return [(h, yagi(h, toward) + rng.normal(0, noise_db) if noise_db else yagi(h, toward)) for h in headings]


def miss(a, b):
    return abs((a - b + 180) % 360 - 180)


# --- sweep fit ---

def test_a_clean_full_circle_sweep_finds_the_bearing():
    fit = fit_sweep(sweep(212, range(0, 360, 45)))
    assert miss(fit["heading"], 212) <= 1 and fit["pm"] <= 10


def test_a_noisy_sweep_is_close_and_its_range_covers_the_truth():
    fit = fit_sweep(sweep(212, range(0, 360, 30), noise_db=1.5))
    assert miss(fit["heading"], 212) <= fit["pm"] * 2 and fit["pm"] < 30


def test_a_sweep_across_north_wraps_correctly():
    fit = fit_sweep(sweep(355, [300, 330, 0, 30, 60]))
    assert miss(fit["heading"], 355) <= 2


def test_four_marks_around_the_front_are_enough():
    assert fit_sweep(sweep(100, [60, 90, 120, 150])) is not None


def test_noisier_sweeps_get_wider_ranges():
    clean = fit_sweep(sweep(212, range(0, 360, 30), noise_db=0.5))
    noisy = fit_sweep(sweep(212, range(0, 360, 30), noise_db=4.0))
    assert noisy["pm"] > clean["pm"]


def test_the_range_has_a_floor():
    assert fit_sweep(sweep(212, range(0, 360, 10)))["pm"] >= 3.0  # a perfect fit still isn't exact


@pytest.mark.parametrize("points", [
    sweep(212, [180, 200, 220]),  # too few
    sweep(212, [100, 120, 140, 160]),  # all on one side: the peak may be past the last mark
    [(0, -40.0), (90, -40.0), (180, -40.0), (270, -40.0)],  # flat: says nothing
    [(0, -40.0), (90, -41.0), (180, -42.0), (270, -41.5)],  # under 3 dB from best to worst: mostly reflections
    [(0, -40.0), (90, -40.0), (180, -50.0), (270, -50.0)],  # strongest tied with its only neighbor on one side
])
def test_sweeps_that_cant_pin_a_bearing_give_none(points):
    assert fit_sweep(points) is None


def test_a_single_mark_is_used_as_pointed_with_an_assumed_range():
    bearing = spot_bearing([{"heading": 75.0, "level_db": -50.0}])
    assert bearing["heading"] == 75.0 and bearing["pm"] == ASSUMED_PM_DEG and "assumed" in bearing["method"]


def test_a_spot_with_a_good_sweep_uses_the_fit():
    marks = [{"heading": h, "level_db": lvl} for h, lvl in sweep(212, range(0, 360, 45))]
    assert spot_bearing(marks)["method"] == "fitted from 8 headings"


def test_summarize_groups_marks_by_spot():
    spots = [{"id": 1, "lat": None, "lon": None}, {"id": 2, "lat": None, "lon": None}]
    bearings = [{"spot": 1, "heading": 10.0, "level_db": -50}, {"spot": 2, "heading": 20.0, "level_db": -50}]
    out = summarize(spots, bearings)
    assert [s["bearing"]["heading"] for s in out] == [10.0, 20.0] and len(out[0]["marks"]) == 1


# --- probability map ---

FOX = (40.01, -99.99)  # about 1.1 km north and 0.85 km east of LAT0, LON0


def toward_fox(lat, lon):
    dx = math.radians(FOX[1] - lon) * 6_371_000 * math.cos(math.radians(lat))
    dy = math.radians(FOX[0] - lat) * 6_371_000
    return math.degrees(math.atan2(dx, dy)) % 360


def spot(id_, lat, lon, heading=None, pm=5.0):
    heading = toward_fox(lat, lon) if heading is None else heading
    return {"id": id_, "lat": lat, "lon": lon, "bearing": {"heading": heading, "pm": pm}}


def distance_m(estimate):
    dy = math.radians(estimate["lat"] - FOX[0]) * 6_371_000
    dx = math.radians(estimate["lon"] - FOX[1]) * 6_371_000 * math.cos(math.radians(FOX[0]))
    return math.hypot(dx, dy)


def test_two_crossing_bearings_find_the_fox():
    result = probability_map([spot(1, 40.0, -100.0), spot(2, 40.0, -99.98)])
    assert distance_m(result["estimate"]) < 100 and result["reflections"] == []
    assert len(result["grid"]) == result["size"] ** 2 and max(result["grid"]) == 255


def test_more_spots_shrink_the_search_area():
    two = probability_map([spot(1, 40.0, -100.0), spot(2, 40.0, -99.98)])
    three = probability_map([spot(1, 40.0, -100.0), spot(2, 40.0, -99.98), spot(3, 40.02, -99.99)])
    assert three["area_km2"] < two["area_km2"]


def test_sharper_bearings_give_a_smaller_area():
    loose = probability_map([spot(1, 40.0, -100.0, pm=15), spot(2, 40.0, -99.98, pm=15)])
    tight = probability_map([spot(1, 40.0, -100.0, pm=3), spot(2, 40.0, -99.98, pm=3)])
    assert tight["area_km2"] < loose["area_km2"]


def test_a_reflection_is_flagged_and_left_out():
    good = [spot(1, 40.0, -100.0), spot(2, 40.0, -99.98), spot(3, 40.02, -99.99)]
    bounced = spot(4, 40.02, -100.01, heading=(toward_fox(40.02, -100.01) + 60) % 360)
    result = probability_map(good + [bounced])
    assert result["reflections"] == [4] and "spot 4" in result["text"]
    assert distance_m(result["estimate"]) < 100


def test_with_three_spots_nothing_is_called_a_reflection():
    bounced = spot(3, 40.02, -99.99, heading=(toward_fox(40.02, -99.99) + 60) % 360)
    result = probability_map([spot(1, 40.0, -100.0), spot(2, 40.0, -99.98), bounced])
    assert result["reflections"] == []  # one odd spot out of three can't be told from a good one


@pytest.mark.parametrize("summaries", [
    [],
    [spot(1, 40.0, -100.0)],  # one spot: a line, not a place
    [spot(1, 40.0, -100.0), {"id": 2, "lat": None, "lon": None, "bearing": {"heading": 10.0, "pm": 5}}],
    [spot(1, 40.0, -100.0), {"id": 2, "lat": 40.0, "lon": -99.98, "bearing": None}],
])
def test_the_map_needs_two_spots_with_positions_and_bearings(summaries):
    result = probability_map(summaries)
    assert result["estimate"] is None and result["text"] == MAP_NEEDS


def test_bearings_pointing_off_the_map_say_so():
    # Nearly parallel bearings pointing north: they cross far away, at the map's north edge.
    result = probability_map([spot(1, 40.0, -100.0, heading=1.0), spot(2, 40.0, -99.999, heading=359.0)])
    assert result["at_edge"] and "edge of the map" in result["text"]
