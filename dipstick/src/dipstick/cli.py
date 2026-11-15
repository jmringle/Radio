"""dipstick BAND: sweep an antenna across one amateur band and explain what the NanoVNA measured.

Exit codes: 0 measured (whatever the antenna's SWR), 2 the measurement couldn't be made (no
NanoVNA, a device problem) or the command was used wrongly.
"""

import argparse
import math
import re
import sys
from datetime import datetime
from pathlib import Path

from serial.tools import list_ports

from dipstick.bands import BANDS
from dipstick.cable import MAX_LENGTH_M, analyze, sweep_for
from dipstick.device import DeviceError, NanoVNA, find_port
from dipstick.measure import BandMeasurement, measure_band
from dipstick.report import cable_report
from dipstick.scan import MAX_POINTS, scan

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
        measured = measure_band(args.band, args.target, args.points, connect, args.port)
        print(measured.report, end="")
        print(f"\nPlots: {', '.join(str(p) for p in _save_plots(measured, args.out))}")
        return 0
    except (DeviceError, ValueError, OSError) as error:
        print(f"dipstick: {error}", file=sys.stderr)
        return 2


def _save_plots(measured: BandMeasurement, folder: Path) -> list[Path]:
    """File names are made here from the band (already checked against the band list) and the
    time, never from anything typed, so they can't point outside the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    paths = [folder / f"{measured.band}-{stamp}-swr.svg", folder / f"{measured.band}-{stamp}-smith.svg"]
    paths[0].write_text(measured.swr_svg, encoding="utf-8")
    paths[1].write_text(measured.smith_svg, encoding="utf-8")
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
