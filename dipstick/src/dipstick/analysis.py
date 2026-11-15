"""The numbers in a band report.

Trim advice comes from where SWR is lowest, not from where the reactance X crosses zero. On a
low-loss coax, SWR is the same at both ends of the cable, so the lowest-SWR frequency is the
antenna's own best match however long the coax is. Impedance (R + jX) changes along the coax,
so X = 0 at the radio's end is usually not where the antenna itself is resonant.
"""

import math
from dataclasses import dataclass

from dipstick.s11 import Reading

NOTHING_SWR = 10  # best SWR above this everywhere: nothing connected, or something badly wrong
TWO_TO_ONE = 2.0
# Highest SWR in the band under 1.25 times the lowest, with the lowest above 2: no dip to move.
# A dipole even 10% off frequency rises far more than that across a band.
FLAT_RATIO = 1.25


@dataclass(frozen=True)
class Summary:
    low: Reading  # the first reading (the band's low edge)
    middle: Reading  # the reading closest to the middle
    high: Reading  # the last reading
    best: Reading  # lowest SWR
    best_at_edge: str | None  # "low" or "high" if the lowest SWR is at an edge: the real best is beyond it
    two_to_one: tuple[float, float] | None  # Hz range around the best where SWR <= 2, or None
    two_to_one_reaches_low: bool  # the 2:1 range runs into the low edge (it may go further)
    two_to_one_reaches_high: bool
    zero_reactance: list[float]  # Hz where X crosses 0, at the radio's end of the coax
    target_hz: int
    trim_percent: float | None  # + lengthen, - shorten, to move the best match to the target
    nothing_connected: bool
    worst: Reading  # highest SWR
    flat: bool  # SWR high and nearly the same across the band: no clear dip, so no trim advice
    points: int


def summarize(readings: list[Reading], target_hz: int) -> Summary:
    if len(readings) < 2:
        raise ValueError("A summary needs at least 2 readings")
    low, high = readings[0], readings[-1]
    if not low.hz <= target_hz <= high.hz:
        raise ValueError(f"The target {target_hz} Hz is outside the sweep ({low.hz}-{high.hz} Hz)")
    middle_hz = (low.hz + high.hz) / 2
    middle = min(readings, key=lambda r: abs(r.hz - middle_hz))
    best_index = min(range(len(readings)), key=lambda i: readings[i].swr)
    best = readings[best_index]
    nothing = best.swr > NOTHING_SWR
    edge = "low" if best_index == 0 else "high" if best_index == len(readings) - 1 else None
    two_to_one, reaches_low, reaches_high = (None, False, False) if nothing else _two_to_one(readings, best_index)
    trim = None if nothing else (best.hz / target_hz - 1) * 100
    worst = max(readings, key=lambda r: r.swr)
    flat = not nothing and best.swr > TWO_TO_ONE and worst.swr < best.swr * FLAT_RATIO
    return Summary(low, middle, high, best, edge, two_to_one, reaches_low, reaches_high,
                   _zero_reactance(readings), target_hz, trim, nothing, worst, flat, len(readings))


def _two_to_one(readings: list[Reading], best: int) -> tuple[tuple[float, float] | None, bool, bool]:
    """Walk out from the best reading both ways to where SWR goes over 2, interpolating the crossing."""
    if readings[best].swr > TWO_TO_ONE:
        return None, False, False
    lo = best
    while lo > 0 and readings[lo - 1].swr <= TWO_TO_ONE:
        lo -= 1
    hi = best
    while hi < len(readings) - 1 and readings[hi + 1].swr <= TWO_TO_ONE:
        hi += 1
    low_hz = readings[0].hz if lo == 0 else _crossing(readings[lo], readings[lo - 1])
    high_hz = readings[-1].hz if hi == len(readings) - 1 else _crossing(readings[hi], readings[hi + 1])
    return (low_hz, high_hz), lo == 0, hi == len(readings) - 1


def _crossing(inside: Reading, outside: Reading) -> float:
    """Where SWR passes 2 between a reading at or under 2 and its neighbor over 2 (straight line)."""
    if math.isinf(outside.swr):
        return inside.hz  # can't draw a line to infinity; the last good point is the safe answer
    fraction = (TWO_TO_ONE - inside.swr) / (outside.swr - inside.swr)
    return inside.hz + fraction * (outside.hz - inside.hz)


def _zero_reactance(readings: list[Reading]) -> list[float]:
    crossings = []
    for a, b in zip(readings, readings[1:]):
        xa, xb = a.impedance.imag, b.impedance.imag
        if not (math.isfinite(xa) and math.isfinite(xb)):
            continue
        if xa == 0:
            crossings.append(float(a.hz))
        elif xa * xb < 0:
            crossings.append(a.hz + xa / (xa - xb) * (b.hz - a.hz))
    if readings[-1].impedance.imag == 0:
        crossings.append(float(readings[-1].hz))
    return crossings
