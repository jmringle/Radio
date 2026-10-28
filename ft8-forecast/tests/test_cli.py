"""ft8cast import and forecast: output, exit codes and file handling (README acceptance criteria)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from ft8_forecast import Decode, cli, logs
from ft8_forecast.cli import main
from ft8_forecast.store import open_db, save_decodes

RX = b"261027_143015    14.074 Rx FT8     -9  0.2  627 CQ N0CALL FN31\r\n"
RX2 = b"261027_143015    14.074 Rx FT8    -12  0.1 1200 N0CALL/M N0CALL -07\r\n"
FT4 = b"261027_143015    14.080 Rx FT4     -9  0.2  627 CQ N0CALL FN31\r\n"
NO_DIAL = b"261027_143015     0.000 Rx FT8     -9  0.2  627 CQ N0CALL FN31\r\n"
ADIF = (b"WSJT-X ADIF Export<eoh>\n<call:6>N0CALL <gridsquare:4>FN31 <mode:3>FT8 "
        b"<qso_date:8>20261027 <time_on:6>143015 <freq:9>14.075800 <eor>\n")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "ft8cast.sqlite"


def run(capsys, *args):
    code = main(["import", *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_imports_all_txt_and_reports_counts(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX + RX2 + FT4 + NO_DIAL)
    code, out, err = run(capsys, path, "--db", db)
    assert code == 0
    assert out == ("ALL.TXT (ALL.TXT): 2 FT8 lines, 2 new, 0 already stored\n"
                   "Skipped: 1 other modes, 1 unknown dial frequency\n"
                   "Problems: 0\n")
    assert err == ""


def test_reimporting_the_same_file_adds_nothing(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX + RX2)
    run(capsys, path, "--db", db)
    code, out, _ = run(capsys, path, "--db", db)
    assert code == 0
    assert out.startswith("ALL.TXT (ALL.TXT): 2 FT8 lines, 0 new, 2 already stored\n")


def test_a_longer_copy_of_the_file_adds_only_the_new_lines(tmp_path, db, capsys):
    # ALL.TXT grows; copying it over again should only add what's new.
    run(capsys, write(tmp_path, "ALL.TXT", RX), "--db", db)
    _, out, _ = run(capsys, write(tmp_path, "ALL.TXT", RX + RX2), "--db", db)
    assert "2 FT8 lines, 1 new, 1 already stored" in out


def test_imports_adif_detected_by_content_not_name(tmp_path, db, capsys):
    path = write(tmp_path, "export.txt", ADIF)
    code, out, _ = run(capsys, path, "--db", db)
    assert code == 0
    assert out.startswith("export.txt (ADIF): 1 FT8 contacts, 1 new, 0 already stored\n")


def test_headerless_adif_is_detected(tmp_path, db, capsys):
    path = write(tmp_path, "log.adi", ADIF.split(b"<eoh>\n")[1])
    assert "(ADIF): 1 FT8 contacts" in run(capsys, path, "--db", db)[1]


def test_source_file_is_never_changed(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX + RX2)
    os.utime(path, (1_000_000_000, 1_000_000_000))
    run(capsys, path, "--db", db)
    assert path.read_bytes() == RX + RX2
    assert path.stat().st_mtime == 1_000_000_000


def test_problems_go_to_stderr_with_line_numbers_and_the_rest_imports(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX + b"garbage\r\n" + RX2)
    code, out, err = run(capsys, path, "--db", db)
    assert code == 0
    assert "2 FT8 lines, 2 new" in out
    assert out.endswith("Problems: 1 (listed above)\n")
    assert err.startswith("line 2: not an ALL.TXT decode line")


def test_only_the_first_problems_are_listed(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX + b"garbage\n" * 25)
    _, out, err = run(capsys, path, "--db", db)
    assert err.count("not an ALL.TXT decode line") == cli.SHOW_PROBLEMS
    assert "... and 15 more problems" in err
    assert "Problems: 25" in out


@pytest.mark.parametrize("data, reason", [
    (b"", "no FT8 records found (read as ALL.TXT)"),
    (FT4, "no FT8 records found (read as ALL.TXT)"),
    (b"garbage\n", "no FT8 records found (read as ALL.TXT)"),
    (b"WSJT-X ADIF Export<eoh>\n", "no FT8 records found (read as ADIF)"),
])
def test_file_with_no_ft8_records_is_an_error_and_stores_nothing(tmp_path, db, capsys, data, reason):
    code, out, err = run(capsys, write(tmp_path, "in.txt", data), "--db", db)
    assert code == 2
    assert reason in err
    assert out == ""
    assert not db.exists()


def test_missing_file_is_an_error(tmp_path, db, capsys):
    code, _, err = run(capsys, tmp_path / "nope.txt", "--db", db)
    assert (code, err) == (2, f"ft8cast: error: {tmp_path / 'nope.txt'}: no such file\n")


def test_folder_is_an_error(tmp_path, db, capsys):
    assert run(capsys, tmp_path, "--db", db)[0] == 2


def test_db_cant_be_the_file_being_imported(tmp_path, capsys):
    path = write(tmp_path, "ALL.TXT", RX)
    code, _, err = run(capsys, path, "--db", path)
    assert code == 2
    assert "--db can't be the file being imported" in err
    assert path.read_bytes() == RX


def test_db_that_isnt_ours_is_an_error_and_left_alone(tmp_path, capsys):
    other = write(tmp_path, "notes.txt", b"not a database\n")
    code, _, err = run(capsys, write(tmp_path, "ALL.TXT", RX), "--db", other)
    assert code == 2
    assert "isn't an ft8cast database" in err
    assert other.read_bytes() == b"not a database\n"


def test_oversized_adif_is_refused(tmp_path, db, capsys, monkeypatch):
    monkeypatch.setattr(logs, "MAX_ADIF_BYTES", len(ADIF) - 1)
    code, _, err = run(capsys, write(tmp_path, "log.adi", ADIF), "--db", db)
    assert code == 2
    assert "not an ADIF log?" in err


def test_unreadable_file_is_an_error(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX)
    path.chmod(0)
    try:
        code, _, err = run(capsys, path, "--db", db)
    finally:
        path.chmod(0o600)
    assert code == 2
    assert "Permission denied" in err


@pytest.mark.parametrize("argv", [[], ["import"], ["frobnicate"]])
def test_usage_errors_exit_2(argv, capsys):
    assert main(argv) == 2
    assert "usage: ft8cast" in capsys.readouterr().err


def test_help_exits_0(capsys):
    assert main(["import", "--help"]) == 0
    assert "never changed" in capsys.readouterr().out


# --- ft8cast forecast ---

NOW = datetime(2026, 10, 27, 15, 5, tzinfo=UTC)


@pytest.fixture
def setup(tmp_path, db, monkeypatch):
    """A database with 5 days of 20 m at 15 UTC, a fixed clock and an empty .env."""
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    conn = open_db(db)
    newest = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
    save_decodes(conn, [Decode(newest - timedelta(days=n), 14_074_000, False, -10 - n, f"N{n}CALL",
                               "JJ01", f"CQ N{n}CALL JJ01") for n in range(5)])
    # N0CALL again the next day back: a second day, so its grid can set Farthest.
    save_decodes(conn, [Decode(newest - timedelta(days=1), 14_074_000, False, -12, "N0CALL", "JJ01", "CQ N0CALL JJ01")])
    conn.close()
    return tmp_path / ".env"


def forecast_run(capsys, db, *args):
    code = main(["forecast", "--db", str(db), *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_forecast_prints_the_table(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    code, out, err = forecast_run(capsys, db)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "FT8 forecast for 15:00-15:59 UTC (your data: 30 days through 2026-10-25 15:30 UTC)"
    assert lines[2] == "      ----- Stations heard -----"
    assert lines[3] == "Band   Typical day  30-day total  Median SNR          Farthest  30-day contacts"
    assert "20m              1             5      -12 dB      69 mi (JJ01)                0" in lines
    assert "40m   not enough data (0 days listening; need 5)" in lines
    # The table, then the note on the two station columns, last.
    assert lines[-5:] == ["10m   not enough data (0 days listening; need 5)", "",
                          "Typical day: stations heard on the median day you listened at this hour.",
                          "30-day total: different stations heard over the whole 30 days.",
                          "Farthest: a station heard with the same grid square on 2+ days at this hour; "
                          "the square is theirs."]
    assert "Note:" not in out and "MY_GRID" not in out


def test_forecast_uses_the_current_utc_hour_by_default(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    out = forecast_run(capsys, db)[1]
    assert out.startswith("FT8 forecast for 03:00-03:59 UTC")
    assert "20m   not enough data (0 days listening; need 5)" in out


def test_forecast_hour_option(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    assert forecast_run(capsys, db, "--hour", "15")[1].startswith("FT8 forecast for 15:00-15:59 UTC")


def test_forecast_all_hours(setup, db, capsys):
    conn = open_db(db)  # 03 UTC, outside the fixture's 15 UTC hour: counts only for all hours
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 3, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL/P",
                               None, "CQ N0CALL/P")])
    conn.close()
    code, out, _ = forecast_run(capsys, db, "--hour", "all")
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == "FT8 forecast for all hours (00:00-23:59 UTC) (your data: 30 days through 2026-10-25 15:30 UTC)"
    assert any(line.startswith("20m ") and line.split()[2] == "6" for line in lines)  # 30-day total
    assert "Typical day: stations heard on the median day you listened, at any hour." in lines
    assert "Farthest: a station heard with the same grid square on 2+ days, at any hour; the square is theirs." in lines


def test_one_day_is_singular(setup, db, capsys):
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 7_074_000, False, -5,
                               "N0CALL", None, "CQ N0CALL")])
    conn.close()
    out = forecast_run(capsys, db)[1]
    assert "40m   not enough data (1 day listening; need 5)" in out
    assert "30m   not enough data (0 days listening; need 5)" in out


def test_without_my_grid_farthest_is_blank_and_explained(setup, db, capsys):
    out = forecast_run(capsys, db)[1]
    assert "20m              1             5      -12 dB                 -                0" in out
    assert "Farthest needs your grid: set MY_GRID in .env (see .env.example)." in out


@pytest.mark.parametrize("env", ["MY_GRID=\n", "# MY_GRID=JJ00\n", "OTHER=1\n"])
def test_empty_or_commented_my_grid_counts_as_unset(setup, db, capsys, env):
    setup.write_text(env)
    code, out, _ = forecast_run(capsys, db)
    assert code == 0 and "Farthest needs your grid" in out


@pytest.mark.parametrize("env", ['MY_GRID="JJ00"\n', "MY_GRID = jj00  # home\n", "MY_GRID=JJ00ab\n"])
def test_my_grid_formats_people_write(setup, db, capsys, env):
    setup.write_text(env)
    assert "69 mi (JJ01)" in forecast_run(capsys, db)[1]


@pytest.mark.parametrize("bad", ["ZZ99", "FN3", "my house"])
def test_invalid_my_grid_is_an_error(setup, db, capsys, bad):
    setup.write_text(f"MY_GRID={bad}\n")
    code, out, err = forecast_run(capsys, db)
    assert (code, out) == (2, "")
    assert "MY_GRID in .env:" in err and "isn't a grid square" in err


def test_stale_data_gets_a_note(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 2, 15, 31, tzinfo=UTC))  # 8 days on
    assert "Note: your newest data is 8 days old; copy a fresh ALL.TXT over and import it." \
        in forecast_run(capsys, db)[1]


def test_seven_day_old_data_gets_no_note(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 1, 15, 31, tzinfo=UTC))
    assert "Note:" not in forecast_run(capsys, db)[1]


def test_forecast_without_a_database_is_an_error_and_creates_none(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    missing = tmp_path / "none.sqlite"
    code, _, err = forecast_run(capsys, missing)
    assert code == 2 and "run `ft8cast import` first" in err
    assert not missing.exists()


def test_forecast_with_only_adif_imported_is_an_error(tmp_path, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    run(capsys, write(tmp_path, "log.adi", ADIF), "--db", db)
    code, _, err = forecast_run(capsys, db)
    assert code == 2 and "no ALL.TXT data imported yet" in err


@pytest.mark.parametrize("hour", ["24", "-1", "x", "1.5", "007", "１", "ALL", "al"])
def test_bad_hour_is_a_usage_error(setup, db, capsys, hour):
    code, _, err = forecast_run(capsys, db, "--hour", hour)
    assert code == 2 and "must be a UTC hour from 0 to 23" in err


@pytest.mark.parametrize("hour", ["0", "00", "23", "9", "all"])
def test_good_hours(setup, db, capsys, hour):
    assert forecast_run(capsys, db, "--hour", hour)[0] == 0


def test_commands_never_use_the_network(setup, db, tmp_path, capsys, monkeypatch):
    # Decided 2026-10-28: no web calls. Any attempt to connect fails this test.
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("ft8cast tried to use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    setup.write_text("MY_GRID=JJ00\n")
    assert run(capsys, write(tmp_path, "ALL.TXT", RX), "--db", db)[0] == 0
    assert run(capsys, write(tmp_path, "log.adi", ADIF), "--db", db)[0] == 0
    assert forecast_run(capsys, db)[0] == 0
