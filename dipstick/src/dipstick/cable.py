"""Cable checks: length (or velocity factor), what's at the far end, and loss.

With the far end open or shorted, the whole signal bounces back from it. The echo's phase
turns faster with frequency the longer the round trip takes:

    S11 phase = start - 4 pi f x delay,  delay = length / (velocity factor x c)

so a straight line fitted to phase against frequency gives the delay from its slope, and what's
at the end from where the line starts at 0 Hz (0 = open, half a turn = short). The echo also
comes back weaker by the cable's loss there and back, so one-way loss = return loss / 2.
"""

import cmath
import math
from dataclasses import dataclass

C = 299_792_458.0  # m/s
START_HZ = 1_000_000
MAX_STOP_HZ = 200_000_000
POINTS = 101
MARGIN = 0.8  # phase turns at most 0.8 x pi per step on the longest cable planned for
SLOWEST_VF = 0.5  # planning a sweep without a known velocity factor: assume it could be this slow
MAX_LENGTH_M = 2000
LOSS_HZ = (7_000_000, 14_000_000, 28_000_000, 50_000_000)
MATCHED = 0.5  # |S11| below this at the lowest frequency: nothing much reflects at the end
CLEAN_RMS = 0.2  # radians: phase further than this from a straight line isn't a clean open or short


@dataclass(frozen=True)
class CableResult:
    end: str  # "open", "short" or "matched" (nothing reflects: a load or an antenna)
    length_m: float | None
    vf: float | None
    loss_db: dict[int, float]  # one-way loss at LOSS_HZ inside the sweep
    clean: bool  # phase follows a straight line, as a plain cable with an open or short does
    vf_given: bool  # True: the length was measured from a given velocity factor; False: the reverse


def sweep_for(max_length_m: float, vf: float | None) -> tuple[int, int, int]:
    """Start, stop and points for a sweep that measures cables up to `max_length_m` without
    aliasing (a long cable looking short because the phase turns more than half a turn per step)."""
    if not (math.isfinite(max_length_m) and 0 < max_length_m <= MAX_LENGTH_M):
        raise ValueError(f"--max-length must be above 0 and at most {MAX_LENGTH_M} m, got {max_length_m}")
    slowest = vf if vf is not None else SLOWEST_VF
    step = MARGIN * slowest * C / (4 * max_length_m)
    return START_HZ, min(round(START_HZ + (POINTS - 1) * step), MAX_STOP_HZ), POINTS


def analyze(readings, vf: float | None = None, length_m: float | None = None) -> CableResult:
    if (vf is None) == (length_m is None):
        raise ValueError("Give the cable's velocity factor or its length, not both")
    if vf is not None and not (math.isfinite(vf) and 0 < vf <= 1):
        raise ValueError(f"Velocity factor must be above 0 and at most 1, got {vf}")
    if length_m is not None and not (math.isfinite(length_m) and 0 < length_m <= MAX_LENGTH_M):
        raise ValueError(f"Length must be above 0 and at most {MAX_LENGTH_M} m, got {length_m}")
    if abs(readings[0].s11) < MATCHED:
        return CableResult("matched", None, None, {}, False, vf is not None)

    hz = [r.hz for r in readings]
    phase = _unwrap([cmath.phase(r.s11) for r in readings])
    slope, intercept, rms = _fit(hz, phase)
    delay = -slope / (4 * math.pi)  # seconds, one way
    start_phase = math.remainder(intercept, math.tau)  # wrapped to -pi..pi
    end = "open" if abs(start_phase) < math.pi / 2 else "short"
    clean = rms < CLEAN_RMS and delay > 0
    if delay <= 0:  # impossible for a real cable: aliased or not a cable at all
        found_length, found_vf = None, None
    elif vf is not None:
        found_length, found_vf = delay * vf * C, vf
    else:
        found_length, found_vf = length_m, length_m / (delay * C)
    step = (hz[-1] - hz[0]) / (len(hz) - 1)
    loss = {}
    for f in LOSS_HZ:
        if hz[0] <= f <= hz[-1]:
            nearest = min(readings, key=lambda r: abs(r.hz - f))
            if abs(nearest.hz - f) <= step:
                loss[f] = nearest.return_loss_db / 2
    return CableResult(end, found_length, found_vf, loss, clean, vf is not None)


def _unwrap(phases: list[float]) -> list[float]:
    """Phase only reads -pi..pi; add whole turns back wherever it jumps by more than half a turn."""
    out = [phases[0]]
    for p in phases[1:]:
        step = math.remainder(p - out[-1], math.tau)  # the smallest turn from the last point
        out.append(out[-1] + step)
    return out


def _fit(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """Least-squares straight line y = slope x + intercept, and the RMS distance from it."""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    intercept = my - slope * mx
    rms = math.sqrt(sum((b - (slope * a + intercept)) ** 2 for a, b in zip(x, y)) / n)
    return slope, intercept, rms
