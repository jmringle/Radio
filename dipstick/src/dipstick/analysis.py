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
THREE_TO_ONE = 3.0  # what most radios' built-in tuners reach (see report.py's tuner words)
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
    at_target: Reading  # the reading nearest the target: where you'll operate
    three_to_one: tuple[float, float] | None  # as two_to_one, for SWR <= 3 (most built-in tuners)
    three_to_one_reaches_low: bool
    three_to_one_reaches_high: bool


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
    two_to_one, reaches_low, reaches_high = (None, False, False) if nothing else _around(readings, best, TWO_TO_ONE)
    three, three_low, three_high = (None, False, False) if nothing else _around(readings, best, THREE_TO_ONE)
    trim = None if nothing else (best.hz / target_hz - 1) * 100
    worst = max(readings, key=lambda r: r.swr)
    flat = not nothing and best.swr > TWO_TO_ONE and worst.swr < best.swr * FLAT_RATIO
    return Summary(low, middle, high, best, edge, two_to_one, reaches_low, reaches_high,
                   _zero_reactance(readings), target_hz, trim, nothing, worst, flat, len(readings),
                   min(readings, key=lambda r: abs(r.hz - target_hz)), three, three_low, three_high)


def spans(readings: list[Reading], limit: float) -> list[tuple[float, float]]:
    """Every stretch of the sweep where SWR is at or under `limit`, as (low, high) Hz. Ends between
    two readings are interpolated; a stretch that starts or ends at the sweep's edge ends exactly there."""
    found, start = [], None
    for i, r in enumerate(readings):
        inside = r.swr <= limit
        if inside and start is None:
            start = r.hz if i == 0 else _crossing(r, readings[i - 1], limit)
        elif not inside and start is not None:
            found.append((start, _crossing(readings[i - 1], r, limit)))
            start = None
    if start is not None:
        found.append((start, readings[-1].hz))
    return found


def _around(readings: list[Reading], best: Reading, limit: float) -> tuple[tuple[float, float] | None, bool, bool]:
    """The stretch under `limit` that holds the best match, and whether it runs into each edge."""
    for low, high in spans(readings, limit):
        if low <= best.hz <= high:
            return (low, high), low == readings[0].hz, high == readings[-1].hz
    return None, False, False


def _crossing(inside: Reading, outside: Reading, limit: float) -> float:
    """Where SWR passes `limit` between a reading at or under it and its neighbor over it (straight line)."""
    if math.isinf(outside.swr):
        return inside.hz  # can't draw a line to infinity; the last good point is the safe answer
    fraction = (limit - inside.swr) / (outside.swr - inside.swr)
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
