"""Attenuator coaching (README: acceptance criteria, phase 2b)."""
import pytest

from foxhunt.coach import CLOSE, STRONG, WEAK, WINDOW, Coach


def r(over_noise_db, attenuator_db=0.0, gain_db=20.0, overload=False):
    return {"over_noise_db": over_noise_db, "attenuator_db": attenuator_db, "gain_db": gain_db, "overload": overload}


def feed(coach, reading, n=WINDOW):
    advice = None
    for _ in range(n):
        advice = coach.update(reading)
    return advice


def test_overload_says_add_attenuation_at_once():
    advice = Coach().update(r(20, overload=True))
    assert "add 10 dB" in advice and "lower the gain" in advice


def test_overload_at_zero_gain_doesnt_suggest_lowering_it():
    assert "lower the gain" not in Coach().update(r(20, gain_db=0.0, overload=True))


def test_overload_advice_lasts_a_second_after_the_last_clip():
    coach = Coach()
    coach.update(r(20, overload=True))
    assert "Overloaded" in feed(coach, r(20), WINDOW - 1)
    assert coach.update(r(20)) is None


@pytest.mark.parametrize("over_noise, attenuator, advice", [
    (46, 0, STRONG), (46, 59, STRONG), (46, 60, CLOSE),
    (45, 0, None), (6, 10, None),  # the edges give no advice
    (5, 10, WEAK), (5, 0, None),  # weak with nothing to remove: it's just far away
    (20, 30, None),
])
def test_advice_by_strength_and_attenuator(over_noise, attenuator, advice):
    assert feed(Coach(), r(over_noise, attenuator)) == advice


def test_one_odd_reading_doesnt_change_the_advice():
    coach = Coach()
    feed(coach, r(50))
    assert coach.update(r(10)) == STRONG  # the median of the last second is still strong


def test_no_advice_until_a_second_of_readings():
    assert feed(Coach(), r(50), WINDOW - 1) is None


def test_no_advice_while_the_fox_is_off_the_air():
    coach = Coach()
    feed(coach, r(2, attenuator_db=30))
    assert coach.update(r(2, attenuator_db=30), fox_off=True) is None
    assert coach.update(r(2, attenuator_db=30)) is None  # the gap's noise was dropped: starts over


def test_clear_starts_over_after_a_settings_change():
    coach = Coach()
    feed(coach, r(50))
    coach.clear()
    assert coach.update(r(50)) is None
