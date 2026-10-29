"""ft8cast import and forecast: output, exit codes and file handling (README acceptance criteria)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from ft8_forecast import Contact, Decode, cli, logs
from ft8_forecast.cli import main
from ft8_forecast.store import open_db, save_contacts, save_decodes

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


HEADER = "Band  Typical day  Total heard  Signal  Heard out to  Worked out to  Contacts"
LEGEND = ["Typical day: median stations per day you listened. Total heard: over 30 days.",
          "Signal: median SNR. Heard out to: same station and grid on 2+ days."]


def row(lines, band):
    """A table row's cells, checked to line up with the header (every column is right-aligned)."""
    found = next(line for line in lines if line.startswith(band + " "))
    assert len(found) == len(HEADER)
    return found.split()


def test_forecast_prints_the_best_bet_and_table(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    code, out, err = forecast_run(capsys, db)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[:6] == ["FT8 forecast for 15:00-15:59 UTC (your last 30 days, through 2026-10-25 15:30 UTC)", "",
                         "Best bet (busiest): 20m - about 1 station on a typical day", "",
                         HEADER, lines[5]]
    assert row(lines, "20m") == ["20m", "1", "5", "-12", "dB", "69", "mi", "-", "0"]  # miles only, no grid
    assert lines[6:] == ["", "Too little data at this hour (need 5 days): 160m 80m 40m 30m 17m 15m 12m 10m (0 days)",
                         "", *LEGEND, "", "Every hour at a glance: ft8cast overview"]
    assert "Note:" not in out and "MY_GRID" not in out and "JJ" not in out


def test_forecast_shows_farthest_contacts_and_ranks_by_contacts(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, False, -5, f"N{n}CALL/P",
                               None, f"CQ N{n}CALL/P") for n in range(5)])  # 40m: 5 days, 1 station a day
    save_contacts(conn, [
        Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 7_074_000, "JJ01"),
        Contact("N0CALL/P", datetime(2026, 10, 25, 3, 0, tzinfo=UTC), 7_074_000, "JJ10"),  # other hour
        Contact("N0CALL/M", datetime(2026, 10, 23, 15, 0, tzinfo=UTC), 7_074_000, None),  # no grid
        Contact("N0CALL/QRP", datetime(2026, 4, 8, 15, 0, tzinfo=UTC), 14_074_000, "JJ30"),  # before the window
    ])
    conn.close()
    lines = forecast_run(capsys, db)[1].splitlines()
    # Busiest (default): 20m and 40m tie at 1 station a day; 40m's 2 contacts put it first.
    assert lines[2] == "Best bet (busiest): 40m - about 1 station on a typical day; worked out to 69 mi"
    assert [line.split()[0] for line in lines[5:7]] == ["40m", "20m"]
    assert row(lines, "40m") == ["40m", "1", "5", "-5", "dB", "-", "69", "mi", "2"]
    assert lines[-7:] == ["", "Farthest contact ever: 415 mi on 20m, 2026-04-08",
                          "", "Farthest contact by day (30 days, any hour):",
                          "Date        Band  Farthest",
                          "2026-10-25  40m     138 mi",
                          "2026-10-23  -            -"]
    out = forecast_run(capsys, db, "--rank", "contacts")[1]
    assert "Best bet (most contacts): 40m - 2 contacts in 30 days; worked out to 69 mi" in out
    assert "N0CALL" not in out and "JJ" not in out  # no callsigns; grids only on the web page


def test_rank_contacts_without_contacts_names_no_band(setup, db, capsys):
    out = forecast_run(capsys, db, "--rank", "contacts")[1]
    assert "Best bet (most contacts): none - no contacts at this hour in these 30 days" in out


def test_no_band_with_enough_data_has_no_table_or_legend(setup, db, capsys):
    conn = open_db(db)  # 40m on 1 day at 15 UTC; 20m has 5
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 7_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL")])
    conn.close()
    lines = forecast_run(capsys, db, "--hour", "15")[1].splitlines()
    assert LEGEND[0] in lines  # 20m has a table row
    conn = open_db(db)
    conn.execute("DELETE FROM decodes WHERE dial_hz = 14074000")
    conn.execute("INSERT INTO decodes VALUES ('2026-10-25 15:59:00', 14074000, 1, 0, 'N0CALL', NULL, 'CQ')")
    conn.commit()
    conn.close()
    lines = forecast_run(capsys, db, "--hour", "15")[1].splitlines()
    assert lines[2] == "Best bet (busiest): none yet - no band has 5 days of listening at this hour"
    assert HEADER not in lines and LEGEND[0] not in lines
    assert "Too little data at this hour (need 5 days): 160m 80m 30m 17m 15m 12m 10m (0 days), 40m 20m (1 day)" in lines


def test_no_listening_at_this_hour_says_so_once(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    lines = forecast_run(capsys, db)[1].splitlines()
    assert "Every hour at a glance: ft8cast overview" in lines  # most useful when this hour is empty
    assert lines[2] == "Best bet (busiest): none - no listening at this hour in these 30 days"
    assert not any(line.startswith("Too little data") for line in lines)
    assert HEADER not in lines and LEGEND[0] not in lines


@pytest.mark.parametrize("rank", ["", "Busiest", "most", "contacts "])
def test_bad_rank_is_a_usage_error(setup, db, capsys, rank):
    code, _, err = forecast_run(capsys, db, "--rank", rank)
    assert code == 2 and "must be 'busiest' or 'contacts'" in err


def test_forecast_uses_the_current_utc_hour_by_default(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    out = forecast_run(capsys, db)[1]
    assert out.startswith("FT8 forecast for 03:00-03:59 UTC")


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
    assert lines[0] == "FT8 forecast for all hours (00:00-23:59 UTC) (your last 30 days, through 2026-10-25 15:30 UTC)"
    assert row(lines, "20m")[2] == "6"  # total heard
    assert "Too little data (need 5 days): 160m 80m 40m 30m 17m 15m 12m 10m (0 days)" in lines
    assert "at this hour" not in out


def test_thin_bands_are_grouped_by_days_and_one_day_is_singular(setup, db, capsys):
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), dial, False, -5, "N0CALL", None,
                               "CQ N0CALL") for dial, days in [(7_074_000, 1), (28_074_000, 3), (21_074_000, 3)]
                        for n in range(days)])
    conn.close()
    out = forecast_run(capsys, db)[1]
    assert "Too little data at this hour (need 5 days): 160m 80m 30m 17m 12m (0 days), 40m (1 day), 15m 10m (3 days)" in out


def test_without_my_grid_distances_are_blank_and_explained(setup, db, capsys):
    lines = forecast_run(capsys, db)[1].splitlines()
    assert row(lines, "20m") == ["20m", "1", "5", "-12", "dB", "-", "-", "0"]
    assert lines[-1] == "Heard out to and Worked out to need your grid: set MY_GRID in .env (see .env.example)."
    assert not any("Farthest contact" in line for line in lines)


# --- ft8cast overview ---

def overview_run(capsys, db, *args):
    code = main(["overview", "--db", str(db), *args])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def overview_db(setup, db):
    """setup's 20m at 15 UTC (1 station a day), plus 40m at 15 UTC (2 a day, 1 contact) and 20m once at 03 UTC."""
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, False, -5, call, None,
                               f"CQ {call}") for n in range(5) for call in ("N0CALL/P", "N0CALL/M")])
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 3, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL")])
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, None),
                         Contact("N0CALL/P", datetime(2026, 10, 24, 15, 0, tzinfo=UTC), 14_074_000, None)])
    conn.close()


def test_overview_prints_an_hour_by_band_grid(overview_db, db, capsys):
    code, out, err = overview_run(capsys, db)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "24-hour overview (your last 30 days, through 2026-10-25 15:30 UTC)",
        "Typical-day stations; * = best bet (busiest); . = too little data", "",
        "UTC   40m    20m",
        "15      2*     1", "",
        # Rows and columns that would be all dots are summed up instead.
        "Too little data on every band: 03",
        "Hours with no listening: 00-02, 04-14, 16-23",
        "Too little data at every hour: 160m 80m 30m 17m 15m 12m 10m"]


def test_overview_keeps_a_dot_for_a_band_with_data_at_other_hours(overview_db, db, capsys):
    conn = open_db(db)  # 20m at 03 UTC on 5 days: 03 gets a row, and 40m shows "." there
    save_decodes(conn, [Decode(datetime(2026, 10, 24 - n, 3, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL") for n in range(4)])
    conn.close()
    lines = overview_run(capsys, db)[1].splitlines()
    assert lines[3:6] == ["UTC   40m    20m", "03      .      1*", "15      2*     1"]
    assert not any(line.startswith("Too little data on every band") for line in lines)


def test_overview_with_no_band_ready_at_any_hour(setup, db, capsys):
    conn = open_db(db)
    conn.execute("DELETE FROM decodes WHERE time < '2026-10-23'")  # 20m now has 3 days
    conn.commit()
    conn.close()
    lines = overview_run(capsys, db)[1].splitlines()
    assert lines[2:] == ["", "No band has 5 days of listening at any hour yet.", "",
                         "Hours with no listening: 00-14, 16-23"]


def test_overview_matches_the_forecast_for_each_hour(overview_db, db, capsys):
    grid = overview_run(capsys, db)[1].splitlines()[4].split()
    forecast_lines = forecast_run(capsys, db, "--hour", "15")[1].splitlines()
    assert grid[1] == row(forecast_lines, "40m")[1] + "*" and grid[2] == row(forecast_lines, "20m")[1]
    assert forecast_lines[2].startswith("Best bet (busiest): 40m")


def test_overview_without_a_database_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    code, _, err = overview_run(capsys, tmp_path / "none.sqlite")
    assert code == 2 and "no database" in err and not (tmp_path / "none.sqlite").exists()


def test_overview_bad_rank_is_a_usage_error(overview_db, db, capsys):
    code, _, err = overview_run(capsys, db, "--rank", "most")
    assert code == 2 and "must be 'busiest' or 'contacts'" in err


def test_overview_stale_data_gets_a_note(overview_db, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW + timedelta(days=10))
    assert "Note: your newest data is 11 days old" in overview_run(capsys, db)[1]


@pytest.mark.parametrize("hours, text", [([0, 1, 2, 3, 22, 23], "00-03, 22-23"), ([5], "05"), ([1, 3], "01, 03"),
                                         (list(range(24)), "00-23")])
def test_hour_ranges(hours, text):
    assert cli.hour_ranges(hours) == text


@pytest.mark.parametrize("env", ["MY_GRID=\n", "# MY_GRID=JJ00\n", "OTHER=1\n"])
def test_empty_or_commented_my_grid_counts_as_unset(setup, db, capsys, env):
    setup.write_text(env)
    code, out, _ = forecast_run(capsys, db)
    assert code == 0 and "need your grid" in out


@pytest.mark.parametrize("env", ['MY_GRID="JJ00"\n', "MY_GRID = jj00  # home\n", "MY_GRID=JJ00ab\n"])
def test_my_grid_formats_people_write(setup, db, capsys, env):
    setup.write_text(env)
    assert row(forecast_run(capsys, db)[1].splitlines(), "20m")[5:7] == ["69", "mi"]  # Heard out to


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
