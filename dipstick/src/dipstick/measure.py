"""One band measurement, start to finish: check the request, sweep, summarize, explain, draw.

The command and the app both call this, so they can't drift apart. Everything that can be
checked without the NanoVNA is checked before connecting to it.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from dipstick.analysis import summarize
from dipstick.bands import band_containing, band_range
from dipstick.plots import smith_svg, swr_svg
from dipstick.report import report
from dipstick.s11 import Reading
from dipstick.scan import MAX_POINTS, scan

_MHZ = re.compile(r"[0-9]+(\.[0-9]{1,6})?")


@dataclass(frozen=True)
class BandMeasurement:
    band: str
    readings: list[Reading]
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


def measure_band(band: str, target: str | None, points: int, connect, port: str | None = None) -> BandMeasurement:
    start, stop, target_hz = check_band(band, target, points)
    nano = connect(port)
    try:
        readings = scan(nano, start, stop, points)
    finally:
        nano.close()
    return BandMeasurement(band, readings, report(summarize(readings, target_hz=target_hz), band),
                           swr_svg(readings, band), smith_svg(readings))


def _target(text: str | None, start: int, stop: int) -> int:
    if text is None or not text.strip():
        return (start + stop) // 2
    text = text.strip()
    hz = _mhz(text)
    if not start <= hz <= stop:
        raise ValueError(f"The target {text} MHz is outside the band ({start / 1e6:g}-{stop / 1e6:g} MHz)")
    return hz


def _mhz(text: str) -> int:
    if not _MHZ.fullmatch(text):
        raise ValueError(f"The target must be a frequency in MHz like 7.074, got {text!r}")
    return int(Decimal(text) * 1_000_000)
