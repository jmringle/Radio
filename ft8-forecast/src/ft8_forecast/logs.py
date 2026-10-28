"""Reading a WSJT-X/JTDX ALL.TXT or ADIF file: shared by `ft8cast import` and the web page."""

import sqlite3
from dataclasses import dataclass
from typing import BinaryIO

from ft8_forecast.adif import Contact, Problem, parse_adi
from ft8_forecast.alltxt import Decode, parse_all_txt
from ft8_forecast.store import save_contacts, save_decodes

# An ADIF file is read whole; a real log is well under 1 MB, so this only stops accidents.
MAX_ADIF_BYTES = 100 * 1024 * 1024


class TooLarge(Exception):
    """An ADIF file over MAX_ADIF_BYTES."""


@dataclass(frozen=True)
class Log:
    kind: str  # "ALL.TXT" or "ADIF", decided by content, not file name
    records: list[Decode] | list[Contact]
    problems: list[Problem]
    skipped: list[tuple[int, str]]  # (count, reason) for lines left out on purpose

    @property
    def noun(self) -> str:
        return "contacts" if self.kind == "ADIF" else "lines"


def read_log(file: BinaryIO) -> Log:
    """Parse an open binary file (must be seekable). Raises TooLarge, or OSError from reading."""
    is_adif = _looks_like_adif(file.read(4096))
    file.seek(0)
    if is_adif:
        data = file.read(MAX_ADIF_BYTES + 1)
        if len(data) > MAX_ADIF_BYTES:
            raise TooLarge(f"larger than {MAX_ADIF_BYTES // 1024 // 1024} MB; not an ADIF log?")
        result = parse_adi(data)
        return Log("ADIF", result.contacts, result.problems, [(result.other_modes, "other modes")])
    result = parse_all_txt(file)
    return Log("ALL.TXT", result.decodes, result.problems,
               [(result.other_modes, "other modes"), (result.unknown_dial, "unknown dial frequency")])


def save_log(conn: sqlite3.Connection, log: Log) -> int:
    """Store the records; returns how many were new."""
    return save_contacts(conn, log.records) if log.kind == "ADIF" else save_decodes(conn, log.records)


def _looks_like_adif(start: bytes) -> bool:
    # An ADI file starts with "<" (no header) or has <EOH> near the top; ALL.TXT lines start with a date.
    return start.lstrip().startswith(b"<") or b"<eoh>" in start.lower()
