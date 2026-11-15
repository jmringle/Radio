"""From S11 to what you read on the NanoVNA's screen.

S11 is the one thing the NanoVNA measures on its CH0 port: the reflection coefficient, the
fraction of the signal (as a complex number, size and phase) that comes back from whatever is
connected. Everything else it shows (SWR, impedance, return loss, the Smith chart) is S11
redrawn. The Smith chart is literally a plot of S11: the center is 0 (perfect match), the edge
is |S11| = 1 (everything comes back).
"""

import cmath
import math
from dataclasses import dataclass

Z0 = 50.0  # ohms: the NanoVNA's reference, and your coax
NOISE = 1.05  # |S11| up to this is measurement noise on an open or short; beyond it, something's wrong


@dataclass(frozen=True)
class Reading:
    hz: int
    s11: complex
    impedance: complex  # ohms: resistance + j reactance; inf for an open
    swr: float  # 1.0 is a perfect match
    return_loss_db: float  # how far down the reflection is; higher is better, inf for a perfect match


def reading(hz: int, s11: complex) -> Reading:
    if not cmath.isfinite(s11):
        raise ValueError(f"S11 at {hz} Hz isn't a finite number: {s11}")
    size = abs(s11)
    if size > NOISE:
        raise ValueError(f"S11 at {hz} Hz is {size:.2f}; above 1 means more came back than was sent "
                         "(recalibrate the NanoVNA)")
    if size >= 1:
        # An open (s11 = 1) has infinite impedance; anything else on the edge is pure reactance.
        impedance = complex(math.inf, 0) if s11 == 1 else Z0 * (1 + s11) / (1 - s11)
        return Reading(hz, s11, impedance, math.inf, 0.0)
    impedance = Z0 * (1 + s11) / (1 - s11)
    swr = (1 + size) / (1 - size)
    return_loss = math.inf if size == 0 else -20 * math.log10(size)
    return Reading(hz, s11, impedance, swr, return_loss)
