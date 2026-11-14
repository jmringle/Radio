"""SWR (standing wave ratio): how well an antenna's feedpoint impedance matches the feed line.

1.0 is a perfect match; the higher it is, the more power is reflected back toward the radio.
"""

import cmath
import math


def swr(z: complex, z0: float = 50.0) -> float:
    """SWR of a load `z` ohms (resistance + j reactance) on a line of `z0` ohms.

    Infinite for a load with no resistance (a short or a pure reactance), which takes no power.
    """
    z = complex(z)
    if not (cmath.isfinite(z) and math.isfinite(z0)):
        raise ValueError(f"Impedance must be a finite number, got {z} on {z0} ohms")
    if z0 <= 0:
        raise ValueError(f"Line impedance must be above 0 ohms, got {z0}")
    if z.real < 0:
        raise ValueError(f"Resistance can't be negative for an antenna, got {z.real} ohms")
    gamma = abs((z - z0) / (z + z0))  # reflection coefficient: the fraction of voltage sent back
    if gamma >= 1:
        return math.inf
    return (1 + gamma) / (1 - gamma)
