"""Logs from a folder: finding them, importing them once, and watching for changes (README)."""

import os
import sys

import pytest

from ft8_forecast.folder import FolderError, Watcher, find_logs, import_folder
from ft8_forecast.store import open_db

ADIF = (b"WSJT-X ADIF Export<eoh>\n<call:6>N0CALL <gridsquare:4>FN31 <mode:3>FT8 "
        b"<qso_date:8>20261027 <time_on:6>143015 <freq:9>14.075800 <eor>\n")


def rx(second: int, snr: int = -9) -> bytes:
    """One ALL.TXT decode line; each second gives a distinct line."""
    return f"261027_1430{second:02d}    14.074 Rx FT8    {snr:3d}  0.2  627 CQ N0CALL FN31\r\n".encode()


@pytest.fixture
def logs(tmp_path):
    path = tmp_path / "logs"
    path.mkdir()
    return path


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "ft8cast.sqlite")
    yield conn
    conn.close()


def count(conn, table="decodes"):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --- finding the logs ---

def test_finds_all_txt_and_adif_files_by_name(logs):
    for name in ["ALL.TXT", "wsjtx_log.adi", "old.ADIF", "notes.txt", "ALL.TXT.bak", "wsjtx.log"]:
        (logs / name).write_bytes(b"x")
    assert [p.name for p in find_logs(logs)] == ["ALL.TXT", "old.ADIF", "wsjtx_log.adi"]


def test_name_match_ignores_case(logs):
    (logs / "all.txt").write_bytes(b"x")
    assert [p.name for p in find_logs(logs)] == ["all.txt"]


def test_skips_symlinks_and_subfolders(logs, tmp_path):
    outside = tmp_path / "secret.adi"
    outside.write_bytes(ADIF)
    try:
        (logs / "link.adi").symlink_to(outside)  # could point anywhere on disk
    except OSError:
        pass  # Windows without symlink rights: no symlink to skip, the subfolder part still runs
    (logs / "sub.adi").mkdir()
    (logs / "sub").mkdir()
    (logs / "sub" / "ALL.TXT").write_bytes(b"x")  # subfolders aren't searched
    assert find_logs(logs) == []


@pytest.mark.parametrize("make", ["missing", "file"])
def test_missing_folder_or_a_file_is_an_error(logs, make):
    path = logs / "nope"
    if make == "file":
        path.write_bytes(b"x")
    with pytest.raises(FolderError, match="isn't a folder"):
        find_logs(path)


# --- importing a folder once ---

def test_imports_every_log_in_the_folder(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1) + rx(2))
    (logs / "wsjtx_log.adi").write_bytes(ADIF)
    results = import_folder(conn, logs)
    assert [(r.path.name, r.log.kind, r.new, r.error) for r in results] == [
        ("ALL.TXT", "ALL.TXT", 2, None), ("wsjtx_log.adi", "ADIF", 1, None)]
    assert (count(conn), count(conn, "contacts")) == (2, 1)
    assert [r.new for r in import_folder(conn, logs)] == [0, 0]  # again: nothing new


def test_a_bad_file_is_reported_and_the_rest_still_import(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1))
    (logs / "broken.adi").write_bytes(b"<call:6>N0CALL <mode:3>FT4 <eor>")  # no FT8 records
    results = import_folder(conn, logs)
    assert [(r.path.name, r.error) for r in results] == [
        ("ALL.TXT", None), ("broken.adi", "no FT8 records found (read as ADIF)")]
    assert count(conn) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ignores chmod's read permission bits")
def test_an_unreadable_file_is_reported(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1))
    (logs / "ALL.TXT").chmod(0)
    try:
        assert import_folder(conn, logs)[0].error == "Permission denied"
    finally:
        (logs / "ALL.TXT").chmod(0o644)


def test_a_folder_without_logs_is_an_error(logs, conn):
    (logs / "notes.txt").write_bytes(b"x")
    with pytest.raises(FolderError, match="no ALL.TXT or .adi files in"):
        import_folder(conn, logs)


def test_the_folder_is_never_changed(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1))
    (logs / "wsjtx_log.adi").write_bytes(ADIF)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in logs.iterdir()}
    import_folder(conn, logs)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in logs.iterdir()} == before


# --- watching ---

def append(path, data):
    with path.open("ab") as file:
        file.write(data)


def test_first_check_imports_everything_then_stays_quiet(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1) + rx(2))
    (logs / "wsjtx_log.adi").write_bytes(ADIF)
    watcher = Watcher(logs)
    assert watcher.check(conn) == ["ALL.TXT: 2 new", "wsjtx_log.adi: 1 new"]
    assert watcher.check(conn) == []  # nothing changed: nothing printed


def test_only_new_lines_are_read(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1) + rx(2))
    watcher = Watcher(logs)
    watcher.check(conn)
    # Garble line 1 in place (same length): a full re-read would report it, a tail read never sees it.
    data = path.read_bytes()
    path.write_bytes(b"#" * len(rx(1)) + data[len(rx(1)):] + rx(3))
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]
    assert count(conn) == 3


def test_a_half_written_line_waits_for_the_next_check(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1))
    watcher = Watcher(logs)
    watcher.check(conn)
    line = rx(2)
    append(path, line[:20])  # WSJT-X is mid-write
    assert watcher.check(conn) == []
    append(path, line[20:])
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]
    assert count(conn) == 2


def test_problems_have_the_files_line_numbers(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1) + rx(2))
    watcher = Watcher(logs)
    watcher.check(conn)
    append(path, b"not an ALL.TXT line\n" + rx(3))
    messages = watcher.check(conn)
    assert messages[0] == "ALL.TXT: 1 new"
    assert messages[1].startswith("ALL.TXT line 3: ")


def test_a_smaller_file_is_read_again_from_the_start(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1) + rx(2) + rx(3))
    watcher = Watcher(logs)
    watcher.check(conn)
    path.write_bytes(rx(4))  # replaced with a fresh, shorter file
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]


def test_a_replaced_file_is_read_again_even_if_larger(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1))
    watcher = Watcher(logs)
    watcher.check(conn)
    fresh = logs / "fresh"
    fresh.write_bytes(rx(5) + rx(6) + rx(1))  # a different file: new lines come first
    os.replace(fresh, path)
    assert watcher.check(conn) == ["ALL.TXT: 2 new"]


def test_a_changed_adif_is_read_again(logs, conn):
    path = logs / "wsjtx_log.adi"
    path.write_bytes(ADIF)
    watcher = Watcher(logs)
    watcher.check(conn)
    append(path, ADIF.split(b"<eoh>\n")[1].replace(b"143015", b"150000"))
    assert watcher.check(conn) == ["wsjtx_log.adi: 1 new"]


def test_new_files_are_picked_up_and_deleted_ones_forgotten(logs, conn):
    watcher = Watcher(logs)
    assert watcher.check(conn) == []
    (logs / "ALL.TXT").write_bytes(rx(1))
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]
    (logs / "ALL.TXT").unlink()
    assert watcher.check(conn) == []
    (logs / "ALL.TXT").write_bytes(rx(1) + rx(2))
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]  # read from the start again


def test_an_unreachable_folder_is_reported_once_and_its_return_too(logs, conn, tmp_path):
    (logs / "ALL.TXT").write_bytes(rx(1))
    watcher = Watcher(logs)
    watcher.check(conn)
    logs.rename(tmp_path / "away")  # like a share coming unmounted
    first = watcher.check(conn)
    assert len(first) == 1 and first[0].startswith("folder not reachable") and first[0].endswith("; still checking")
    assert watcher.check(conn) == []
    (tmp_path / "away").rename(logs)
    append(logs / "ALL.TXT", rx(2))
    assert watcher.check(conn) == ["folder is reachable again", "ALL.TXT: 1 new"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ignores chmod's read permission bits")
def test_an_unreadable_file_is_tried_again(logs, conn):
    path = logs / "ALL.TXT"
    path.write_bytes(rx(1))
    path.chmod(0)
    watcher = Watcher(logs)
    try:
        assert watcher.check(conn) == ["ALL.TXT: can't read (Permission denied); trying again next check"]
    finally:
        path.chmod(0o644)
    assert watcher.check(conn) == ["ALL.TXT: 1 new"]


def test_watching_never_changes_the_folder(logs, conn):
    (logs / "ALL.TXT").write_bytes(rx(1))
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in logs.iterdir()}
    watcher = Watcher(logs)
    watcher.check(conn)
    watcher.check(conn)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in logs.iterdir()} == before


def test_an_adif_without_ft8_is_reported_once_until_it_changes(logs, conn):
    path = logs / "wsjtx_log.adi"
    path.write_bytes(b"<call:6>N0CALL <mode:3>FT4 <eor>")
    watcher = Watcher(logs)
    assert watcher.check(conn) == ["wsjtx_log.adi: no FT8 records found (read as ADIF)"]
    assert watcher.check(conn) == []
    path.write_bytes(ADIF)
    assert watcher.check(conn) == ["wsjtx_log.adi: 1 new"]


def test_an_oversized_adif_is_reported_once(logs, conn, monkeypatch):
    monkeypatch.setattr("ft8_forecast.logs.MAX_ADIF_BYTES", 10)
    (logs / "wsjtx_log.adi").write_bytes(ADIF)
    watcher = Watcher(logs)
    assert watcher.check(conn) == ["wsjtx_log.adi: larger than 0 MB; not an ADIF log?"]
    assert watcher.check(conn) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ignores chmod's read permission bits")
def test_an_unreadable_adif_is_tried_again(logs, conn):
    path = logs / "wsjtx_log.adi"
    path.write_bytes(ADIF)
    path.chmod(0)
    watcher = Watcher(logs)
    try:
        assert watcher.check(conn) == ["wsjtx_log.adi: can't read (Permission denied); trying again next check"]
    finally:
        path.chmod(0o644)
    assert watcher.check(conn) == ["wsjtx_log.adi: 1 new"]
