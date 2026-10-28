"""WSJT-X ALL.TXT import: one line per decode (Rx) or transmission (Tx).

The format isn't formally documented. This follows the user's own file, surveyed
2026-10-28 (424,976 lines, WSJT-X, Dec 2025 - Oct 2026), where every line is:

    YYMMDD_HHMMSS  <dial MHz> Rx|Tx <mode>  <SNR dB> <DT s> <audio Hz> <message>

Findings that shaped the rules below: a dial of 0.000 (WSJT-X didn't know the
frequency) on 19 days; trailing a1-a9 tags on "a priori" decodes; RR73, the FT8
sign-off, has a grid's shape; lines aren't strictly in time order (late decode
passes, up to 60 s back), so nothing here assumes order.

The file is untrusted input. Bad lines never raise; each is reported with its
line number and skipped.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Iterable

from band_privileges import mhz

from ft8_forecast.adif import Problem

_LINE = re.compile(
    r"(?P<date>[0-9]{6})_(?P<time>[0-9]{6}) +(?P<dial>[0-9]{1,5}\.[0-9]{1,6}) (?P<dir>Rx|Tx) "
    r"(?P<mode>[A-Z0-9]{1,8}) +(?P<snr>-?[0-9]{1,3}) +-?[0-9]{1,2}\.[0-9] +[0-9]{1,5} (?P<msg>.*)"
)
_AP_TAG = re.compile(r"a[0-9]")  # WSJT-X marks "a priori" decodes, e.g. "CQ N0CALL AA00 a1"
_CALL = re.compile(r"(?=[A-Z0-9/]*[0-9])(?=[A-Z0-9/]*[A-Z])[A-Z0-9]+(/[A-Z0-9]+)*")
_MAX_CALL = 15
_GRID4 = re.compile(r"[A-R]{2}[0-9]{2}")
_NOT_GRIDS = {"RR73"}  # the FT8 sign-off, not a square in the Arctic


@dataclass(frozen=True)
class Decode:
    time: datetime  # UTC, as WSJT-X logged it
    dial_hz: int
    transmit: bool  # your own Tx line: proof you were on the band, not a decode
    snr_db: int
    sender: str | None  # station that sent the message, when its shape says
    grid: str | None  # sender's 4-character grid, when the message carries one


@dataclass
class AllTxtResult:
    decodes: list[Decode] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    other_modes: int = 0  # valid lines that aren't FT8: skipped, not errors
    unknown_dial: int = 0  # dial 0.000: band unknown, so skipped, not errors


def parse_all_txt(lines: Iterable[bytes]) -> AllTxtResult:
    """Parse ALL.TXT lines (bytes, as read from the file). Only FT8 is kept."""
    result = AllTxtResult()
    for number, raw in enumerate(lines, 1):
        try:
            text = raw.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError:
            result.problems.append(Problem(number, "non-ASCII data; line skipped"))
            continue
        if not text.strip():
            continue
        match = _LINE.fullmatch(text)
        if not match:
            result.problems.append(Problem(number, f"not an ALL.TXT decode line: {text[:60]!r}"))
            continue
        if match["mode"] != "FT8":
            result.other_modes += 1
            continue
        if Decimal(match["dial"]) == 0:
            result.unknown_dial += 1
            continue
        try:
            when = _time(match["date"], match["time"])
            dial = mhz(match["dial"])
        except ValueError as error:
            result.problems.append(Problem(number, f"{error}; line skipped"))
            continue
        sender, grid = _sender_and_grid(match["msg"])
        result.decodes.append(Decode(when, dial, match["dir"] == "Tx", int(match["snr"]), sender, grid))
    return result


def _time(date: str, time: str) -> datetime:
    try:
        # Two-digit year: FT8 dates from 2017, so 20YY (strptime's %y would put 69-99 in the 1900s).
        return datetime.strptime("20" + date + time, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"{date}_{time} isn't a real date and time") from None


def _sender_and_grid(message: str) -> tuple[str | None, str | None]:
    """Who sent a standard FT8 message, and their grid if it's in it.

    Shapes: "CQ [modifier] FROM [GRID]" and "TO FROM [GRID|report|RR73|73]".
    A hashed call WSJT-X resolved shows as <N0CALL>; unresolved <...> and anything
    else (free text) give None rather than a guess.
    """
    words = message.split()
    if words and _AP_TAG.fullmatch(words[-1]):
        words.pop()
    grid = None
    if len(words) >= 3 and _GRID4.fullmatch(words[-1]) and words[-1] not in _NOT_GRIDS:
        grid = words.pop()
    if words[:1] == ["CQ"]:
        # "CQ FROM" or "CQ DX FROM": the sender is last once the grid is off.
        sender = words[-1] if len(words) in (2, 3) else None
    else:
        sender = words[1] if len(words) >= 2 else None
    if sender is not None:
        sender = sender.removeprefix("<").removesuffix(">")
    if sender is None or len(sender) > _MAX_CALL or not _CALL.fullmatch(sender):
        return None, None
    return sender, grid
