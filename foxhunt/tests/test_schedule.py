"""The fox schedule learner (README: acceptance criteria, phase 2b). Times are made up and fed
directly, 10 readings a second."""
import pytest

from foxhunt.schedule import Schedule

STEP = 0.1


def run(schedule, pattern, start=0.0, on_db=20.0, off_db=0.0):
    """Feed (on_s, off_s) pairs; returns the time after the last reading."""
    t = start
    for on_s, off_s in pattern:
        for seconds, db in ((on_s, on_db), (off_s, off_db)):
            for _ in range(round(seconds / STEP)):
                schedule.update(t, db, False)
                t = round(t + STEP, 6)
    return t


def test_a_regular_fox_is_learned_and_the_next_transmission_predicted():
    s = Schedule()
    t = run(s, [(30, 90)] * 3)  # on 30 s every 2 min; now 90 s into the third gap
    assert s.period == pytest.approx(120) and s.status(t)["duration_s"] == pytest.approx(30)
    t = run(s, [(30, 20)], start=t)  # a fourth: 20 s into its gap
    status = s.status(t)
    assert status["next_in_s"] == pytest.approx(70, abs=0.5)
    assert status["text"] == "Next transmission in about 70 s (every 120 s, on for 30 s)."
    assert s.fox_off


def test_it_needs_three_transmissions():
    s = Schedule()
    t = run(s, [(30, 90), (30, 10)])
    assert s.period is None
    assert "learning its pattern (needs 3 transmissions)" in s.status(t)["text"]


def test_irregular_timing_isnt_called_a_pattern():
    s = Schedule()
    t = run(s, [(10, 20), (10, 80), (10, 5)])  # intervals 30 s and 90 s
    assert s.period is None and "irregular" in s.status(t)["text"]


def test_small_timing_wobble_still_counts_as_regular():
    s = Schedule()
    run(s, [(30, 90), (30, 100), (30, 5)])  # 120 s then 130 s: within 20%
    assert s.period == pytest.approx(125)


def test_while_on_it_says_how_long():
    s = Schedule()
    t = run(s, [(30, 90)] * 3 + [(12, 0)])
    assert s.status(t)["text"] == "Fox on the air for 12 s (usually about 30 s)."
    assert not s.fox_off


def test_due_then_overdue():
    s = Schedule()
    t = run(s, [(30, 90)] * 3)
    assert "due now" in s.status(t + 31)["text"]  # due at t (the gap ends), so 31 s late: under half a period
    assert s.status(t + 100)["text"].startswith("Overdue by 100 s")  # more than half a period (60 s)


def test_a_changed_pattern_is_relearned():
    s = Schedule()
    t = run(s, [(30, 90)] * 3)
    run(s, [(10, 50)] * 6, start=t)  # now every 60 s; only the last few transmissions count
    assert s.period == pytest.approx(60)


def test_a_short_noise_spike_isnt_a_transmission():
    s = Schedule()
    run(s, [(0.2, 5)])  # two readings over the threshold
    assert not s.heard and s.status(10)["text"] == "No transmission heard yet."


def test_a_signal_hovering_between_the_thresholds_doesnt_flicker():
    s = Schedule()
    run(s, [(1, 0)], on_db=20)
    run(s, [(5, 0)], start=1, on_db=4)  # 4 dB: under "on" (6) but over "off" (3), so it stays on
    assert s.on and len(s.starts) == 1


def test_a_weak_fox_never_heard_isnt_off():
    s = Schedule()
    run(s, [(0, 30)])
    assert not s.fox_off  # nothing heard: it may just be weak, so don't block bearings or coaching


def test_overload_counts_as_on():
    s = Schedule()
    for i in range(5):
        s.update(i * STEP, 0.0, True)
    assert s.on


def test_the_start_time_is_when_it_first_came_on_not_when_it_was_confirmed():
    s = Schedule()
    run(s, [(0, 1), (2, 0)])
    assert s.starts[0] == pytest.approx(1.0)


def test_clear_forgets_the_fox():
    s = Schedule()
    run(s, [(30, 90)] * 3)
    s.clear()
    assert not s.heard and s.period is None
