"""What the NanoVNA measures (S11, the reflection coefficient) turned into what you read:
impedance, SWR and return loss. Expected values are worked by hand from the definitions,
not computed by the code's own formulas."""

import math

import pytest

from dipstick.s11 import Reading, reading


@pytest.mark.parametrize("gamma, z, swr, return_loss", [
    (0, 50, 1.0, math.inf),              # perfect match: nothing comes back
    (1 / 3, 100, 2.0, 9.54),             # 100 ohms: a third of the voltage comes back
    (-1 / 3, 25, 2.0, 9.54),             # 25 ohms: same SWR, opposite side of the Smith chart
    (0.5, 150, 3.0, 6.02),
    (0.2j, 46.15 + 19.23j, 1.5, 13.98),  # (1 + 0.2j) / (1 - 0.2j) x 50, worked by hand
])
def test_known_reflections(gamma, z, swr, return_loss):
    r = reading(14_000_000, complex(gamma))
    assert r.impedance == pytest.approx(z, abs=0.01)
    assert r.swr == pytest.approx(swr, abs=0.005)
    assert r.return_loss_db == pytest.approx(return_loss, abs=0.01)


def test_an_open_or_short_reflects_everything():
    for gamma in (1, -1, 1j):
        assert reading(7_000_000, complex(gamma)).swr == math.inf
    assert reading(7_000_000, complex(-1)).impedance == 0  # a short
    assert reading(7_000_000, complex(1)).impedance == complex(math.inf, 0)  # an open


def test_noise_slightly_above_one_is_treated_as_total_reflection():
    # An uncalibrated or noisy NanoVNA can report |S11| a hair over 1 on an open.
    r = reading(7_000_000, complex(1.02, 0))
    assert (r.swr, r.return_loss_db) == (math.inf, 0)


def test_reading_keeps_the_frequency():
    assert reading(7_074_000, complex(0)) == Reading(7_074_000, complex(0), 50, 1.0, math.inf)


@pytest.mark.parametrize("gamma", [complex(math.nan, 0), complex(0, math.inf), complex(5, 0)])
def test_impossible_measurements_are_refused(gamma):
    # Way over 1 isn't noise: a passive antenna can't reflect more than it's sent.
    with pytest.raises(ValueError):
        reading(7_000_000, gamma)
