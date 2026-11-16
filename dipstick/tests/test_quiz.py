"""The "Check yourself" questions (Phase 4): built from your own sweep, answered by dipstick's analysis.

A wrong answer key would teach the wrong thing, so every expected answer here is worked out by
hand from a made-up antenna or cable with a known answer, never with the quiz's own formula."""

import pytest
from test_analysis import antenna
from test_cable_cli import planned

from dipstick.analysis import summarize
from dipstick.cable import CableResult, analyze
from dipstick.quiz import antenna_questions, cable_questions
from dipstick.s11 import reading


def about(questions, words):
    """The one question whose wording contains `words`, or None."""
    found = [q for q in questions if words in q.ask]
    assert len(found) <= 1
    return found[0] if found else None


def right(question):
    return question.choices[question.answer]


def ask(f0, half_width=60_000, target=7_150_000, **kwargs):
    return antenna_questions(summarize(antenna(f0, half_width, **kwargs), target_hz=target))


# --- antenna: which way to trim -------------------------------------------------------------------

def test_too_long_means_shorter():
    # Best match 7.051 MHz, below the 7.150 target: a shorter antenna resonates higher.
    q = about(ask(7_051_000), "should the antenna be")
    assert right(q) == "Shorter"
    assert "7.051" in q.ask and "7.150" in q.ask
    assert "1.4%" in q.why  # the same percent as the report's advice


def test_too_short_means_longer():
    assert right(about(ask(7_249_000, target=7_074_000), "should the antenna be")) == "Longer"


def test_on_target_means_leave_it():
    assert right(about(ask(7_150_000), "should the antenna be")) == "Leave it as it is"


def test_best_match_below_the_band_means_shorter():
    assert right(about(ask(6_900_000, half_width=200_000), "should the antenna be")) == "Shorter"


def test_best_match_above_the_band_means_longer():
    assert right(about(ask(7_400_000, half_width=200_000), "should the antenna be")) == "Longer"


def test_a_flat_curve_gets_no_trim_question():
    # No clear dip (the 2m HT case): trimming won't fix it, so don't ask about trimming.
    assert about(ask(7_150_000, half_width=5_000_000, r=250), "should the antenna be") is None


# --- antenna: how much power comes back -----------------------------------------------------------
# At resonance the test antenna's impedance is r, so SWR = r / 50. The share of power that comes
# back is ((SWR - 1) / (SWR + 1)) squared, worked out here by hand.

@pytest.mark.parametrize("r, share", [
    (50, "Under 1%"),         # SWR 1.0: nothing comes back
    (75, "About 1% to 10%"),  # SWR 1.5: (0.5 / 2.5)^2 = 4%
    (125, "About 10% to 25%"),  # SWR 2.5: (1.5 / 3.5)^2 = 18.4%
    (250, "Over 25%"),        # SWR 5.0: (4 / 6)^2 = 44.4%
])
def test_the_share_of_power_that_comes_back(r, share):
    q = about(ask(7_150_000, r=r), "comes back")
    assert right(q) == share


def test_the_reason_shows_the_working():
    q = about(ask(7_150_000, r=75), "comes back")
    assert "1.50" in q.ask and "4.0%" in q.why


# --- antenna: a frequency without a tuner ---------------------------------------------------------

def test_a_narrow_antenna_needs_a_tuner_at_the_far_edge():
    # 2:1 only 60 kHz either side of 7.150: both edges read SWR 4.92, so no.
    q = about(ask(7_150_000), "without a tuner")
    assert right(q) == "No"
    assert "4.92" in q.why


def test_a_broad_antenna_works_across_the_band():
    q = about(ask(7_150_000, half_width=1_000_000), "without a tuner")
    assert right(q) == "Yes"


def test_the_frequency_asked_about_is_the_edge_farther_from_the_best_match():
    # Best match at 7.051: the high edge (7.300) is farther away, so that's the one asked about.
    assert "7.300" in about(ask(7_051_000), "without a tuner").ask


# --- antenna: nothing to ask ----------------------------------------------------------------------

def test_nothing_connected_asks_nothing():
    readings = [reading(7_000_000 + i * 30_000, complex(0.9999, -0.0003)) for i in range(11)]
    assert antenna_questions(summarize(readings, target_hz=7_150_000)) == []


# --- cable ----------------------------------------------------------------------------------------

def test_foam_coax_means_the_same_echo_is_a_longer_cable():
    # Measured at VF 0.66. Foam (0.82) is faster, so the same delay covers more cable:
    # 12.00 m x 0.82 / 0.66 = 14.91 m.
    q = about(cable_questions(analyze(planned(12.0, 0.66), vf=0.66)), "velocity factor")
    assert right(q) == "Longer"
    assert "14.91" in q.why


def test_slower_coax_means_the_same_echo_is_a_shorter_cable():
    # Measured at VF 0.85, so the question compares with solid coax (0.66): 12 x 0.66 / 0.85 = 9.32 m.
    q = about(cable_questions(analyze(planned(12.0, 0.85, plan_vf=0.85), vf=0.85)), "velocity factor")
    assert right(q) == "Shorter"
    assert "9.32" in q.why


def test_a_longer_cable_than_you_said_means_a_higher_velocity_factor():
    # Given the length, dipstick works out the VF = length / (delay x c): a longer cable, a higher VF.
    q = about(cable_questions(analyze(planned(15.24, 0.78, plan_vf=None), length_m=15.24)), "velocity factor")
    assert right(q) == "Higher"


def test_how_much_of_20_watts_reaches_the_far_end():
    # 1.00 dB one way at 28 MHz: 20 W x 10^(-1.00 / 10) = 15.89 W arrives.
    result = CableResult("open", 12.0, 0.66, {28_000_000: 1.0}, True, True)
    q = about(cable_questions(result), "20 W")
    assert right(q) == "15.9 W"
    assert "1.00 dB" in q.why and "28 MHz" in q.why


def test_a_matched_end_asks_nothing():
    assert cable_questions(CableResult("matched", None, None, {}, False, True)) == []


def test_no_length_means_no_velocity_factor_question():
    result = CableResult("open", None, None, {28_000_000: 1.0}, False, True)
    assert about(cable_questions(result), "velocity factor") is None


# --- every question -------------------------------------------------------------------------------

def every_question():
    yield from ask(7_051_000) + ask(7_150_000, r=125) + ask(7_400_000, half_width=200_000)
    yield from cable_questions(analyze(planned(12.0, 0.66), vf=0.66))
    yield from cable_questions(CableResult("short", 3.0, 0.66, {7_000_000: 0.1, 28_000_000: 0.4}, True, True))


def test_every_question_has_two_to_four_choices_and_a_real_answer():
    for q in every_question():
        assert 2 <= len(q.choices) <= 4, q.ask
        assert len(set(q.choices)) == len(q.choices), q.ask
        assert 0 <= q.answer < len(q.choices), q.ask
        assert q.ask and q.why


def test_at_most_three_antenna_and_two_cable_questions():
    assert len(ask(7_051_000)) <= 3
    assert len(cable_questions(analyze(planned(12.0, 0.66), vf=0.66))) <= 2


# --- paths the first tests didn't reach (checked branch by branch, 2026-11-16) -----------------------

def test_beyond_an_edge_the_reason_says_at_least():
    # Best match below the band: 7.000 / 7.150 = 0.979, so at least 2.1% shorter (as the report says).
    q = about(ask(6_900_000, half_width=200_000), "should the antenna be")
    assert "at least 2.1%" in q.why and "below the band" in q.why


def test_the_low_edge_is_asked_about_when_it_is_farther():
    # Best match at 7.249: the low edge (7.000) is farther away.
    assert "7.000" in about(ask(7_249_000), "without a tuner").ask


def test_a_sweep_that_stops_below_28_mhz_asks_about_its_highest_loss():
    # A long cable's sweep may stop before 28 MHz: ask about 14 MHz instead. 20 W x 10^(-0.5 / 10) = 17.8 W.
    q = about(cable_questions(CableResult("open", 80.0, 0.66, {7_000_000: 0.3, 14_000_000: 0.5}, True, True)), "20 W")
    assert "14 MHz" in q.ask and right(q) == "17.8 W"


def test_so_little_loss_that_the_choices_match_asks_nothing_about_loss():
    # 0.01 dB: 19.95 W and 19.91 W both round to 20.0 W, the same as "all of it".
    result = CableResult("open", 0.3, 0.66, {28_000_000: 0.01}, True, True)
    assert about(cable_questions(result), "20 W") is None


def test_no_loss_figures_asks_nothing_about_loss():
    assert about(cable_questions(CableResult("open", 3.0, 0.66, {}, True, True)), "20 W") is None


def test_where_the_right_loss_answer_sits_varies_with_the_cable():
    positions = {about(cable_questions(CableResult("open", 9.0, 0.66, {28_000_000: db}, True, True)), "20 W").answer
                 for db in (0.50, 0.51, 0.52)}
    assert len(positions) == 3  # not always the middle one, which you'd learn to pick


def test_28_mhz_is_asked_about_even_when_the_sweep_reaches_50():
    # A real sweep that reaches 50 MHz has all four figures; 28 MHz (10 m) is the one asked about.
    result = CableResult("open", 12.0, 0.66, {7_000_000: 0.43, 14_000_000: 0.58, 28_000_000: 0.84, 50_000_000: 1.12},
                         True, True)
    assert "28 MHz" in about(cable_questions(result), "20 W").ask
