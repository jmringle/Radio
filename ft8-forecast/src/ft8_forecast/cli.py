"""ft8cast: command-line front end. Every command is manual; nothing runs on a schedule."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from ft8_forecast import forecast
from ft8_forecast.adif import Problem, parse_adi
from ft8_forecast.alltxt import parse_all_txt
from ft8_forecast.store import StoreError, open_db, save_contacts, save_decodes

# This project's folder. Assumes the editable install from the README.
PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT / "data" / "ft8cast.sqlite"  # gitignored
ENV_FILE = PROJECT / ".env"  # gitignored; holds MY_GRID
STALE_DAYS = 7  # newer data than this needs no reminder to copy ALL.TXT over
# An ADIF file is read whole; a real log is well under 1 MB, so this only stops accidents.
MAX_ADIF_BYTES = 100 * 1024 * 1024
SHOW_PROBLEMS = 10

# Exit codes (README): 0 imported, 2 bad input (argparse uses 2 for usage errors too).
OK, BAD_INPUT = 0, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ft8cast", description="FT8 band forecast from your own logs.")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="add a WSJT-X/JTDX ALL.TXT or ADIF file to the database")
    imp.add_argument("file", type=Path, help="ALL.TXT or .adi file; it's only read, never changed")
    imp.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    fc = commands.add_parser("forecast", help="how each band has done for you at this UTC hour")
    fc.add_argument("--hour", type=_hour, help="UTC hour 0-23 (default: now)")
    fc.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    return parser


def _hour(text: str) -> int:
    if not (text.isascii() and text.isdigit() and len(text) <= 2 and int(text) <= 23):
        raise argparse.ArgumentTypeError(f"must be a UTC hour from 0 to 23, got {text!r}")
    return int(text)


def _now() -> datetime:
    return datetime.now(UTC)  # one place, so tests can fix the clock


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        # argparse has printed usage and the error (code 2), or help (code 0).
        return int(exit_.code or 0)
    if args.command == "forecast":
        return _forecast(args.hour, args.db)
    return _import(args.file, args.db)


def _import(source: Path, db: Path) -> int:
    if not source.is_file():
        return _error(f"{source}: no such file")
    if db.exists() and db.resolve() == source.resolve():
        return _error("--db can't be the file being imported")
    try:
        with source.open("rb") as file:
            is_adif = _looks_like_adif(file.read(4096))
            file.seek(0)
            if is_adif:
                data = file.read(MAX_ADIF_BYTES + 1)
                if len(data) > MAX_ADIF_BYTES:
                    return _error(f"{source}: larger than {MAX_ADIF_BYTES // 1024 // 1024} MB; not an ADIF log?")
                result = parse_adi(data)
                records, skipped = result.contacts, [(result.other_modes, "other modes")]
            else:
                result = parse_all_txt(file)
                records = result.decodes
                skipped = [(result.other_modes, "other modes"), (result.unknown_dial, "unknown dial frequency")]
    except OSError as error:
        return _error(f"{source}: {error.strerror}")

    kind = "ADIF" if is_adif else "ALL.TXT"
    _print_problems(result.problems)
    if not records:
        return _error(f"{source}: no FT8 records found (read as {kind})")

    try:
        conn = open_db(db)
    except StoreError as error:
        return _error(str(error))
    try:
        new = save_contacts(conn, records) if is_adif else save_decodes(conn, records)
    finally:
        conn.close()

    noun = "contacts" if is_adif else "lines"
    print(f"{source.name} ({kind}): {len(records):,} FT8 {noun}, {new:,} new, "
          f"{len(records) - new:,} already stored")
    skips = ", ".join(f"{count:,} {why}" for count, why in skipped if count)
    if skips:
        print(f"Skipped: {skips}")
    print(f"Problems: {len(result.problems):,}" + (" (listed above)" if result.problems else ""))
    return OK


def _forecast(hour: int | None, db: Path) -> int:
    try:
        my_grid = _my_grid()
    except ValueError as error:
        return _error(f"MY_GRID in {ENV_FILE.name}: {error}")
    if not db.is_file():
        return _error(f"no database at {db}; run `ft8cast import` first")
    try:
        conn = open_db(db)
    except StoreError as error:
        return _error(str(error))
    now = _now()
    hour = now.hour if hour is None else hour
    try:
        result = forecast.compute(conn, hour, my_grid)
    finally:
        conn.close()
    if result is None:
        return _error("no ALL.TXT data imported yet; run `ft8cast import <ALL.TXT>` first")

    newest = result.newest.strftime("%Y-%m-%d %H:%M")
    print(f"FT8 forecast for {hour:02d}:00-{hour:02d}:59 UTC "
          f"(your data: {forecast.WINDOW_DAYS} days through {newest} UTC)")
    age = (now.replace(tzinfo=None) - result.newest).days
    if age > STALE_DAYS:
        print(f"Note: your newest data is {age} days old; copy a fresh ALL.TXT over and import it.")
    print()
    print(f"{'Band':<5} {'Open':<14} {'Stations':>8} {'Median SNR':>11} {'Farthest':>11} {'Contacts':>9}")
    for band in result.bands:
        if not band.enough_data:
            days = band.listening_days
            print(f"{band.band:<5} not enough data ({days} day{'' if days == 1 else 's'} "
                  f"listening; need {forecast.MIN_DAYS})")
            continue
        snr = "-" if band.median_snr is None else f"{band.median_snr:.0f} dB"
        far = "-" if band.farthest_miles is None else f"{band.farthest_miles:,} mi"
        opened = f"{band.open_days} of {band.listening_days} days"
        print(f"{band.band:<5} {opened:<14} {band.stations:>8,} {snr:>11} {far:>11} {band.contacts:>9,}")
    print()
    if my_grid is None:
        print(f"Farthest needs your grid: set MY_GRID in {ENV_FILE.name} (see .env.example).")
    print("Solar: unavailable (the forecast above uses only your data)")
    return OK


def _my_grid() -> str | None:
    """MY_GRID from .env as a 4-character square; None if not set. ValueError if invalid."""
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() == "MY_GRID":
            value = value.split("#", 1)[0].strip().strip("\"'")
            return forecast.parse_grid(value) if value else None
    return None


def _looks_like_adif(start: bytes) -> bool:
    # An ADI file starts with "<" (no header) or has <EOH> near the top; ALL.TXT lines start with a date.
    return start.lstrip().startswith(b"<") or b"<eoh>" in start.lower()


def _print_problems(problems: list[Problem]) -> None:
    for problem in problems[:SHOW_PROBLEMS]:
        print(f"line {problem.line}: {problem.message}", file=sys.stderr)
    if len(problems) > SHOW_PROBLEMS:
        print(f"... and {len(problems) - SHOW_PROBLEMS:,} more problems", file=sys.stderr)


def _error(message: str) -> int:
    print(f"ft8cast: error: {message}", file=sys.stderr)
    return BAD_INPUT
