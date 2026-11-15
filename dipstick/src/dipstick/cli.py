"""dipstick BAND: sweep an antenna across one amateur band and explain what the NanoVNA measured.

Exit codes: 0 measured (whatever the antenna's SWR), 2 the measurement couldn't be made (no
NanoVNA, a device problem) or the command was used wrongly.
"""

import argparse
import re
import sys
from decimal import Decimal

from serial.tools import list_ports

from dipstick.analysis import summarize
from dipstick.bands import BANDS, band_range
from dipstick.device import DeviceError, NanoVNA, find_port
from dipstick.report import report
from dipstick.scan import MAX_POINTS, scan

_MHZ = re.compile(r"[0-9]+(\.[0-9]{1,6})?")


def connect(port: str | None) -> NanoVNA:
    return NanoVNA.open(port or find_port(list_ports.comports()))


def main(argv: list[str] | None = None, connect=connect) -> int:
    parser = argparse.ArgumentParser(
        prog="dipstick", description="Sweep an antenna across one amateur band and explain the NanoVNA's readings.")
    parser.add_argument("band", help=f"one of: {', '.join(BANDS)}")
    parser.add_argument("--target", metavar="MHZ", help="frequency to trim for, e.g. 7.074 (default: the band's middle)")
    parser.add_argument("--points", type=int, default=MAX_POINTS, help=f"2 to {MAX_POINTS} (default {MAX_POINTS})")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    args = parser.parse_args(argv)
    try:
        # Everything that can be checked without the NanoVNA is checked first.
        start, stop = band_range(args.band)
        target = _target(args.target, start, stop)
        if not 2 <= args.points <= MAX_POINTS:
            raise ValueError(f"--points must be 2 to {MAX_POINTS}, got {args.points}")
        nano = connect(args.port)
        try:
            readings = scan(nano, start, stop, args.points)
        finally:
            nano.close()
        print(report(summarize(readings, target_hz=target), args.band), end="")
        return 0
    except (DeviceError, ValueError) as error:
        print(f"dipstick: {error}", file=sys.stderr)
        return 2


def _target(text: str | None, start: int, stop: int) -> int:
    if text is None:
        return (start + stop) // 2
    if not _MHZ.fullmatch(text):
        raise ValueError(f"--target must be a frequency in MHz like 7.074, got {text!r}")
    hz = int(Decimal(text) * 1_000_000)
    if not start <= hz <= stop:
        raise ValueError(f"--target {text} MHz is outside the band ({start / 1e6:g}-{stop / 1e6:g} MHz)")
    return hz
