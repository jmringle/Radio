"""dipstick BAND: sweep an antenna across one amateur band and explain what the NanoVNA measured.

Exit codes: 0 measured (whatever the antenna's SWR), 2 the measurement couldn't be made (no
NanoVNA, a device problem) or the command was used wrongly.
"""

import argparse
import math
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from serial.tools import list_ports

from dipstick.analysis import summarize
from dipstick.cable import MAX_LENGTH_M, analyze, sweep_for
from dipstick.bands import BANDS, band_range
from dipstick.device import DeviceError, NanoVNA, find_port
from dipstick.plots import smith_svg, swr_svg
from dipstick.report import cable_report, report
from dipstick.scan import MAX_POINTS, scan

_MHZ = re.compile(r"[0-9]+(\.[0-9]{1,6})?")
_LENGTH = re.compile(r"([0-9]+(\.[0-9]+)?) ?(ft|m)?")
_VF = re.compile(r"[0-9]*\.?[0-9]+")
FOOT = 0.3048


def connect(port: str | None) -> NanoVNA:
    return NanoVNA.open(port or find_port(list_ports.comports()))


def main(argv: list[str] | None = None, connect=connect) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["cable"]:
        return _cable(argv[1:], connect)
    parser = argparse.ArgumentParser(
        prog="dipstick", description="Sweep an antenna across one amateur band and explain the NanoVNA's readings.",
        epilog="To check a coax cable instead: dipstick cable --help")
    parser.add_argument("band", help=f"one of: {', '.join(BANDS)}")
    parser.add_argument("--target", metavar="MHZ", help="frequency to trim for, e.g. 7.074 (default: the band's middle)")
    parser.add_argument("--points", type=int, default=MAX_POINTS, help=f"2 to {MAX_POINTS} (default {MAX_POINTS})")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    parser.add_argument("--out", type=Path, default=Path("output"), help="folder for the SVG plots (default: output)")
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
        print(f"\nPlots: {', '.join(str(p) for p in _save_plots(readings, args.band, args.out))}")
        return 0
    except (DeviceError, ValueError, OSError) as error:
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


def _save_plots(readings, band: str, folder: Path) -> list[Path]:
    """File names are made here from the band (already checked against the band list) and the
    time, never from anything typed, so they can't point outside the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = [folder / f"{band}-{stamp}-swr.svg", folder / f"{band}-{stamp}-smith.svg"]
    paths[0].write_text(swr_svg(readings, band), encoding="utf-8")
    paths[1].write_text(smith_svg(readings), encoding="utf-8")
    return paths


def _cable(argv: list[str], connect) -> int:
    parser = argparse.ArgumentParser(
        prog="dipstick cable",
        description="Measure a coax cable's length (or velocity factor) and loss, with its far end open or shorted.")
    parser.add_argument("--no-antenna", action="store_true",
                        help="confirm nothing that radiates is connected: this sweeps far outside the ham bands")
    parser.add_argument("--vf", help="the cable's velocity factor, e.g. 0.66 (gives the length)")
    parser.add_argument("--length", help="the cable's known length, e.g. 15.2 or 50ft (gives the velocity factor)")
    parser.add_argument("--max-length", default="50", help="longest cable to plan the sweep for (default 50 m)")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    args = parser.parse_args(argv)
    try:
        if not args.no_antenna:
            raise ValueError("dipstick cable sweeps 1 to 200 MHz, outside the ham bands. Disconnect any antenna, "
                             "leave the cable's far end open or shorted, and run again with --no-antenna.")
        if (args.vf is None) == (args.length is None):
            raise ValueError("Give --vf or --length (one of them)")
        vf = _vf(args.vf) if args.vf is not None else None
        length = _length(args.length, "--length") if args.length is not None else None
        max_length = _length(args.max_length, "--max-length")
        start, stop, points = sweep_for(max_length_m=max_length, vf=vf)
        nano = connect(args.port)
        try:
            readings = scan(nano, start, stop, points, no_antenna=True)
        finally:
            nano.close()
        print(cable_report(analyze(readings, vf=vf, length_m=length), start, stop, points, max_length), end="")
        return 0
    except (DeviceError, ValueError) as error:
        print(f"dipstick: {error}", file=sys.stderr)
        return 2


def _vf(text: str) -> float:
    vf = float(text) if _VF.fullmatch(text) else math.nan
    if not 0 < vf <= 1:  # also false for nan
        raise ValueError(f"--vf must be a velocity factor above 0 and at most 1, like 0.66; got {text!r}")
    return vf


def _length(text: str, option: str) -> float:
    match = _LENGTH.fullmatch(text.strip())
    if not match:
        raise ValueError(f"{option} must be a length like 15.2 (meters) or 50ft, got {text!r}")
    meters = float(match.group(1)) * (FOOT if match.group(3) == "ft" else 1)
    if option == "--length" and not 0 < meters <= MAX_LENGTH_M:
        raise ValueError(f"{option} must be above 0 and at most {MAX_LENGTH_M} m, got {text!r}")
    return meters
