"""S21: how much of the signal sent out of CH0 arrives at CH1, as through loss in dB."""

import math

import pytest

from dipstick.s21 import through


@pytest.mark.parametrize("s21, loss_db", [
    (1, 0.0),                # a perfect thru: everything arrives
    (0.5, 6.0206),           # half the voltage: about 6 dB
    (0.1j, 20.0),            # a tenth, whatever the phase: 20 dB
    (-0.01, 40.0),
])
def test_loss_is_minus_20_log_of_the_size(s21, loss_db):
    assert through(7_000_000, complex(s21)).loss_db == pytest.approx(loss_db, abs=1e-4)


def test_nothing_arriving_is_infinite_loss():
    assert through(7_000_000, 0j).loss_db == math.inf


def test_a_little_over_1_is_noise_and_reads_as_a_small_gain():
    assert through(7_000_000, 1.02 + 0j).loss_db == pytest.approx(-0.172, abs=1e-3)


@pytest.mark.parametrize("s21", [1.06, 2j, complex(math.inf, 0), complex(math.nan, 0)])
def test_more_out_than_in_or_not_a_number_is_refused(s21):
    with pytest.raises(ValueError, match="7000000 Hz"):
        through(7_000_000, s21)
