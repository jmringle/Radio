"""The forecast: how each band has done for you at one UTC hour (or all hours), from your own data.

Window: the 30 days up to your newest imported decode or contact, whichever is
later (not up to today), so an older copy of ALL.TXT still gives a full window and
a fresher ADIF log still counts; the CLI says how old it is.
"""

import bisect
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
# Farthest counts a station only if it was decoded with the same grid on this many days
# (at the hour, on the band): one day can be a false decode or a station's wrong grid.
FARTHEST_MIN_DAYS = 2

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


# A decode addressed to you this soon after your call answers it. WSJT-X stamps a line with
# its 15 s cycle's start, so a reply in the next cycle is 15 s later; a reply 45 s later
# belongs to your next call (surveyed in the author's ALL.TXT, 2026-10-29).
REPLY_SECONDS = 30

# Trend: the window's last TREND_DAYS against the TREND_DAYS before, each half needing
# TREND_MIN_DAYS listening days. A change counts only if it is at least TREND_SHARE of
# the earlier half and at least TREND_STATIONS a day, so 1 -> 2 stations isn't "busier".
TREND_DAYS = WINDOW_DAYS // 2
TREND_MIN_DAYS = 3
TREND_SHARE = 0.25
TREND_STATIONS = 2

# How to pick the best bet and order the table: --rank / the page's "Best bet by".
RANKINGS = ("busiest", "contacts")


@dataclass(frozen=True)
class BandStats:
    band: str
    listening_days: int  # days with any line (Rx or your Tx) on this band at this hour
    stations_per_day: float | None  # median distinct senders per listening day (Tx-only days count 0)
    stations: int  # distinct senders decoded over the whole window
    median_snr: float | None
    farthest_miles: int | None  # None without MY_GRID or without a station heard on FARTHEST_MIN_DAYS days
    farthest_grid: str | None  # the 4-character square farthest_miles is measured to
    contact_miles: int | None  # farthest logged contact with a grid; None without MY_GRID or one
    contact_grid: str | None
    contacts: int  # completed contacts from the ADIF log
    # Your opening calls and how many were followed within REPLY_SECONDS by a decode addressed
    # to you on this band: CQs, and calls to a station (they carry your grid).
    cqs: int
    cqs_answered: int
    calls: int
    calls_answered: int
    recent_per_day: float | None  # stations_per_day over the last TREND_DAYS; None under TREND_MIN_DAYS days
    earlier_per_day: float | None  # the same for the TREND_DAYS before

    @property
    def enough_data(self) -> bool:
        return self.listening_days >= MIN_DAYS


@dataclass(frozen=True)
class Farthest:
    """A farthest logged contact. On a day whose contacts have no grid, band/miles/grid are None."""
    day: str  # UTC date, YYYY-MM-DD
    band: str | None
    miles: int | None
    grid: str | None  # the other station's 4-character square


@dataclass(frozen=True)
class Forecast:
    hour: int | None  # None: all hours
    newest: datetime  # newest imported decode or contact (not in the future): the window ends here
    bands: list[BandStats]  # every band in BANDS, low to high
    daily: list[Farthest]  # farthest contact per day with contacts in the window, newest first; [] without MY_GRID
    best_ever: Farthest | None  # farthest of every imported contact; None without MY_GRID or a gridded contact


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


def compute(conn: sqlite3.Connection, hour: int | None, my_grid: str | None,
            now: datetime | None = None) -> Forecast | None:
    """The forecast for `hour` (0-23 UTC; None for all hours), or None if no decodes are imported.

    `now` (UTC): contacts dated after it (a wrong clock on the radio computer) don't move
    the window's end; without it, every contact may.
    """
    newest_text = conn.execute("SELECT max(time) FROM decodes").fetchone()[0]
    if newest_text is None:
        return None
    latest = "9999" if now is None else now.strftime(_TIME)
    contact_text = conn.execute("SELECT max(time) FROM contacts WHERE time <= ?", (latest,)).fetchone()[0]
    if contact_text is not None and contact_text > newest_text:
        newest_text = contact_text
    newest = datetime.strptime(newest_text, _TIME)
    window: tuple = ((newest - timedelta(days=WINDOW_DAYS)).strftime(_TIME), newest_text)
    where = "time > ? AND time <= ?"
    if hour is not None:
        window += (f"{hour:02d}",)
        where += " AND substr(time, 12, 2) = ?"

    # band -> day -> senders decoded that day; a day with only your Tx has an empty set.
    listening: dict[str, dict[str, set[str]]] = {}
    snrs: dict[str, list[int]] = {}
    grid_days: dict[str, dict[tuple[str, str], set[str]]] = {}  # band -> (sender, grid) -> days heard
    cqs: dict[str, list[str]] = {}  # band -> times of your CQs
    calls: dict[str, list[str]] = {}  # band -> times of your calls to a station
    for time, dial_hz, transmit, snr, sender, grid, message in conn.execute(
        f"SELECT time, dial_hz, transmit, snr_db, sender, grid, message FROM decodes WHERE {where}", window
    ):
        band = band_for(dial_hz)
        if band is None:
            continue
        day = time[:10]
        heard = listening.setdefault(band, {}).setdefault(day, set())
        if transmit:
            # Your own Tx: proves you were there, isn't a station heard. Reports and
            # sign-offs carry no grid, so only the opening call of a contact counts.
            if message.startswith("CQ "):
                cqs.setdefault(band, []).append(time)
            elif grid:
                calls.setdefault(band, []).append(time)
            continue
        snrs.setdefault(band, []).append(snr)
        if sender:
            heard.add(sender)
        if grid and sender and my_grid:
            grid_days.setdefault(band, {}).setdefault((sender, grid), set()).add(day)

    farthest: dict[str, tuple[int, str]] = {}
    for band, pairs in grid_days.items():
        qualified = [(miles_between(my_grid, grid), grid) for (_, grid), days in pairs.items()
                     if len(days) >= FARTHEST_MIN_DAYS]
        if qualified:
            farthest[band] = max(qualified)

    contacts: dict[str, int] = {}
    contact_far: dict[str, Farthest] = {}  # the column: window and hour
    by_day: dict[str, Farthest] = {}  # the daily list: window, any hour
    best_ever = None  # every contact
    # No 2-day rule here: a contact is a completed exchange, and its grid came from it.
    # Oldest first, so a tie keeps the earlier contact.
    for time, freq_hz, grid in conn.execute("SELECT time, freq_hz, grid FROM contacts ORDER BY time"):
        band = band_for(freq_hz)
        if band is None:
            continue
        day = time[:10]
        far = Farthest(day, band, miles_between(my_grid, grid), grid) if grid and my_grid else None
        best_ever = _farther(best_ever, far)
        if not window[0] < time <= window[1]:
            continue
        by_day[day] = _farther(by_day.get(day, Farthest(day, None, None, None)), far)
        if hour is not None and time[11:13] != f"{hour:02d}":
            continue
        contacts[band] = contacts.get(band, 0) + 1
        contact_far[band] = _farther(contact_far.get(band), far)

    cqs_answered = _answered(conn, cqs, window[1])
    calls_answered = _answered(conn, calls, window[1])
    split = (newest - timedelta(days=TREND_DAYS)).strftime("%Y-%m-%d")  # later dates: the recent half

    bands = []
    for name, _, _ in BANDS:
        days = listening.get(name, {})
        bands.append(BandStats(
            band=name,
            listening_days=len(days),
            stations_per_day=statistics.median(len(heard) for heard in days.values()) if days else None,
            stations=len(set().union(*days.values())),
            median_snr=statistics.median(snrs[name]) if name in snrs else None,
            farthest_miles=farthest[name][0] if name in farthest else None,
            farthest_grid=farthest[name][1] if name in farthest else None,
            contact_miles=contact_far[name].miles if contact_far.get(name) else None,
            contact_grid=contact_far[name].grid if contact_far.get(name) else None,
            contacts=contacts.get(name, 0),
            cqs=len(cqs.get(name, [])),
            cqs_answered=cqs_answered.get(name, 0),
            calls=len(calls.get(name, [])),
            calls_answered=calls_answered.get(name, 0),
            recent_per_day=_median_day([heard for day, heard in days.items() if day > split]),
            earlier_per_day=_median_day([heard for day, heard in days.items() if day <= split]),
        ))
    daily = sorted(by_day.values(), key=lambda far: far.day, reverse=True) if my_grid else []
    return Forecast(hour, newest, bands, daily, best_ever)


def _median_day(days: list[set[str]]) -> float | None:
    return statistics.median(len(heard) for heard in days) if len(days) >= TREND_MIN_DAYS else None


def trend(band: BandStats) -> str | None:
    """'busier' or 'quieter' in the recent half of the window, or None (no clear change, or too few days)."""
    if band.recent_per_day is None or band.earlier_per_day is None:
        return None
    change = band.recent_per_day - band.earlier_per_day
    if abs(change) < TREND_STATIONS or abs(change) < TREND_SHARE * band.earlier_per_day:
        return None
    return "busier" if change > 0 else "quieter"


def _answered(conn: sqlite3.Connection, calls: dict[str, list[str]], end: str) -> dict[str, int]:
    """Per band, how many of `calls` (times) a decode addressed to you followed within REPLY_SECONDS.

    You are every sender of your own Tx lines (more than one if you've used /P or a new call).
    """
    if not calls:
        return {}
    first = min(min(times) for times in calls.values())
    last = (datetime.strptime(end, _TIME) + timedelta(seconds=REPLY_SECONDS)).strftime(_TIME)
    mine = [row[0] for row in conn.execute("SELECT DISTINCT sender FROM decodes WHERE transmit = 1 AND sender IS NOT NULL")]
    if not mine:
        return {}  # no Tx line with a readable call: nothing can be addressed to you
    # Calls only hold A-Z, 0-9 and / (alltxt checks), so they can't carry LIKE wildcards.
    to_me = " OR ".join("message LIKE ? OR message LIKE ?" for _ in mine)
    replies: dict[str, list[str]] = {}
    for time, dial_hz in conn.execute(
        f"SELECT time, dial_hz FROM decodes WHERE transmit = 0 AND time > ? AND time <= ? AND ({to_me}) ORDER BY time",
        (first, last, *[pattern for call in mine for pattern in (f"{call} %", f"<{call}> %")]),
    ):
        if band := band_for(dial_hz):
            replies.setdefault(band, []).append(time)
    answered = {}
    for band, times in calls.items():
        heard = replies.get(band, [])
        answered[band] = 0
        for time in times:
            soon = (datetime.strptime(time, _TIME) + timedelta(seconds=REPLY_SECONDS)).strftime(_TIME)
            i = bisect.bisect_right(heard, time)
            answered[band] += i < len(heard) and heard[i] <= soon
    return answered


def _farther(best: Farthest | None, new: Farthest | None) -> Farthest | None:
    """The farther of two; a tie keeps `best`, so with contacts in time order the earlier wins."""
    if new is None or (best is not None and best.miles is not None and new.miles <= best.miles):
        return best
    return new


def rank(bands: list[BandStats], by: str) -> list[BandStats]:
    """Bands with enough data, best first by `by` (one of RANKINGS); the other measure breaks
    a tie, then the lower band (the sort is stable and `bands` runs low to high)."""
    def score(band: BandStats) -> tuple:
        busy = band.stations_per_day or 0
        return (busy, band.contacts) if by == "busiest" else (band.contacts, busy)
    return sorted((b for b in bands if b.enough_data), key=score, reverse=True)


def best_bet(bands: list[BandStats], by: str) -> BandStats | None:
    """The top band by `by`, or None when no band with enough data scores above 0."""
    ranked = rank(bands, by)
    if not ranked:
        return None
    top = ranked[0]
    return top if (top.stations_per_day if by == "busiest" else top.contacts) else None
