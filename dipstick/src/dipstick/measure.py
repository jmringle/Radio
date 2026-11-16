"""One band measurement, start to finish: check the request, sweep, summarize, explain, draw.

The command and the app both call this, so they can't drift apart. Everything that can be
checked without the NanoVNA is checked before connecting to it.
"""

import math
import re
from dataclasses import dataclass
from decimal import Decimal

from dipstick.analysis import Summary, summarize
from dipstick.bands import band_containing, band_range
from dipstick.cable import MAX_LENGTH_M, CableResult, analyze, sweep_for
from dipstick.plots import smith_svg, swr_svg
from dipstick.report import FOOT, cable_report, report
from dipstick.s11 import Reading
from dipstick.scan import MAX_POINTS, scan

_MHZ = re.compile(r"[0-9]+(\.[0-9]{1,6})?")
_LENGTH = re.compile(r'([0-9]*\.?[0-9]+) ?(ft|m|in|inch|inches|")?', re.IGNORECASE)  # ".6" is 0.6 m; 6" is 6 inches; 6FT too
_UNITS = {None: 1, "m": 1, "ft": FOOT, "in": FOOT / 12, "inch": FOOT / 12, "inches": FOOT / 12, '"': FOOT / 12}
_VF = re.compile(r"[0-9]*\.?[0-9]+")

# What each setting is called where the person typed it, so an error names the right thing:
# the command's options, or the app's fields.
COMMAND_NAMES = {"no_antenna": "run again with --no-antenna", "vf": "--vf", "length": "--length", "max_length": "--max-length"}


@dataclass(frozen=True)
class BandMeasurement:
    band: str
    readings: list[Reading]
    target_hz: int
    summary: Summary
    report: str
    swr_svg: str
    smith_svg: str


def band_for_target(target: str | None) -> str:
    """The band to sweep when only a target frequency is given."""
    if target is None or not target.strip():
        raise ValueError("Choose a band, or type a target frequency")
    hz = _mhz(target.strip())
    band = band_containing(hz)
    if band is None:
        raise ValueError(f"{target.strip()} MHz isn't in an amateur band dipstick can sweep")
    return band


def check_band(band: str, target: str | None, points: int) -> tuple[int, int, int]:
    """Start, stop and target in Hz, or ValueError saying what's wrong."""
    start, stop = band_range(band)
    if not 2 <= points <= MAX_POINTS:
        raise ValueError(f"Points must be 2 to {MAX_POINTS}, got {points}")
    return start, stop, _target(target, start, stop)


def measure_band(band: str, target: str | None, points: int, connect, port: str | None = None,
                 calibrated: bool = False) -> BandMeasurement:
    """`calibrated`: the app calibrated in this session, so the report leaves out its reminder."""
    start, stop, target_hz = check_band(band, target, points)
    nano = connect(port)
    try:
        readings = scan(nano, start, stop, points)
    finally:
        nano.close()
    summary = summarize(readings, target_hz=target_hz)
    return BandMeasurement(band, readings, target_hz, summary, report(summary, band, calibrated=calibrated),
                           swr_svg(readings, band, target_hz=target_hz), smith_svg(readings))


@dataclass(frozen=True)
class CableMeasurement:
    readings: list[Reading]
    result: CableResult
    report: str


def measure_cable(no_antenna: bool, vf: str | None, length: str | None, max_length: str, connect,
                  port: str | None = None, names: dict[str, str] = COMMAND_NAMES) -> CableMeasurement:
    """Length (or velocity factor), far end and loss of a coax cable. The sweep goes far outside
    the ham bands, so it runs only when no_antenna is exactly True (T5). Settings arrive as text."""
    if no_antenna is not True:
        raise ValueError("The cable check sweeps 1 to 200 MHz, outside the ham bands. Disconnect any antenna, leave "
                         f"the cable's far end open or shorted, then {names['no_antenna']}.")
    vf, length = _given(vf, names["vf"]), _given(length, names["length"])
    if (vf is None) == (length is None):
        raise ValueError(f"Give {names['vf']} or {names['length']} (one of them)")
    vf = _vf(vf, names["vf"]) if vf is not None else None
    length = _length(length, names["length"]) if length is not None else None
    max_length = _length(_given(max_length, names["max_length"]) or "", names["max_length"])
    start, stop, points = sweep_for(max_length_m=max_length, vf=vf)
    nano = connect(port)
    try:
        readings = scan(nano, start, stop, points, no_antenna=True)
    finally:
        nano.close()
    result = analyze(readings, vf=vf, length_m=length)
    return CableMeasurement(readings, result, cable_report(result, start, stop, points, max_length, names["max_length"]))


def _cut(text: str, limit: int = 40) -> str:
    """Typed text for a message, cut short when someone pastes a wall of it (QA 2026-11-16)."""
    return text if len(text) <= limit else text[:limit] + "…"


def shown(value) -> str:
    """A value echoed in a message, quoted like repr() and cut short if it's long text."""
    return repr(_cut(value)) if isinstance(value, str) else repr(value)


def _given(text, name: str) -> str | None:
    """Text, or None when left empty. The app's page sends text; anything else is refused."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise ValueError(f"{name} must be typed as text, got {shown(text)}")
    return text.strip() or None


def _vf(text: str, name: str) -> float:
    vf = float(text) if _VF.fullmatch(text) else math.nan
    if not 0 < vf <= 1:  # also false for nan
        raise ValueError(f"{name} must be a velocity factor above 0 and at most 1, like 0.66; got {shown(text)}")
    return vf


def _length(text: str, name: str) -> float:
    match = _LENGTH.fullmatch(text)
    if not match:
        raise ValueError(f"{name} must be a length like 15.2 (meters), 50ft or 6in, got {shown(text)}")
    meters = float(match.group(1)) * _UNITS[match.group(2) and match.group(2).lower()]
    if not 0 < meters <= MAX_LENGTH_M:
        raise ValueError(f"{name} must be above 0 and at most {MAX_LENGTH_M} m, got {shown(text)}")
    return meters


def _target(text: str | None, start: int, stop: int) -> int:
    if text is None or not text.strip():
        return (start + stop) // 2
    text = text.strip()
    hz = _mhz(text)
    if not start <= hz <= stop:
        raise ValueError(f"The target {_cut(text)} MHz is outside the band ({start / 1e6:g}-{stop / 1e6:g} MHz)")
    return hz


def _mhz(text: str) -> int:
    if not _MHZ.fullmatch(text):
        raise ValueError(f"The target must be a frequency in MHz like 7.074, got {shown(text)}")
    return int(Decimal(text) * 1_000_000)
