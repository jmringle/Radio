"""ft8cast: command-line front end. Every command is manual and offline: no schedule, no web calls."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from ft8_forecast import forecast
from ft8_forecast.adif import Problem
from ft8_forecast.logs import TooLarge, read_log, save_log
from ft8_forecast.store import StoreError, open_db

# This project's folder. Assumes the editable install from the README.
PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT / "data" / "ft8cast.sqlite"  # gitignored
ENV_FILE = PROJECT / ".env"  # gitignored; holds MY_GRID
DEFAULT_PORT = 8074  # 14.074 MHz, the 20 m FT8 frequency
STALE_DAYS = 7  # newer data than this needs no reminder to copy ALL.TXT over
SHOW_PROBLEMS = 10
ALL_HOURS = "all"  # --hour all / ?hour=all: the whole day, not one hour


def station_notes(hour: int | None) -> tuple[str, ...]:
    """Under the forecast table, here and on the web page: the two station columns are easy
    to mix up, Farthest heard leaves stations out on purpose, and Farthest contact is
    worked, not heard. hour None: all hours."""
    when = "at this hour" if hour is not None else "at any hour"
    return (f"Typical day: stations heard on the median day you listened{'' if hour is not None else ','} {when}.",
            f"30-day total: different stations heard over the whole {forecast.WINDOW_DAYS} days.",
            f"Farthest heard: a station heard with the same grid square on {forecast.FARTHEST_MIN_DAYS}+ days"
            f"{' ' if hour is not None else ', '}{when}; the square is theirs.",
            f"Farthest contact: your farthest logged contact with a grid square"
            f"{' ' if hour is not None else ', '}{when}; the square is theirs.")


def distance(miles: int | None, grid: str | None) -> str:
    """A farthest contact as '1,234 mi (FN31)', or '-' for none; the page uses it too."""
    return "-" if miles is None else f"{miles:,} mi ({grid})"


def hour_title(hour: int | None) -> str:
    return "all hours (00:00-23:59 UTC)" if hour is None else f"{hour:02d}:00-{hour:02d}:59 UTC"

# Exit codes (README): 0 imported, 2 bad input (argparse uses 2 for usage errors too).
OK, BAD_INPUT = 0, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ft8cast", description="FT8 band forecast from your own logs.")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="add a WSJT-X/JTDX ALL.TXT or ADIF file to the database")
    imp.add_argument("file", type=Path, help="ALL.TXT or .adi file; it's only read, never changed")
    imp.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    fc = commands.add_parser("forecast", help="how each band has done for you at this UTC hour")
    fc.add_argument("--hour", type=_hour, help=f"UTC hour 0-23, or {ALL_HOURS!r} for the whole day (default: now)")
    fc.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    sv = commands.add_parser("serve", help="the forecast and import as a web page, on this machine only")
    sv.add_argument("--port", type=_port, default=DEFAULT_PORT, help=f"port (default: {DEFAULT_PORT})")
    sv.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    return parser


def _port(text: str) -> int:
    # Below 1024 needs root on macOS; never run this as root.
    if not (text.isascii() and text.isdigit() and 1024 <= int(text) <= 65535):
        raise argparse.ArgumentTypeError(f"must be a port from 1024 to 65535, got {text!r}")
    return int(text)


def _hour(text: str) -> int | str:
    if text == ALL_HOURS:
        return ALL_HOURS
    if not (text.isascii() and text.isdigit() and len(text) <= 2 and int(text) <= 23):
        raise argparse.ArgumentTypeError(f"must be a UTC hour from 0 to 23 or {ALL_HOURS!r}, got {text!r}")
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
    if args.command == "serve":
        return _serve(args.port, args.db)
    return _import(args.file, args.db)


def _import(source: Path, db: Path) -> int:
    if not source.is_file():
        return _error(f"{source}: no such file")
    if db.exists() and db.resolve() == source.resolve():
        return _error("--db can't be the file being imported")
    try:
        with source.open("rb") as file:
            log = read_log(file)
    except TooLarge as error:
        return _error(f"{source}: {error}")
    except OSError as error:
        return _error(f"{source}: {error.strerror}")

    _print_problems(log.problems)
    if not log.records:
        return _error(f"{source}: no FT8 records found (read as {log.kind})")

    try:
        conn = open_db(db)
    except StoreError as error:
        return _error(str(error))
    try:
        new = save_log(conn, log)
    finally:
        conn.close()

    print(f"{source.name} ({log.kind}): {len(log.records):,} FT8 {log.noun}, {new:,} new, "
          f"{len(log.records) - new:,} already stored")
    skips = ", ".join(f"{count:,} {why}" for count, why in log.skipped if count)
    if skips:
        print(f"Skipped: {skips}")
    print(f"Problems: {len(log.problems):,}" + (" (listed above)" if log.problems else ""))
    return OK


def _forecast(hour: int | str | None, db: Path) -> int:
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
    hour = now.hour if hour is None else None if hour == ALL_HOURS else hour
    try:
        result = forecast.compute(conn, hour, my_grid)
    finally:
        conn.close()
    if result is None:
        return _error("no ALL.TXT data imported yet; run `ft8cast import <ALL.TXT>` first")

    newest = result.newest.strftime("%Y-%m-%d %H:%M")
    print(f"FT8 forecast for {hour_title(hour)} (your data: {forecast.WINDOW_DAYS} days through {newest} UTC)")
    age = (now.replace(tzinfo=None) - result.newest).days
    if age > STALE_DAYS:
        print(f"Note: your newest data is {age} days old; copy a fresh ALL.TXT over and import it.")
    print()
    print(f"{'':6}{' Stations heard ':-^26}")  # spans the two station columns below
    print(f"{'Band':<5} {'Typical day':>12} {'30-day total':>13} {'Median SNR':>11} {'Farthest heard':>17} "
          f"{'Farthest contact':>17} {'30-day contacts':>16}")
    for band in result.bands:
        if not band.enough_data:
            days = band.listening_days
            print(f"{band.band:<5} not enough data ({days} day{'' if days == 1 else 's'} "
                  f"listening; need {forecast.MIN_DAYS})")
            continue
        snr = "-" if band.median_snr is None else f"{band.median_snr:.0f} dB"
        far = "-" if band.farthest_miles is None else f"{band.farthest_miles:,} mi ({band.farthest_grid})"
        worked = distance(band.contact_miles, band.contact_grid)
        per_day = f"{band.stations_per_day:,.0f}"
        print(f"{band.band:<5} {per_day:>12} {band.stations:>13,} {snr:>11} {far:>17} {worked:>17} {band.contacts:>16,}")
    print("", *station_notes(hour), sep="\n")
    if result.best_ever:
        best = result.best_ever
        print(f"\nFarthest contact ever: {distance(best.miles, best.grid)} on {best.band}, {best.day}")
    if result.daily:
        print(f"\nFarthest contact by day ({forecast.WINDOW_DAYS} days, any hour):")
        print(f"{'Date':<10}  {'Band':<5} {'Farthest':>17}")
        for far in result.daily:
            print(f"{far.day:<10}  {far.band or '-':<5} {distance(far.miles, far.grid):>17}")
    if my_grid is None:
        print(f"\nFarthest heard and contacts need your grid: set MY_GRID in {ENV_FILE.name} (see .env.example).")
    return OK


def _serve(port: int, db: Path) -> int:
    from ft8_forecast import web  # Flask loads only for this command

    print(f"FT8 forecast page: http://127.0.0.1:{port}  (Ctrl+C stops it)")
    try:
        # 127.0.0.1: only this machine can connect. debug=False and no .env loading, so
        # FLASK_DEBUG can't switch on Werkzeug's debugger (it runs typed-in code).
        web.create_app(db).run(host="127.0.0.1", port=port, debug=False, load_dotenv=False)
    except SystemExit:
        return BAD_INPUT  # Werkzeug has printed why, e.g. the port is in use
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


def _print_problems(problems: list[Problem]) -> None:
    for problem in problems[:SHOW_PROBLEMS]:
        print(f"line {problem.line}: {problem.message}", file=sys.stderr)
    if len(problems) > SHOW_PROBLEMS:
        print(f"... and {len(problems) - SHOW_PROBLEMS:,} more problems", file=sys.stderr)


def _error(message: str) -> int:
    print(f"ft8cast: error: {message}", file=sys.stderr)
    return BAD_INPUT
