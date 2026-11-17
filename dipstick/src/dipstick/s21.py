"""From S21 to through loss.

S21 is what the NanoVNA measures on its CH1 port: the fraction of the signal sent out of CH0 that
arrives at CH1 (as a complex number, size and phase). With something in between (a choke, a balun,
a cable) its size says how much got through: through loss in dB is -20 log10 |S21|. It means
something only after a calibration that included the thru step (Calibrate, Both ports).
"""

import cmath
import math
from dataclasses import dataclass

from dipstick.s11 import NOISE


@dataclass(frozen=True)
class Through:
    hz: int
    s21: complex
    loss_db: float  # 0 is everything arriving; inf is nothing; slightly below 0 is noise


def through(hz: int, s21: complex) -> Through:
    if not cmath.isfinite(s21):
        raise ValueError(f"S21 at {hz} Hz isn't a finite number: {s21}")
    size = abs(s21)
    if size > NOISE:
        raise ValueError(f"S21 at {hz} Hz is {size:.2f}; above 1 means more arrived at CH1 than CH0 sent "
                         "(calibrate the NanoVNA with Both ports)")
    return Through(hz, s21, math.inf if size == 0 else -20 * math.log10(size))
