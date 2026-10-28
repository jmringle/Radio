"""ft8cast: command-line front end. Every command is manual; nothing runs on a schedule."""

import argparse
import sys
from pathlib import Path

from ft8_forecast.adif import Problem, parse_adi
from ft8_forecast.alltxt import parse_all_txt
from ft8_forecast.store import StoreError, open_db, save_contacts, save_decodes

# This project's data/ folder (gitignored). Assumes the editable install from the README.
DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "ft8cast.sqlite"
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
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        # argparse has printed usage and the error (code 2), or help (code 0).
        return int(exit_.code or 0)
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
