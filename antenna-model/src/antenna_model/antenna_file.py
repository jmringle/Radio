"""Antenna files: one TOML file per antenna, read into meters (README acceptance criteria).

    name = "40m EFHW"
    units = "ft"            # required: "ft" or "m"
    ground = "average"      # free-space, perfect, average, poor or good
    bands = ["40m", "20m"]

    [[wire]]                # one per straight wire
    from = [0, 0, 6]        # x, y, height
    to = [66, 0, 25]
    size = "14 AWG"         # or "2.0 mm" (diameter)

    [feed]
    wire = 1                # which [[wire]], counting from 1
    at = 0                  # 0 = the wire's "from" end, 0.5 = middle, 1 = "to" end
    ratio = 49              # transformer impedance ratio; optional, 1 if none

Files may come from a forum or a club, so every field is checked before NEC2 sees it (T1),
and unknown keys are refused so a typo can't silently fall back to a default.
"""

import math
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

FOOT = 0.3048  # meters, exactly (international foot)
UNITS = {"ft": FOOT, "m": 1.0}
GROUNDS = ("free-space", "perfect", "average", "poor", "good")  # values: with the ground model
# HF band edges, 47 CFR 97.301(b), Region 2 (eCFR, read 2026-11-15). 80m includes 75m.
# 60m is left out: it's five channels, not a band (97.303(h)), as in band-privileges v1.
BANDS = {
    "160m": (1.800, 2.000), "80m": (3.500, 4.000), "40m": (7.000, 7.300), "30m": (10.100, 10.150),
    "20m": (14.000, 14.350), "17m": (18.068, 18.168), "15m": (21.000, 21.450),
    "12m": (24.890, 24.990), "10m": (28.000, 29.700),
}
MAX_BYTES = 64 * 1024  # a 100-wire antenna is about 10 KB
MAX_WIRES = 100
MAX_NAME = 60
MAX_COORDINATE = 10_000  # in the file's units: no backyard antenna is 10 km away
MAX_AWG, MAX_MM = 40, 50  # 40 AWG is hair-thin; 50 mm covers aluminum tubing for verticals
MAX_RATIO = 100

TOP_KEYS = {"name", "units", "ground", "bands", "wire", "feed"}
WIRE_KEYS = {"from", "to", "size"}
FEED_KEYS = {"wire", "at", "ratio"}


@dataclass(frozen=True)
class Wire:
    start: tuple[float, float, float]  # meters: x, y, height
    end: tuple[float, float, float]
    radius_m: float


@dataclass(frozen=True)
class Feed:
    wire: int  # index into Antenna.wires, from 0
    at: float  # 0 = the wire's start, 1 = its end
    ratio: float  # transformer impedance ratio, e.g. 49 for 49:1


@dataclass(frozen=True)
class Antenna:
    name: str
    ground: str
    bands: tuple[str, ...]
    wires: tuple[Wire, ...]
    feed: Feed


class AntennaFileError(ValueError):
    """The file can't be used; the message names the file and the field."""


class _Problem(Exception):
    """A problem inside the file; read_antenna adds the file name."""


def read_antenna(path: Path) -> Antenna:
    path = Path(path)
    try:
        return _antenna(_toml(path))
    except _Problem as problem:
        raise AntennaFileError(f"{path.name}: {problem}") from None


def _toml(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            # Never reads more than the cap, however big the file. (Untested: a test would need a
            # huge file, and would hang rather than fail if this broke.)
            raw = file.read(MAX_BYTES + 1)
    except OSError as error:
        raise _Problem(f"can't read it ({error.strerror})") from None
    if len(raw) > MAX_BYTES:
        raise _Problem(f"over {MAX_BYTES // 1024} KB, too big for an antenna file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Problem("not UTF-8 text") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise _Problem(f"not valid TOML: {error}") from None  # tomllib's message gives the line


def _antenna(data: dict) -> Antenna:
    _known_keys(data, TOP_KEYS, "")
    name = _required(data, "name", "")
    if not isinstance(name, str) or not name.strip():
        raise _Problem("'name' must be text, not blank")
    if len(name) > MAX_NAME:
        raise _Problem(f"'name' is over {MAX_NAME} characters")
    if any(unicodedata.category(ch)[0] == "C" or unicodedata.category(ch) in ("Zl", "Zp") for ch in name):
        raise _Problem("'name' has a control character (a line break, tab or terminal code)")
    units = _required(data, "units", "")
    if units not in UNITS:
        raise _Problem(f"'units' must be \"ft\" or \"m\", got {units!r}")
    ground = _required(data, "ground", "")
    if ground not in GROUNDS:
        raise _Problem(f"'ground' must be one of {', '.join(GROUNDS)}; got {ground!r}")
    bands = _bands(_required(data, "bands", ""))
    wire_tables = _required(data, "wire", "")
    if not isinstance(wire_tables, list):
        raise _Problem("wires go in [[wire]] sections (double brackets), one per wire")
    if not wire_tables:
        raise _Problem("at least one [[wire]] is required")
    if len(wire_tables) > MAX_WIRES:
        raise _Problem(f"more than {MAX_WIRES} wires")
    wires = tuple(_wire(table, f"wire {n}", UNITS[units], ground) for n, table in enumerate(wire_tables, 1))
    feed = _feed(_required(data, "feed", ""), len(wires))
    return Antenna(name, ground, bands, wires, feed)


def _bands(value) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _Problem("'bands' must be a list of bands, e.g. [\"40m\", \"20m\"]")
    for band in value:
        if band not in BANDS:
            raise _Problem(f"band {band!r} isn't one of {', '.join(BANDS)}")
        if value.count(band) > 1:
            raise _Problem(f"band {band!r} is listed twice")
    return tuple(value)


def _wire(table, where: str, scale: float, ground: str) -> Wire:
    if not isinstance(table, dict):
        raise _Problem(f"{where}: must be a [[wire]] section")
    _known_keys(table, WIRE_KEYS, where)
    start = _point(_required(table, "from", where), f"{where}: 'from'", scale, ground)
    end = _point(_required(table, "to", where), f"{where}: 'to'", scale, ground)
    if start == end:
        raise _Problem(f"{where}: 'from' and 'to' are the same point, so the wire has no length")
    return Wire(start, end, _diameter_m(_required(table, "size", where), where) / 2)


def _point(value, what: str, scale: float, ground: str) -> tuple[float, float, float]:
    if not (isinstance(value, list) and len(value) == 3 and all(_is_number(v) for v in value)):
        raise _Problem(f"{what} must be 3 numbers [x, y, height]")
    if not all(math.isfinite(v) for v in value):
        raise _Problem(f"{what} must be finite numbers")
    if any(abs(v) > MAX_COORDINATE for v in value):
        raise _Problem(f"{what} is more than {MAX_COORDINATE} from the origin")
    if value[2] < 0 and ground != "free-space":
        raise _Problem(f"{what} is below ground (height {value[2]})")
    x, y, z = (v * scale for v in value)
    return (x, y, z)


def _diameter_m(size, where: str) -> float:
    usage = f"{where}: 'size' must be like \"14 AWG\" or \"2.0 mm\""
    if not isinstance(size, str) or len(size.split()) != 2:
        raise _Problem(usage)
    number, unit = size.split()
    if unit.upper() == "AWG":
        if not (number.isascii() and number.isdigit() and 0 <= int(number) <= MAX_AWG):
            raise _Problem(f"{where}: 'size' AWG must be a whole number from 0 to {MAX_AWG}, got {number!r}")
        # The AWG definition: 36 AWG is 0.005 in (0.127 mm), 0000 is 0.46 in, 39 steps between.
        return 0.127e-3 * 92 ** ((36 - int(number)) / 39)
    if unit.lower() == "mm":
        try:
            mm = float(number)
        except ValueError:
            raise _Problem(usage) from None
        if not (0 < mm <= MAX_MM):  # also false for nan
            raise _Problem(f"{where}: 'size' must be above 0 and at most {MAX_MM} mm, got {number}")
        return mm / 1000
    raise _Problem(usage)


def _feed(table, wire_count: int) -> Feed:
    if not isinstance(table, dict):
        raise _Problem("feed: must be a [feed] section")
    _known_keys(table, FEED_KEYS, "feed")
    wire = _required(table, "wire", "feed")
    if not isinstance(wire, int) or isinstance(wire, bool):
        raise _Problem("feed: 'wire' must be a whole number")
    if not 1 <= wire <= wire_count:
        raise _Problem(f"feed: 'wire' is {wire}, but the file has {wire_count} wire{'' if wire_count == 1 else 's'}"
                       " (counting from 1)")
    at = _required(table, "at", "feed")
    if not (_is_number(at) and 0 <= at <= 1):
        raise _Problem(f"feed: 'at' must be a number from 0 (the wire's start) to 1 (its end), got {at!r}")
    ratio = table.get("ratio", 1)
    if not _is_number(ratio):
        raise _Problem(f"feed: 'ratio' must be a number, e.g. 49 for a 49:1 transformer, got {ratio!r}")
    if not 0 < ratio <= MAX_RATIO:
        raise _Problem(f"feed: 'ratio' must be above 0 and at most {MAX_RATIO}, got {ratio}")
    return Feed(wire - 1, at, ratio)


def _required(table: dict, key: str, where: str):
    if key not in table:
        raise _Problem(f"{where + ': ' if where else ''}'{key}' is required")
    return table[key]


def _known_keys(table: dict, known: set[str], where: str) -> None:
    unknown = sorted(set(table) - known)
    if unknown:
        raise _Problem(f"{where + ': ' if where else ''}unknown key {unknown[0]!r} (allowed: {', '.join(sorted(known))})")


def _is_number(value) -> bool:
    # TOML true/false load as bool, which Python counts as an int: not a number here.
    return isinstance(value, (int, float)) and not isinstance(value, bool)
