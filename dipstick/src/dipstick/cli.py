"""dipstick BAND: sweep an antenna across one amateur band and explain what the NanoVNA measured.

Exit codes: 0 measured (whatever the antenna's SWR), 2 the measurement couldn't be made (no
NanoVNA, a device problem) or the command was used wrongly.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from serial.tools import list_ports

from dipstick.bands import BANDS
from dipstick.device import DeviceError, NanoVNA, find_port
from dipstick.balun import RATIOS
from dipstick.measure import BandMeasurement, band_for_target, measure_band, measure_cable, measure_transformer
from dipstick.scan import MAX_POINTS



def connect(port: str | None) -> NanoVNA:
    return NanoVNA.open(port or find_port(list_ports.comports()))


def main(argv: list[str] | None = None, connect=connect) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["cable"]:
        return _cable(argv[1:], connect)
    if argv[:1] == ["balun"]:
        return _balun(argv[1:], connect)
    parser = argparse.ArgumentParser(
        prog="dipstick", description="Sweep an antenna across one amateur band and explain the NanoVNA's readings.",
        epilog="To check a coax cable instead: dipstick cable --help. A balun or unun: dipstick balun --help")
    parser.add_argument("band", help=f"one of: {', '.join(BANDS)}; or a frequency in MHz, e.g. 915, to sweep its "
                                     "band and trim for it")
    parser.add_argument("--target", metavar="MHZ", help="frequency to trim for, e.g. 7.074 (default: the band's middle)")
    parser.add_argument("--points", type=int, default=MAX_POINTS, help=f"2 to {MAX_POINTS} (default {MAX_POINTS})")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    parser.add_argument("--out", type=Path, default=Path("output"), help="folder for the SVG plots (default: output)")
    args = parser.parse_args(argv)
    try:
        band, target = args.band, args.target
        if band not in BANDS and re.fullmatch(r"[0-9.]+", band):  # a frequency: its band, trimmed for it
            if target is not None:
                raise ValueError(f"{band} is already the target; give a band with --target, or the frequency alone")
            band, target = band_for_target(band), band
        measured = measure_band(band, target, args.points, connect, args.port)
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
    parser.add_argument("--length", help="the cable's known length, e.g. 15.2 (meters), 50ft or 6in (gives the velocity factor)")
    parser.add_argument("--max-length", default="50", help="longest cable to plan the sweep for (default 50 m)")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    args = parser.parse_args(argv)
    try:
        measured = measure_cable(args.no_antenna, args.vf, args.length, args.max_length, connect, args.port)
        print(measured.report, end="")
        return 0
    except (DeviceError, ValueError) as error:
        print(f"dipstick: {error}", file=sys.stderr)
        return 2



def _balun(argv: list[str], connect) -> int:
    parser = argparse.ArgumentParser(
        prog="dipstick balun",
        description="Test an unun or voltage balun: a resistor of 50 x the ratio on its output (2450 ohms for a "
                    "49:1), the NanoVNA on its input. Shows its SWR on each band from 160 m to 6 m.")
    parser.add_argument("--ratio", required=True, help=f"the transformer's ratio: {', '.join(RATIOS)}")
    parser.add_argument("--resistor", help="the resistor's value, e.g. 2450, 2.45k (default: 50 x the ratio)")
    parser.add_argument("--no-antenna", action="store_true",
                        help="confirm nothing that radiates is connected: this sweeps far outside the ham bands")
    parser.add_argument("--port", help="the NanoVNA's serial port, if dipstick can't find it")
    parser.add_argument("--out", type=Path, default=Path("output"), help="folder for the SVG plot (default: output)")
    args = parser.parse_args(argv)
    try:
        measured = measure_transformer(args.no_antenna, args.ratio, args.resistor, connect, args.port)
        print(measured.report, end="")
        # The name comes from the ratio (already checked against the list) and the time, never typed text.
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"balun-{args.ratio.replace(':', 'to')}-{datetime.now():%Y%m%d-%H%M%S}-swr.svg"
        path.write_text(measured.swr_svg, encoding="utf-8")
        print(f"\nPlot: {path}")
        return 0
    except (DeviceError, ValueError, OSError) as error:
        print(f"dipstick: {error}", file=sys.stderr)
        return 2
