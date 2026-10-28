"""SQLite storage for imported decodes and contacts.

One local file (default data/ft8cast.sqlite, gitignored: it holds other
operators' callsigns). Re-importing the same file adds nothing: each table has a
UNIQUE key and rows go in with INSERT OR IGNORE. Every query is parameterized,
so text from a log (messages can be free text) is never read as SQL.
"""

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from ft8_forecast.adif import Contact
from ft8_forecast.alltxt import Decode

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE decodes (
    time TEXT NOT NULL,          -- UTC, 'YYYY-MM-DD HH:MM:SS'
    dial_hz INTEGER NOT NULL,
    transmit INTEGER NOT NULL,   -- 1 = your own Tx line
    snr_db INTEGER NOT NULL,
    sender TEXT,
    grid TEXT,
    message TEXT NOT NULL,
    UNIQUE (time, dial_hz, transmit, snr_db, message)
);
CREATE TABLE contacts (
    time TEXT NOT NULL,
    freq_hz INTEGER NOT NULL,
    call TEXT NOT NULL,
    grid TEXT,
    UNIQUE (time, freq_hz, call)
);
"""

_TIME = "%Y-%m-%d %H:%M:%S"


class StoreError(Exception):
    """The database file can't be used (not ours, or a different schema version)."""


def open_db(path: Path) -> sqlite3.Connection:
    """Open the database, creating it (and its folder) if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and not conn.execute("SELECT 1 FROM sqlite_master").fetchone():
            with conn:
                conn.executescript(_SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION};")
        elif version != SCHEMA_VERSION:
            raise StoreError(f"{path} isn't an ft8cast database (schema version {version})")
    except sqlite3.DatabaseError as error:
        conn.close()
        raise StoreError(f"{path} isn't an ft8cast database ({error})") from None
    except StoreError:
        conn.close()
        raise
    return conn


def save_decodes(conn: sqlite3.Connection, decodes: Iterable[Decode]) -> int:
    """Insert decodes in one transaction; returns how many were new."""
    rows = ((d.time.strftime(_TIME), d.dial_hz, int(d.transmit), d.snr_db, d.sender, d.grid, d.message)
            for d in decodes)
    return _insert(conn, "INSERT OR IGNORE INTO decodes VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def save_contacts(conn: sqlite3.Connection, contacts: Iterable[Contact]) -> int:
    """Insert contacts in one transaction; returns how many were new."""
    rows = ((c.time.strftime(_TIME), c.freq_hz, c.call, c.grid) for c in contacts)
    return _insert(conn, "INSERT OR IGNORE INTO contacts VALUES (?, ?, ?, ?)", rows)


def _insert(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> int:
    before = conn.total_changes
    with conn:  # one transaction: an error part-way stores nothing
        conn.executemany(sql, rows)
    return conn.total_changes - before
