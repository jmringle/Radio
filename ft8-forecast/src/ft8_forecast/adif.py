"""ADIF (.adi) import: a WSJT-X/JTDX contact log into validated FT8 contacts.

Follows the ADI format in ADIF 3.1.6 section IV.A (adif.org, checked 2026-10-28):
an optional header that doesn't start with "<" and ends at <EOH>, then records of
<NAME:LENGTH[:TYPE]>data specifiers, each record ending at <EOR>. Names and tags
are case-insensitive. Anything outside a specifier (line breaks, comments) is
ignored.

The file is untrusted input: it may be truncated, hand-edited or written by
another logger. Bad content never raises; each problem is reported with the line
it's on, and the bad record is skipped.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from band_privileges import mhz

# Inside the angle brackets: NAME, or NAME:LENGTH, or NAME:LENGTH:TYPE.
_SPECIFIER = re.compile(rb"([A-Za-z0-9_]+)(?::([^:]*))?(?::(.*))?", re.DOTALL)
# ADI is ASCII text (the spec bars international types from .adi files), so a
# length in bytes is a length in characters for any file that follows it.
_DIGITS = re.compile(rb"[0-9]+")
_CALL = re.compile(r"[A-Z0-9]+(/[A-Z0-9]+)*")
_MAX_CALL = 20
_DATE = re.compile(r"[0-9]{8}")
_TIME = re.compile(r"[0-9]{4}([0-9]{2})?")
_GRID4 = re.compile(r"[A-R]{2}[0-9]{2}")  # Maidenhead field + square, e.g. FN31


@dataclass(frozen=True)
class Contact:
    call: str
    time: datetime  # UTC
    freq_hz: int
    grid: str | None  # first 4 characters, or None if not logged or invalid


@dataclass(frozen=True)
class Problem:
    line: int
    message: str


@dataclass
class ImportResult:
    contacts: list[Contact] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    other_modes: int = 0  # valid records that aren't FT8: skipped, not errors


def parse_adi(data: bytes) -> ImportResult:
    """Parse an .adi file's bytes. Only FT8 contacts are returned."""
    result = ImportResult()
    in_header = bool(data) and not data.startswith(b"<")
    fields: dict[str, bytes] = {}
    in_record = False
    record_line = 0
    record_ok = True
    pos = 0
    line = 1
    counted_to = 0  # line counts newlines incrementally, up to this byte

    while (start := data.find(b"<", pos)) != -1:
        line += data.count(b"\n", counted_to, start)
        counted_to = start
        end = data.find(b">", start)
        if end == -1:
            break  # a stray "<" at the end; handled as a truncated record below
        match = _SPECIFIER.fullmatch(data[start + 1 : end])
        name = match.group(1).decode().upper() if match else ""
        length = match.group(2) if match else None

        if in_header:
            # The header is free text that may hold its own specifiers; only
            # <EOH> matters. Skip over a specifier's data so it can't hide a tag.
            if name == "EOH" and length is None:
                in_header = False
                pos = end + 1
            elif length is not None and _DIGITS.fullmatch(length):
                pos = end + 1 + int(length)
            else:
                pos = end + 1
            continue

        if name == "EOR" and length is None:
            if in_record and record_ok:
                _add_record(fields, record_line, result)
            fields, in_record, record_ok = {}, False, True
            pos = end + 1
            continue

        if not in_record:
            in_record, record_line = True, line
        if length is None or not _DIGITS.fullmatch(length):
            result.problems.append(Problem(line, f"unreadable tag {_show(data[start : end + 1])}"))
            record_ok = False
            pos = end + 1
            continue
        value_end = end + 1 + int(length)
        if value_end > len(data):
            result.problems.append(Problem(line, f"<{name}> runs past the end of the file (truncated?)"))
            return result
        if name in fields:
            result.problems.append(Problem(line, f"<{name}> appears twice in one record"))
            record_ok = False
        fields[name] = data[end + 1 : value_end]
        pos = value_end

    if in_header:
        result.problems.append(Problem(1, "header has no <EOH>; no records read"))
    elif in_record:
        result.problems.append(Problem(record_line, "last record has no <EOR> (truncated?); skipped"))
    return result


def _add_record(fields: dict[str, bytes], line: int, result: ImportResult) -> None:
    def text(name: str) -> str | None:
        raw = fields.get(name)
        return None if raw is None else raw.decode("ascii").strip().upper()

    try:
        mode = text("MODE")
        if mode is None:
            raise ValueError("no MODE")
        if mode != "FT8":
            result.other_modes += 1
            return
        contact = Contact(
            call=_call(text("CALL")),
            time=_time(text("QSO_DATE"), text("TIME_ON")),
            freq_hz=_freq(text("FREQ")),
            grid=None,
        )
    except UnicodeDecodeError:  # a ValueError subclass, so it must come first
        result.problems.append(Problem(line, "non-ASCII data; record skipped"))
        return
    except ValueError as error:
        result.problems.append(Problem(line, f"{error}; record skipped"))
        return

    # The grid is optional: a bad one costs the distance, not the contact.
    raw_grid = fields.get("GRIDSQUARE")
    if raw_grid is not None:
        grid = raw_grid.decode("ascii", "replace").strip().upper()[:4]
        if _GRID4.fullmatch(grid):
            contact = replace(contact, grid=grid)
        else:
            result.problems.append(Problem(line, f"GRIDSQUARE {_show(raw_grid)} has no 4-character locator; contact kept without it"))
    result.contacts.append(contact)


def _call(value: str | None) -> str:
    if not value:
        raise ValueError("no CALL")
    if len(value) > _MAX_CALL or not _CALL.fullmatch(value):
        raise ValueError(f"CALL {value[:_MAX_CALL]!r} isn't a callsign")
    return value


def _time(date: str | None, time: str | None) -> datetime:
    if not date or not time:
        raise ValueError("no QSO_DATE or TIME_ON")
    if not _DATE.fullmatch(date) or not _TIME.fullmatch(time):
        raise ValueError(f"QSO_DATE/TIME_ON {date!r} {time!r} isn't YYYYMMDD HHMM[SS]")
    try:
        when = datetime.strptime(date + time.ljust(6, "0"), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"QSO_DATE/TIME_ON {date!r} {time!r} isn't a real date and time") from None
    if when.year < 1930:  # the spec's earliest allowed date
        raise ValueError(f"QSO_DATE {date!r} is before 1930")
    return when


def _freq(value: str | None) -> int:
    if not value:
        raise ValueError("no FREQ")
    try:
        return mhz(value)
    except ValueError as error:
        raise ValueError(f"FREQ: {error}") from None


def _show(tag: bytes) -> str:
    return repr(tag[:40].decode("ascii", "replace"))
