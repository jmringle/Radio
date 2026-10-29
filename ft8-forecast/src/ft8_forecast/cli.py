"""ft8cast: command-line front end. Every command is manual and offline: no schedule, no web calls."""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ft8_forecast import folder, forecast
from ft8_forecast.adif import Problem
from ft8_forecast.logs import Log, TooLarge, read_log, save_log
from ft8_forecast.store import StoreError, open_db

# This project's folder. Assumes the editable install from the README.
PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT / "data" / "ft8cast.sqlite"  # gitignored
ENV_FILE = PROJECT / ".env"  # gitignored; holds MY_GRID
DEFAULT_PORT = 8074  # 14.074 MHz, the 20 m FT8 frequency
DEFAULT_EVERY = 60  # seconds between `watch` checks; WSJT-X adds lines every 15 s
STALE_DAYS = 7  # newer data than this needs no reminder to copy ALL.TXT over
SHOW_PROBLEMS = 10
ALL_HOURS = "all"  # --hour all / ?hour=all: the whole day, not one hour


# Under the table, here and on the web page: what the less obvious columns mean.
LEGEND = (f"Typical day: median stations per day you listened. Total heard: over {forecast.WINDOW_DAYS} days.",
          f"Signal: median SNR. Heard out to: same station and grid on {forecast.FARTHEST_MIN_DAYS}+ days.")
RANK_LABELS = {"busiest": "busiest", "contacts": "most contacts"}


def distance(miles: int | None, grid: str | None = None) -> str:
    """'1,234 mi', or '1,234 mi (FN31)' with a grid (the web page); '-' for none."""
    if miles is None:
        return "-"
    return f"{miles:,} mi" + (f" ({grid})" if grid else "")


def best_bet_line(result: forecast.Forecast, by: str) -> str:
    """The answer at the top, here and on the web page."""
    label = f"Best bet ({RANK_LABELS[by]})"
    when = " at this hour" if result.hour is not None else ""
    best = forecast.best_bet(result.bands, by)
    if best is None:
        if not any(band.listening_days for band in result.bands):
            return f"{label}: none - no listening{when} in these {forecast.WINDOW_DAYS} days"
        if not forecast.rank(result.bands, by):
            return f"{label}: none yet - no band has {forecast.MIN_DAYS} days of listening{when}"
        if by == "busiest":
            return f"{label}: none - no stations heard{when}"
        return f"{label}: none - no contacts{when} in these {forecast.WINDOW_DAYS} days"
    if by == "busiest":
        busy = f"{best.stations_per_day:,.0f}"
        why = f"about {busy} station{'' if busy == '1' else 's'} on a typical day"
    else:
        why = f"{best.contacts:,} contact{'' if best.contacts == 1 else 's'} in {forecast.WINDOW_DAYS} days"
    worked = f"; worked out to {distance(best.contact_miles)}" if best.contact_miles is not None else ""
    return f"{label}: {best.band} - {why}{worked}"


def thin_line(result: forecast.Forecast) -> str | None:
    """One line for the bands without enough data, grouped by days listened; None if there are
    none, or if there's no listening at all (the best bet line says so)."""
    groups: dict[int, list[str]] = {}
    for band in result.bands:
        if not band.enough_data:
            groups.setdefault(band.listening_days, []).append(band.band)
    if not groups or not any(band.listening_days for band in result.bands):
        return None
    when = " at this hour" if result.hour is not None else ""
    parts = [f"{' '.join(names)} ({days} day{'' if days == 1 else 's'})" for days, names in sorted(groups.items())]
    return f"Too little data{when} (need {forecast.MIN_DAYS} days): {', '.join(parts)}"


def overview_key(by: str) -> str:
    return f"Typical-day stations; * = best bet ({RANK_LABELS[by]}); . = too little data"


@dataclass(frozen=True)
class Overview:
    """The 24-hour grid, trimmed of rows and columns that would be all dots. The terminal and
    the web page both draw from this."""
    bands: list[str]  # columns: bands with enough data at some hour, in BANDS order
    rows: list[tuple[int, list[tuple[str, bool]]]]  # (hour, (cell, is best bet) per column)
    thin_hours: list[int]  # listened, but too little data on every band
    silent_hours: list[int]  # no listening at all
    hidden_bands: list[str]  # too little data at every hour

    def notes(self) -> list[str]:
        """The lines under the grid. With no rows, only the no-listening line: the
        'no band has 5 days' message covers the rest."""
        silent = [f"Hours with no listening: {hour_ranges(self.silent_hours)}"] if self.silent_hours else []
        if not self.rows:
            return silent
        thin = [f"Too little data on every band: {hour_ranges(self.thin_hours)}"] if self.thin_hours else []
        hidden = [f"Too little data at every hour: {' '.join(self.hidden_bands)}"] if self.hidden_bands else []
        return thin + silent + hidden


OVERVIEW_EMPTY = f"No band has {forecast.MIN_DAYS} days of listening at any hour yet."


def overview(results: list[forecast.Forecast], by: str) -> Overview:
    """results: compute() for hours 0-23."""
    shown = [i for i, (name, _, _) in enumerate(forecast.BANDS)
             if any(result.bands[i].enough_data for result in results)]
    rows, thin, silent = [], [], []
    for result in results:
        if not any(band.listening_days for band in result.bands):
            silent.append(result.hour)
        elif not any(band.enough_data for band in result.bands):
            thin.append(result.hour)
        else:
            best = forecast.best_bet(result.bands, by)
            rows.append((result.hour, [(f"{band.stations_per_day:,.0f}" if band.enough_data else ".", band is best)
                                       for band in (result.bands[i] for i in shown)]))
    names = [name for name, _, _ in forecast.BANDS]
    return Overview([names[i] for i in shown], rows, thin, silent,
                    [name for i, name in enumerate(names) if i not in shown])


def hour_ranges(hours: list[int]) -> str:
    """[0, 1, 2, 5] -> '00-02, 05'."""
    runs: list[list[int]] = []
    for hour in hours:
        if runs and hour == runs[-1][-1] + 1:
            runs[-1].append(hour)
        else:
            runs.append([hour])
    return ", ".join(f"{run[0]:02d}" if len(run) == 1 else f"{run[0]:02d}-{run[-1]:02d}" for run in runs)


def data_age(newest: datetime, now: datetime) -> str:
    """How old the newest decode is, in calendar days: 'today', 'yesterday', '3 days ago'."""
    days = max((now.date() - newest.date()).days, 0)
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def hour_title(hour: int | None) -> str:
    return "all hours (00:00-23:59 UTC)" if hour is None else f"{hour:02d}:00-{hour:02d}:59 UTC"

# Exit codes (README): 0 imported, 2 bad input (argparse uses 2 for usage errors too).
OK, BAD_INPUT = 0, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ft8cast", description="FT8 band forecast from your own logs.")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="add a WSJT-X/JTDX ALL.TXT or ADIF file, or a folder of them, to the database")
    imp.add_argument("file", type=Path, nargs="?",
                     help="ALL.TXT or .adi file; it's only read, never changed (default: the LOG_DIR folder)")
    imp.add_argument("--dir", type=Path, help="import ALL.TXT and .adi files from this folder instead")
    imp.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    wt = commands.add_parser("watch", help="import from a folder now, then again whenever its logs change, until Ctrl+C")
    wt.add_argument("--dir", type=Path, help="folder to watch (default: LOG_DIR in .env)")
    wt.add_argument("--every", type=_every, default=DEFAULT_EVERY,
                    help=f"seconds between checks, 10 to 3600 (default: {DEFAULT_EVERY})")
    wt.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    fc = commands.add_parser("forecast", help="how each band has done for you at this UTC hour")
    fc.add_argument("--hour", type=_hour, help=f"UTC hour 0-23, or {ALL_HOURS!r} for the whole day (default: now)")
    fc.add_argument("--rank", type=_rank, default="busiest",
                    help="pick the best bet and order bands by 'busiest' typical day or most 'contacts' (default: busiest)")
    fc.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    ov = commands.add_parser("overview", help="every UTC hour at a glance: stations per band, best bet starred")
    ov.add_argument("--rank", type=_rank, default="busiest",
                    help="star the best bet by 'busiest' typical day or most 'contacts' (default: busiest)")
    ov.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
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


def _rank(text: str) -> str:
    if text not in forecast.RANKINGS:
        raise argparse.ArgumentTypeError(f"must be 'busiest' or 'contacts', got {text!r}")
    return text


def _every(text: str) -> int:
    if not (text.isascii() and text.isdigit() and 10 <= int(text) <= 3600):
        raise argparse.ArgumentTypeError(f"must be 10 to 3600 seconds, got {text!r}")
    return int(text)


def _now() -> datetime:
    return datetime.now(UTC)  # one place, so tests can fix the clock


_sleep = time.sleep  # likewise, so tests can run `watch` without waiting


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        # argparse has printed usage and the error (code 2), or help (code 0).
        return int(exit_.code or 0)
    if args.command == "forecast":
        return _forecast(args.hour, args.rank, args.db)
    if args.command == "overview":
        return _overview(args.rank, args.db)
    if args.command == "serve":
        return _serve(args.port, args.db)
    if args.command == "watch":
        return _watch(args.dir, args.every, args.db)
    if args.file is not None and args.dir is not None:
        return _error("give a file or --dir, not both")
    if args.file is not None:
        return _import(args.file, args.db)
    return _import_folder(args.dir, args.db)


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

    _print_summary(source.name, log, new)
    return OK


def _print_summary(name: str, log: Log, new: int) -> None:
    print(f"{name} ({log.kind}): {len(log.records):,} FT8 {log.noun}, {new:,} new, "
          f"{len(log.records) - new:,} already stored")
    skips = ", ".join(f"{count:,} {why}" for count, why in log.skipped if count)
    if skips:
        print(f"Skipped: {skips}")
    print(f"Problems: {len(log.problems):,}" + (" (listed above)" if log.problems else ""))


def _import_folder(given: Path | None, db: Path) -> int:
    try:
        logs = given or _log_dir()
    except ValueError as error:
        return _error(str(error))
    if logs is None:
        return _error(f"nothing to import: give a file or --dir, or set LOG_DIR in {ENV_FILE.name}")
    try:
        folder.find_logs(logs)  # check before creating a database
        conn = open_db(db)
    except (folder.FolderError, StoreError) as error:
        return _error(str(error))
    try:
        results = folder.import_folder(conn, logs)
    except folder.FolderError as error:
        return _error(str(error))
    finally:
        conn.close()
    code = OK
    for result in results:
        if result.log is not None:
            _print_problems(result.log.problems)
        if result.error:
            code = _error(f"{result.path.name}: {result.error}")
        else:
            _print_summary(result.path.name, result.log, result.new)
    return code


def _watch(given: Path | None, every: int, db: Path) -> int:
    try:
        logs = given or _log_dir()
    except ValueError as error:
        return _error(str(error))
    if logs is None:
        return _error(f"nothing to watch: give --dir or set LOG_DIR in {ENV_FILE.name}")
    try:
        folder.find_logs(logs)  # a missing folder at the start is more likely a typo than an unmounted share
        conn = open_db(db)
    except (folder.FolderError, StoreError) as error:
        return _error(str(error))
    watcher = folder.Watcher(logs)
    print(f"Watching {logs} every {every} s; Ctrl+C stops.", flush=True)
    try:
        while True:
            for message in watcher.check(conn):
                print(f"{_now():%H:%M} UTC  {message}", flush=True)
            _sleep(every)
    except KeyboardInterrupt:
        print("Stopped.")
        return OK
    finally:
        conn.close()


def _forecast(hour: int | str | None, by: str, db: Path) -> int:
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
        result = forecast.compute(conn, hour, my_grid, now)
    finally:
        conn.close()
    if result is None:
        return _error("no ALL.TXT data imported yet; run `ft8cast import <ALL.TXT>` first")

    newest = result.newest.strftime("%Y-%m-%d %H:%M")
    print(f"FT8 forecast for {hour_title(hour)} (your last {forecast.WINDOW_DAYS} days, "
          f"through {newest} UTC, {data_age(result.newest, now)})")
    age = (now.replace(tzinfo=None) - result.newest).days
    if age > STALE_DAYS:
        print(f"Note: your newest data is {age} days old; copy a fresh ALL.TXT over and import it.")
    print("", best_bet_line(result, by), sep="\n")
    ranked = forecast.rank(result.bands, by)
    if ranked:
        print()
        print(f"{'Band':<4} {'Typical day':>12} {'Total heard':>12} {'Signal':>7} {'Heard out to':>13} "
              f"{'Worked out to':>14} {'Contacts':>9}")
        for band in ranked:
            snr = "-" if band.median_snr is None else f"{band.median_snr:.0f} dB"
            per_day = f"{band.stations_per_day:,.0f}"
            print(f"{band.band:<4} {per_day:>12} {band.stations:>12,} {snr:>7} {distance(band.farthest_miles):>13} "
                  f"{distance(band.contact_miles):>14} {band.contacts:>9,}")
    if thin := thin_line(result):
        print("", thin, sep="\n")
    if ranked:
        print("", *LEGEND, sep="\n")
    print("", "Every hour at a glance: ft8cast overview", sep="\n")
    if result.best_ever:
        best = result.best_ever
        print(f"\nFarthest contact ever: {distance(best.miles)} on {best.band}, {best.day}")
    if result.daily:
        print(f"\nFarthest contact by day ({forecast.WINDOW_DAYS} days, any hour):")
        print(f"{'Date':<10}  {'Band':<4} {'Farthest':>9}")
        for far in result.daily:
            print(f"{far.day:<10}  {far.band or '-':<4} {distance(far.miles):>9}")
    if my_grid is None:
        print(f"\nHeard out to and Worked out to need your grid: set MY_GRID in {ENV_FILE.name} (see .env.example).")
    return OK


def _overview(by: str, db: Path) -> int:
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
    try:
        now = _now()
        results = [forecast.compute(conn, hour, my_grid, now) for hour in range(24)]
    finally:
        conn.close()
    if results[0] is None:
        return _error("no ALL.TXT data imported yet; run `ft8cast import <ALL.TXT>` first")

    newest = results[0].newest
    print(f"24-hour overview (your last {forecast.WINDOW_DAYS} days, "
          f"through {newest:%Y-%m-%d %H:%M} UTC, {data_age(newest, now)})")
    age = (now.replace(tzinfo=None) - newest).days
    if age > STALE_DAYS:
        print(f"Note: your newest data is {age} days old; copy a fresh ALL.TXT over and import it.")
    print(overview_key(by), "", sep="\n")
    grid = overview(results, by)
    if grid.rows:
        print(("UTC" + "".join(f" {name:>5} " for name in grid.bands)).rstrip())
        for hour, cells in grid.rows:
            print((f"{hour:02d} " + "".join(f" {text:>5}{'*' if best else ' '}" for text, best in cells)).rstrip())
    else:
        print(OVERVIEW_EMPTY)
    if notes := grid.notes():
        print("", *notes, sep="\n")
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


def _env(name: str) -> str | None:
    """A value from .env, without quotes or a trailing # comment; None if not set or empty."""
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.split("#", 1)[0].strip().strip("\"'") or None
    return None


def _my_grid() -> str | None:
    """MY_GRID from .env as a 4-character square; None if not set. ValueError if invalid."""
    value = _env("MY_GRID")
    return forecast.parse_grid(value) if value else None


def _log_dir() -> Path | None:
    """LOG_DIR from .env; ~ is expanded and a relative path is next to .env. None if not set."""
    value = _env("LOG_DIR")
    return None if value is None else (ENV_FILE.parent / Path(value).expanduser())


def _print_problems(problems: list[Problem]) -> None:
    for problem in problems[:SHOW_PROBLEMS]:
        print(f"line {problem.line}: {problem.message}", file=sys.stderr)
    if len(problems) > SHOW_PROBLEMS:
        print(f"... and {len(problems) - SHOW_PROBLEMS:,} more problems", file=sys.stderr)


def _error(message: str) -> int:
    print(f"ft8cast: error: {message}", file=sys.stderr)
    return BAD_INPUT
