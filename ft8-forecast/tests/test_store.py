"""SQLite storage: de-duplication, schema check, untrusted text kept as data."""

import sqlite3
from datetime import UTC, datetime

import pytest

from ft8_forecast import Contact, Decode
from ft8_forecast.store import SCHEMA_VERSION, StoreError, open_db, save_contacts, save_decodes

WHEN = datetime(2026, 10, 27, 14, 30, 15, tzinfo=UTC)


def decode(message="CQ N0CALL FN31", snr=-9, transmit=False) -> Decode:
    return Decode(WHEN, 14_074_000, transmit, snr, "N0CALL", "FN31", message)


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "data" / "ft8cast.sqlite")  # data/ doesn't exist yet
    yield conn
    conn.close()


def test_new_database_gets_the_schema_version(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_saving_the_same_decodes_twice_adds_nothing(conn):
    assert save_decodes(conn, [decode(), decode(snr=-10)]) == 2
    assert save_decodes(conn, [decode(), decode(snr=-10)]) == 0
    assert conn.execute("SELECT count(*) FROM decodes").fetchone()[0] == 2


@pytest.mark.parametrize("other", [decode(message="CQ N0CALL/P FN31"), decode(snr=-8), decode(transmit=True)])
def test_decodes_differing_in_any_key_field_are_both_kept(conn, other):
    assert save_decodes(conn, [decode(), other]) == 2


def test_saving_the_same_contacts_twice_adds_nothing(conn):
    contact = Contact("N0CALL", WHEN, 14_075_800, "FN31")
    assert save_contacts(conn, [contact]) == 1
    assert save_contacts(conn, [contact, Contact("N0CALL", WHEN, 14_075_800, None)]) == 0


def test_stored_values_round_trip(conn):
    save_decodes(conn, [decode()])
    assert conn.execute("SELECT * FROM decodes").fetchone() == (
        "2026-10-27 14:30:15", 14_074_000, 0, -9, "N0CALL", "FN31", "CQ N0CALL FN31")


def test_message_text_is_stored_as_data_not_sql(conn):
    # Free text comes from whoever transmitted it; it must never run as SQL.
    nasty = "TNX'); DROP TABLE decodes; --"
    save_decodes(conn, [decode(message=nasty)])
    assert conn.execute("SELECT message FROM decodes").fetchone() == (nasty,)


def test_reopening_keeps_the_data(tmp_path):
    path = tmp_path / "ft8cast.sqlite"
    with_data = open_db(path)
    save_decodes(with_data, [decode()])
    with_data.close()
    reopened = open_db(path)
    assert reopened.execute("SELECT count(*) FROM decodes").fetchone()[0] == 1
    reopened.close()


def test_a_failed_save_stores_nothing(conn):
    rows = [decode(), "not a decode"]  # fails on the second row
    with pytest.raises(AttributeError):
        save_decodes(conn, rows)
    assert conn.execute("SELECT count(*) FROM decodes").fetchone()[0] == 0


def test_other_sqlite_database_is_refused(tmp_path):
    path = tmp_path / "other.sqlite"
    other = sqlite3.connect(path)
    other.execute("CREATE TABLE notes (text)")
    other.commit()
    other.close()
    with pytest.raises(StoreError, match="isn't an ft8cast database"):
        open_db(path)


def test_different_schema_version_is_refused(tmp_path):
    path = tmp_path / "future.sqlite"
    future = sqlite3.connect(path)
    future.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    future.close()
    with pytest.raises(StoreError, match="schema version"):
        open_db(path)


def test_file_that_isnt_sqlite_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "notes.sqlite"
    path.write_bytes(b"just some text, not a database\n" * 10)
    with pytest.raises(StoreError, match="isn't an ft8cast database"):
        open_db(path)
    assert path.read_bytes() == b"just some text, not a database\n" * 10
