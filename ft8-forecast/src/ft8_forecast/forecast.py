"""The forecast: how each band has done for you at one UTC hour, from your own data.

Window: the 30 days up to your newest imported decode (not up to today), so an
older copy of ALL.TXT still gives a full window; the CLI says how old it is.
"""

import math
import re
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache

from band_privileges import LicenseClass, Mode, check

WINDOW_DAYS = 30
MIN_DAYS = 5  # fewer listening days than this at an hour: "not enough data", no score

# Band edges from §97.301 (the Extra column, i.e. the whole band), in Hz. 60 m is
# left out, as in band-privileges v1. tests/test_forecast.py checks these edges
# against band-privileges, and that General may use data on every one.
BANDS = [
    ("160m", 1_800_000, 2_000_000),
    ("80m", 3_500_000, 4_000_000),
    ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000),
    ("20m", 14_000_000, 14_350_000),
    ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000),
    ("12m", 24_890_000, 24_990_000),
    ("10m", 28_000_000, 29_700_000),
]

_TIME = "%Y-%m-%d %H:%M:%S"
_GRID = re.compile(r"([A-R]{2}[0-9]{2})([A-X]{2}([0-9]{2})?)?")
EARTH_RADIUS_MILES = 3958.8


@dataclass(frozen=True)
class BandStats:
    band: str
    listening_days: int  # days with any line (Rx or your Tx) on this band at this hour
    open_days: int  # of those, days with at least 1 decode
    stations: int  # distinct senders decoded
    median_snr: float | None
    farthest_miles: int | None  # None without MY_GRID or without any grid heard
    contacts: int  # completed contacts from the ADIF log

    @property
    def enough_data(self) -> bool:
        return self.listening_days >= MIN_DAYS


@dataclass(frozen=True)
class Forecast:
    hour: int
    newest: datetime  # newest imported decode: the window ends here
    bands: list[BandStats]  # every band in BANDS, low to high


def parse_grid(text: str) -> str:
    """A 4, 6 or 8-character Maidenhead locator -> its 4-character square. ValueError otherwise."""
    match = _GRID.fullmatch(text.strip().upper())
    if not match:
        raise ValueError(f"{text.strip()[:12]!r} isn't a grid square like FN31")
    return match.group(1)


def miles_between(grid_a: str, grid_b: str) -> int:
    """Great-circle distance between the centers of two 4-character squares, in miles.

    A square is 2 degrees of longitude by 1 of latitude (about 140 x 70 miles in
    the US), so this is good to roughly +/- 70 miles.
    """
    (lat1, lon1), (lat2, lon2) = _center(grid_a), _center(grid_b)
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return round(2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h)))


def _center(grid: str) -> tuple[float, float]:
    lon = (ord(grid[0]) - ord("A")) * 20 - 180 + int(grid[2]) * 2 + 1
    lat = (ord(grid[1]) - ord("A")) * 10 - 90 + int(grid[3]) + 0.5
    return lat, lon


@cache
def band_for(freq_hz: int) -> str | None:
    """The band name, if General may operate data there (the forecast's scope)."""
    if not check(freq_hz, Mode.DATA, LicenseClass.GENERAL).allowed:
        return None
    return next((name for name, low, high in BANDS if low <= freq_hz <= high), None)


def compute(conn: sqlite3.Connection, hour: int, my_grid: str | None) -> Forecast | None:
    """The forecast for `hour` (0-23 UTC), or None if no decodes are imported."""
    newest_text = conn.execute("SELECT max(time) FROM decodes").fetchone()[0]
    if newest_text is None:
        return None
    newest = datetime.strptime(newest_text, _TIME)
    window = ((newest - timedelta(days=WINDOW_DAYS)).strftime(_TIME), newest_text, f"{hour:02d}")
    where = "time > ? AND time <= ? AND substr(time, 12, 2) = ?"

    listening: dict[str, set[str]] = {}
    open_days: dict[str, set[str]] = {}
    senders: dict[str, set[str]] = {}
    snrs: dict[str, list[int]] = {}
    farthest: dict[str, int] = {}
    for time, dial_hz, transmit, snr, sender, grid in conn.execute(
        f"SELECT time, dial_hz, transmit, snr_db, sender, grid FROM decodes WHERE {where}", window
    ):
        band = band_for(dial_hz)
        if band is None:
            continue
        day = time[:10]
        listening.setdefault(band, set()).add(day)
        if transmit:
            continue  # your own Tx: proves you were there, isn't a station heard
        open_days.setdefault(band, set()).add(day)
        snrs.setdefault(band, []).append(snr)
        if sender:
            senders.setdefault(band, set()).add(sender)
        if grid and my_grid:
            farthest[band] = max(farthest.get(band, 0), miles_between(my_grid, grid))

    contacts: dict[str, int] = {}
    for (freq_hz,) in conn.execute(f"SELECT freq_hz FROM contacts WHERE {where}", window):
        if band := band_for(freq_hz):
            contacts[band] = contacts.get(band, 0) + 1

    bands = [
        BandStats(
            band=name,
            listening_days=len(listening.get(name, ())),
            open_days=len(open_days.get(name, ())),
            stations=len(senders.get(name, ())),
            median_snr=statistics.median(snrs[name]) if name in snrs else None,
            farthest_miles=farthest.get(name),
            contacts=contacts.get(name, 0),
        )
        for name, _, _ in BANDS
    ]
    return Forecast(hour, newest, bands)
