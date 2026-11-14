"""CHIRP's CSV fields, read the way CHIRP reads them.

From CHIRP's source (chirp_common.py and drivers/generic_csv.py, commit d99bb22709,
2026-11-13): frequencies are MHz with up to 6 decimals ("146.940000"), optionally
followed by " MHz". Duplex is "", "+", "-", "split" (Offset then holds the transmit
frequency itself) or "off" (transmit disabled).
"""

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

_MHZ = re.compile(r"([0-9]+)(?:\.([0-9]{0,6}))?")  # ASCII digits only: int() would also take "٣"
DUPLEX = ("", "+", "-", "split", "off")


def parse_mhz(text: str) -> int:
    """A CHIRP frequency in MHz -> exact Hz. ValueError if it isn't one."""
    text = text.strip().removesuffix(" MHz").strip()
    match = _MHZ.fullmatch(text)
    if not match:
        raise ValueError(f"{text[:20]!r} isn't a frequency in MHz like 146.940000")
    whole, fraction = match.group(1), match.group(2) or ""
    return int(whole) * 1_000_000 + int(fraction.ljust(6, "0"))


def transmit_hz(rx_hz: int, duplex: str, offset: str) -> int | None:
    """Where the channel transmits; None if transmit is off. ValueError for a bad duplex or offset."""
    if duplex not in DUPLEX:
        raise ValueError(f"Duplex {duplex[:10]!r} isn't one of: blank, +, -, split, off")
    if duplex == "off":
        return None
    if duplex == "":
        return rx_hz
    shift = parse_mhz(offset)
    return {"+": rx_hz + shift, "-": rx_hz - shift, "split": shift}[duplex]


MAX_BYTES = 5 * 1024 * 1024  # CHIRP's own files hold at most 1,000 memories: well under 1 MB
REQUIRED = ("Location", "Frequency")


class ReadError(Exception):
    """The file as a whole can't be checked (the command's exit code 2)."""


@dataclass(frozen=True)
class Channel:
    line: int  # the CSV line, as a text editor numbers it
    location: int  # CHIRP's memory number
    name: str
    rx_hz: int
    tx_hz: int | None  # None: transmit off
    tx_tone: str | None  # what it sends on transmit, e.g. "Tone 100.0" or "DTCS 023"; None: nothing
    rx_tone: str | None  # what it needs to hear to open squelch
    mode: str


def read_channels(path: Path) -> tuple[list[Channel], list[tuple[int, str]]]:
    """Every non-empty memory in a CHIRP CSV, and (line, problem) for each row that couldn't be read."""
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ReadError(f"{path.name} is over {MAX_BYTES // 1024 // 1024} MB; a CHIRP export is far smaller")
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ReadError(f"Can't read {path.name}: {error.strerror}") from None
    except UnicodeDecodeError:
        raise ReadError(f"{path.name} isn't UTF-8 text; export it from CHIRP as CSV") from None

    # Rows end only at CR/LF, as CHIRP reads them (newline=""): str.splitlines() would also
    # split on U+2028, form feeds and others inside a channel name.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    channels, problems, header = [], [], None
    try:
        for fields in reader:
            line = reader.line_num
            if not fields or fields[0].startswith("#"):
                continue  # blank line, or a CHIRP comment
            if header is None:
                header = fields
                missing = [name for name in REQUIRED if name not in header]
                if missing:
                    raise ReadError(f"{path.name} isn't a CHIRP CSV export: no {' or '.join(missing)} column")
                continue
            if len(fields) < len(header):
                problems.append((line, f"has {len(fields)} columns, the header has {len(header)}"))
                continue
            values = dict(zip(header, fields))
            try:
                channel = _channel(line, values)
            except ValueError as error:
                problems.append((line, str(error)))
                continue
            if channel is not None:
                channels.append(channel)
    except csv.Error as error:
        raise ReadError(f"{path.name} line {reader.line_num}: not readable as CSV ({error})") from None
    if header is None:
        raise ReadError(f"{path.name} is empty")
    return channels, problems


def _channel(line: int, values: dict[str, str]) -> Channel | None:
    """One row -> a Channel; None for an empty memory (no frequency), as CHIRP skips them."""
    text = values["Frequency"].strip()
    if text == "" or parse_mhz(text) == 0:
        return None
    rx_hz = parse_mhz(text)
    location = values["Location"].strip()
    if not location.isascii() or not location.isdigit():
        raise ValueError(f"Location {location[:10]!r} isn't a memory number")
    tx_tone, rx_tone = _tones(values)
    return Channel(line, int(location), values.get("Name", ""), rx_hz,
                   transmit_hz(rx_hz, values.get("Duplex", "").strip(), values.get("Offset", "")),
                   tx_tone, rx_tone, values.get("Mode", "FM").strip() or "FM")


def _tones(values: dict[str, str]) -> tuple[str | None, str | None]:
    """What the channel sends and listens for. Only the columns its Tone mode uses are read:
    CHIRP fills the rest (CrossMode included) with defaults."""
    mode = values.get("Tone", "").strip()
    if mode not in TONE_MODES:
        raise ValueError(f"Tone {mode[:10]!r} isn't one of: blank, {', '.join(TONE_MODES[1:])}")
    if mode == "Cross":
        cross = values.get("CrossMode", "").strip()
        if cross not in CROSS_MODES:
            raise ValueError(f"CrossMode {cross[:12]!r} isn't one of: {', '.join(CROSS_MODES)}")
        sends, hears = cross.split("->")
    else:
        sends, hears = _SIMPLE[mode]
    # Which column holds each tone (CHIRP chirp_common.py): TSQL sends and hears cToneFreq; Tone and
    # Cross send rToneFreq; Cross hears RxDtcsCode for DCS; everything else uses DtcsCode.
    send_ctcss = "cToneFreq" if mode == "TSQL" else "rToneFreq"
    hear_dcs = "RxDtcsCode" if mode == "Cross" else "DtcsCode"
    tx = {"": None, "Tone": lambda: _ctcss(values, send_ctcss), "DTCS": lambda: _dcs(values, "DtcsCode")}[sends]
    rx = {"": None, "Tone": lambda: _ctcss(values, "cToneFreq"), "DTCS": lambda: _dcs(values, hear_dcs)}[hears]
    return tx and tx(), rx and rx()


TONE_MODES = ("", "Tone", "TSQL", "DTCS", "DTCS-R", "TSQL-R", "Cross")
CROSS_MODES = ("Tone->Tone", "DTCS->", "->DTCS", "Tone->DTCS", "DTCS->Tone", "->Tone", "DTCS->DTCS", "Tone->")
# Tone mode -> (what it sends, what it listens for), in CrossMode's terms.
_SIMPLE = {"": ("", ""), "Tone": ("Tone", ""), "TSQL": ("Tone", "Tone"), "DTCS": ("DTCS", "DTCS"),
           "TSQL-R": ("", "Tone"), "DTCS-R": ("", "DTCS")}
_DCS = re.compile(r"[0-7]{1,3}")
_CTCSS = re.compile(r"[0-9]{2,3}(\.[0-9])?")


def _ctcss(values: dict[str, str], column: str) -> str:
    text = values.get(column, "").strip()
    hz = float(text) if _CTCSS.fullmatch(text) else None
    if hz is None or not 50 < hz < 300:  # CHIRP's VALIDTONE
        raise ValueError(f"{column} {text[:10]!r} isn't a CTCSS tone like 100.0")
    return f"Tone {hz:.1f}"


def _dcs(values: dict[str, str], column: str) -> str:
    text = values.get(column, "").strip()
    if not _DCS.fullmatch(text):
        raise ValueError(f"{column} {text[:10]!r} isn't a DCS code like 023")
    return f"DTCS {int(text):03d}"
