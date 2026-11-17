"""The through-loss test: one item between CH0 and CH1 (direct), or two identical transformers back
to back. Loss in dB is -20 log10 |S21| (s21.py); readings here are made up from a loss in dB, so each
expected value is the one the reading was made from."""

import math

import pytest

from dipstick.balun import POINTS, START_HZ, STOP_HZ, analyze_loss
from dipstick.report import loss_report
from dipstick.s21 import through


def sweep(db_at):
    """S21 over the 1.8-54 MHz sweep with the total loss in dB `db_at(hz)` gives (inf: nothing through)."""
    out = []
    for i in range(POINTS):
        hz = round(START_HZ + i * (STOP_HZ - START_HZ) / (POINTS - 1))
        db = db_at(hz)
        out.append(through(hz, 0j if db == math.inf else complex(10 ** (-db / 20))))
    return out


def test_direct_loss_is_the_whole_reading_at_each_band_middle():
    result = analyze_loss(sweep(lambda hz: 0.2 if hz < 20e6 else 0.6), "direct")
    assert [b.band for b in result.bands] == ["160m", "80m", "40m", "30m", "20m", "17m", "15m",
                                              "12m", "10m", "6m"]
    forty = result.bands[2]
    assert forty.hz == 7_020_000 and forty.loss_db == pytest.approx(0.2) and forty.status == "loss"
    assert result.bands[-1].loss_db == pytest.approx(0.6)


def test_back_to_back_gives_each_transformer_half():
    result = analyze_loss(sweep(lambda hz: 1.0), "back-to-back")
    assert all(b.loss_db == pytest.approx(0.5) for b in result.bands)


@pytest.mark.parametrize("total_db, status", [
    (0.0, "loss"),      # nothing lost
    (-0.09, "loss"),    # just inside the 0.1 dB tolerance: noise around a near-lossless item
    (-0.11, "gain"),    # more than noise above 0 dB: the thru calibration is off
    (40.0, "loss"),     # the deepest this setup measures (the choke test's limit too)
    (40.1, "beyond"),
])
def test_status_boundaries(total_db, status):
    result = analyze_loss(sweep(lambda hz: total_db if 6e6 < hz < 8e6 else 0.5), "direct")
    assert result.bands[2].status == status


def test_the_limits_are_on_the_pairs_total_not_each_half():
    # Back to back, 0.08 dB of gain in total is noise, and 41 dB in total is beyond, though each half isn't.
    result = analyze_loss(sweep(lambda hz: -0.08 if hz < 2e6 else 41 if hz < 4e6 else 0.5), "back-to-back")
    assert [b.status for b in result.bands[:2]] == ["loss", "beyond"]


def test_nothing_arriving_anywhere_is_an_error():
    with pytest.raises(ValueError, match="between CH0 and CH1"):
        analyze_loss(sweep(lambda hz: math.inf), "direct")


@pytest.mark.parametrize("connection", ["", "Direct", "back to back", None, True])
def test_only_the_two_connections_are_accepted(connection):
    with pytest.raises(ValueError, match="direct or back-to-back"):
        analyze_loss(sweep(lambda hz: 0.5), connection)


# --- the report in plain words ------------------------------------------------------------------


def rising(connection="direct"):
    """0.1 dB on 160 m rising to 0.5 dB on 6 m (in total): a typical ferrite balun's shape."""
    return analyze_loss(sweep(lambda hz: 0.1 if hz < 2e6 else 0.5 if hz > 50e6 else 0.3), connection)


def test_report_answer_first_most_and_least():
    first = loss_report(rising(), calibrated=True, thru=True).splitlines()[0]
    assert first == "Through loss, direct: most 0.50 dB on 6m, least 0.10 dB on 160m."
    first = loss_report(rising("back-to-back"), calibrated=True, thru=True).splitlines()[0]
    assert first == "Through loss, each of two transformers back to back: most 0.25 dB on 6m, least 0.05 dB on 160m."


def test_report_band_lines_give_db_and_the_share_of_power_lost():
    text = loss_report(rising(), calibrated=True, thru=True)
    assert "  40m     7.020 MHz  0.30 dB  (7% of the power doesn't arrive)" in text
    assert "  160m    1.800 MHz  0.10 dB  (2% of the power doesn't arrive)" in text


def test_report_odd_readings_say_what_they_mean():
    result = analyze_loss(sweep(lambda hz: -0.05 if hz < 2e6 else 50 if hz < 4e6 else -0.3 if hz < 8e6
                                else 0.3), "direct")
    text = loss_report(result, calibrated=True, thru=True)
    assert "  160m    1.800 MHz  about 0 dB: no loss this setup can measure" in text
    assert "  80m     3.888 MHz  over 40 dB: almost nothing arrives" in text
    assert "  40m     7.020 MHz  reads 0.30 dB of gain, which a passive item can't have: recheck the thru calibration" in text


def test_report_explains_db_and_the_connection():
    direct = loss_report(rising(), calibrated=True, thru=True)
    assert "3 dB is half the power" in direct and "1:1 balun" in direct
    pair = loss_report(rising("back-to-back"), calibrated=True, thru=True)
    assert "half the pair's total" in pair and "identical" in pair


def test_report_calibration_notes_match_the_choke_tests():
    assert "Both ports" not in loss_report(rising(), calibrated=True, thru=True)
    assert "HF wide" in loss_report(rising(), calibrated=False, thru=True)
    assert "aren't corrected" in loss_report(rising(), calibrated=True, thru=False)
