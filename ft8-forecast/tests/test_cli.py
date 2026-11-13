"""ft8cast import and forecast: output, exit codes and file handling (README acceptance criteria)."""

import os
import re
import sys
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ignores chmod's read permission bits")
def test_unreadable_file_is_an_error(tmp_path, db, capsys):
    path = write(tmp_path, "ALL.TXT", RX)
    path.chmod(0)
    try:
        code, _, err = run(capsys, path, "--db", db)
    finally:
        path.chmod(0o600)
    assert code == 2
    assert "Permission denied" in err


@pytest.mark.parametrize("argv", [[], ["frobnicate"], ["watch", "--every"]])
def test_usage_errors_exit_2(argv, capsys):
    assert main(argv) == 2
    assert "usage: ft8cast" in capsys.readouterr().err


def test_help_exits_0(capsys):
    assert main(["import", "--help"]) == 0
    assert "never changed" in capsys.readouterr().out


# --- ft8cast import from a folder (--dir or LOG_DIR) ---

@pytest.fixture
def logdir(tmp_path, monkeypatch):
    """A folder with ALL.TXT and an ADIF log, and an empty .env next to it."""
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    folder = tmp_path / "wsjt x"  # a space, like "/Volumes/WSJT-X share"
    folder.mkdir()
    (folder / "ALL.TXT").write_bytes(RX + RX2)
    (folder / "wsjtx_log.adi").write_bytes(ADIF)
    return folder


def test_import_dir_imports_every_log(logdir, db, capsys):
    code, out, err = run(capsys, "--dir", logdir, "--db", db)
    assert (code, err) == (0, "")
    assert "ALL.TXT (ALL.TXT): 2 FT8 lines, 2 new, 0 already stored" in out
    assert "wsjtx_log.adi (ADIF): 1 FT8 contacts, 1 new, 0 already stored" in out


@pytest.mark.parametrize("value", ["{dir}", '"{dir}"', "{dir}  # the share", "wsjt x"])
def test_import_with_no_file_uses_log_dir(logdir, db, capsys, value):
    cli.ENV_FILE.write_text("MY_GRID=JJ00\nLOG_DIR=" + value.format(dir=logdir) + "\n")  # relative: next to .env
    code, out, _ = run(capsys, "--db", db)
    assert code == 0 and "2 new" in out and "1 new" in out


def test_log_dir_expands_home(logdir, db, capsys, monkeypatch):
    monkeypatch.setenv("HOME", str(logdir.parent))
    monkeypatch.setenv("USERPROFILE", str(logdir.parent))  # what ~ means on Windows
    cli.ENV_FILE.write_text("LOG_DIR=~/wsjt x\n")
    assert run(capsys, "--db", db)[0] == 0


def test_import_with_nothing_to_import_says_how(logdir, db, capsys):
    code, _, err = run(capsys, "--db", db)
    assert code == 2 and "give a file or --dir, or set LOG_DIR in .env" in err


def test_file_and_dir_together_is_a_usage_error(logdir, db, capsys):
    code, _, err = run(capsys, logdir / "ALL.TXT", "--dir", logdir, "--db", db)
    assert code == 2 and "not both" in err


def test_import_dir_that_isnt_there_is_an_error_and_stores_nothing(logdir, db, capsys):
    code, _, err = run(capsys, "--dir", logdir / "nope", "--db", db)
    assert code == 2 and "isn't a folder" in err and not db.exists()


def test_import_dir_with_a_bad_file_imports_the_rest_and_exits_2(logdir, db, capsys):
    (logdir / "broken.adi").write_bytes(b"<call:6>N0CALL <mode:3>FT4 <eor>")
    code, out, err = run(capsys, "--dir", logdir, "--db", db)
    assert code == 2
    assert "ft8cast: error: broken.adi: no FT8 records found (read as ADIF)" in err
    assert "ALL.TXT (ALL.TXT): 2 FT8 lines, 2 new" in out


# --- ft8cast watch ---

def watch_run(capsys, monkeypatch, *args, changes=()):
    """Run watch; each sleep applies the next change, and the sleep after the last is Ctrl+C."""
    sleeps = []
    pending = list(changes)

    def sleep(seconds):
        sleeps.append(seconds)
        if not pending:
            raise KeyboardInterrupt
        pending.pop(0)()
    monkeypatch.setattr(cli, "_sleep", sleep)
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 10, 29, 16, 42, tzinfo=UTC))
    code = main(["watch", *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err, sleeps


def test_watch_imports_then_checks_until_ctrl_c(logdir, db, capsys, monkeypatch):
    def more():
        with (logdir / "ALL.TXT").open("ab") as file:
            file.write(RX.replace(b"143015", b"143030"))
    code, out, err, sleeps = watch_run(capsys, monkeypatch, "--dir", logdir, "--db", db, changes=[more])
    assert (code, err) == (0, "")
    assert out.splitlines() == [f"Watching {logdir} every 60 s; Ctrl+C stops.",
                                "16:42 UTC  ALL.TXT: 2 new", "16:42 UTC  wsjtx_log.adi: 1 new",
                                "16:42 UTC  ALL.TXT: 1 new", "Stopped."]
    assert sleeps == [60, 60]


def test_watch_uses_log_dir_and_every(logdir, db, capsys, monkeypatch):
    cli.ENV_FILE.write_text(f"LOG_DIR={logdir}\n")
    code, out, _, sleeps = watch_run(capsys, monkeypatch, "--every", "10", "--db", db)
    assert code == 0 and out.startswith(f"Watching {logdir} every 10 s") and sleeps == [10]


@pytest.mark.parametrize("every", ["9", "3601", "abc", "", "1.5", "-60"])
def test_watch_every_must_be_10_to_3600(logdir, db, capsys, monkeypatch, every):
    code, _, err, _ = watch_run(capsys, monkeypatch, "--dir", logdir, "--every", every, "--db", db)
    assert code == 2 and "must be 10 to 3600 seconds" in err


def test_watch_needs_a_folder_that_exists_at_start(logdir, db, capsys, monkeypatch):
    code, _, err, sleeps = watch_run(capsys, monkeypatch, "--dir", logdir / "nope", "--db", db)
    assert code == 2 and "isn't a folder" in err and sleeps == []
    code, _, err, _ = watch_run(capsys, monkeypatch, "--db", db)  # no --dir, no LOG_DIR
    assert code == 2 and "give --dir or set LOG_DIR in .env" in err


def test_watch_keeps_going_when_the_folder_goes_away(logdir, db, capsys, monkeypatch, tmp_path):
    def unmount():
        logdir.rename(tmp_path / "away")
    def remount():
        (tmp_path / "away").rename(logdir)
    code, out, _, _ = watch_run(capsys, monkeypatch, "--dir", logdir, "--db", db, changes=[unmount, remount])
    lines = out.splitlines()
    assert code == 0 and lines[-1] == "Stopped."
    assert lines[3].startswith("16:42 UTC  folder not reachable") and lines[4] == "16:42 UTC  folder is reachable again"


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


HEADER = ["      Stations  Stations  Median   Farthest   Farthest  Contacts",
          "Band   per day   30 days  SNR dB      heard     worked   30 days"]
LEGEND = ["Stations per day: the median (middle value) over the days you listened.",
          "Median SNR: middle signal-to-noise ratio of all decodes; higher is stronger.",
          "Farthest heard: same station and grid on 2+ days."]
ANSWERED = "Replies to you" + " " * 12 + "Calling CQ" + " " * 9 + "Answering CQs"
ANSWERED_NOTES = ["Replies to you: a decode addressed to you within 30 s.",
                  "Answering CQs: you calling a station (usually answering its CQ).",
                  "Got more replies: shown when chance alone would give that gap under 1 in 20."]


def unwrap(out):
    """Output lines with fit()'s wrapped continuations (2-space indent) joined back on."""
    lines = []
    for line in out.splitlines():
        if re.match(r"  \S", line) and lines:
            lines[-1] += " " + line[2:]
        else:
            lines.append(line)
    return lines


def row(lines, band):
    """A table row's cells, checked to line up with the header (every column is right-aligned)."""
    found = next(line for line in lines if line.startswith(band + " "))
    assert len(found) == len(HEADER[0]) == len(HEADER[1])
    return found.split()


def test_forecast_prints_the_best_bet_and_table(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    code, out, err = forecast_run(capsys, db)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[:8] == ["FT8 forecast for 15:00-15:59 UTC, 11 am EDT (your last 30 days, through 2026-10-25 15:30 UTC, 2 days ago)", "",
                         "Best bet (busiest): 20m - about 1 station on a typical day",
                         "This is 20m's busiest hour", "",
                         *HEADER, lines[7]]
    assert row(lines, "20m") == ["20m", "1", "5", "-12", "69", "mi", "-", "0"]  # miles only, no grid
    assert lines[8:] == ["", "Too little data at this hour (need 5 days): 160m 80m 40m 30m 17m 15m 12m 10m (0 days)",
                         "", *DETAILS_HINT]
    assert "Note:" not in out and "MY_GRID" not in out and "JJ" not in out


DETAILS_HINT = ["Column notes and farthest contacts: add --details", "Every hour at a glance: ft8cast overview"]


def test_forecast_leaves_the_details_out_by_default(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    lines = forecast_run(capsys, db)[1].splitlines()
    assert LEGEND[0] not in lines
    assert not any(line.startswith(("Farthest contact ever", "Farthest contact by day")) for line in lines)
    assert "Farthest contact at this hour: 69 mi on 20m" in lines  # a summary line, so it stays
    assert lines[-2:] == DETAILS_HINT


def test_details_adds_the_notes_and_farthest_contacts(setup, db, capsys):
    setup.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    lines = forecast_run(capsys, db, "--details")[1].splitlines()
    assert LEGEND[0] in lines and DETAILS_HINT[0] not in lines
    assert "Farthest contact ever: 69 mi on 20m, 2026-10-25" in lines
    assert "Farthest contact by day (30 days, any hour):" in lines


def test_no_details_hint_when_nothing_is_left_out(setup, db, capsys):
    conn = open_db(db)  # no band with enough data at 03 UTC, no contacts
    conn.close()
    lines = forecast_run(capsys, db, "--hour", "3")[1].splitlines()
    assert DETAILS_HINT[0] not in lines and DETAILS_HINT[1] in lines


def test_forecast_shows_how_many_calls_were_answered(setup, db, capsys):
    conn = open_db(db)
    cq = datetime(2026, 10, 24, 15, 10, tzinfo=UTC)
    save_decodes(conn, [Decode(cq, 14_074_000, True, 0, "N0CALL/P", "AA00", "CQ N0CALL/P AA00"),
                        Decode(cq + timedelta(seconds=15), 14_074_000, False, -9, "N1CALL", "FN31", "N0CALL/P N1CALL FN31"),
                        Decode(cq + timedelta(seconds=30), 14_074_000, True, 0, "N0CALL/P", "AA00", "CQ N0CALL/P AA00"),
                        Decode(cq + timedelta(seconds=60), 14_074_000, True, 0, "N0CALL/P", "AA00", "N2CALL N0CALL/P AA00")])
    conn.close()
    lines = forecast_run(capsys, db, "--details")[1].splitlines()
    top = lines.index(ANSWERED)
    assert lines[top - 1:top + 3] == ["", ANSWERED, "20m" + " " * 21 + "1 of 2 (50%)" + " " * 11 + "0 of 1 (0%)", ""]
    legend = lines.index(LEGEND[-1])
    assert lines[legend + 1:legend + 4] == ANSWERED_NOTES


def test_no_answered_table_without_your_tx(setup, db, capsys):
    out = forecast_run(capsys, db, "--details")[1]
    assert ANSWERED not in out and ANSWERED_NOTES[0] not in out


def test_four_digit_call_counts_line_up(setup, db, capsys):
    """Real all-hours data reaches "269 of 1,959" (2026-10-29)."""
    conn = open_db(db)
    start = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    cqs = [start + timedelta(seconds=30 * n) for n in range(1959)]
    save_decodes(conn, [Decode(when, 14_074_000, True, 0, "N0CALL/P", "AA00", "CQ N0CALL/P AA00") for when in cqs])
    save_decodes(conn, [Decode(when + timedelta(seconds=15), 14_074_000, False, -9, "N1CALL", "FN31", "N0CALL/P N1CALL FN31")
                        for when in cqs[:269]])
    conn.close()
    lines = forecast_run(capsys, db, "--hour", "all")[1].splitlines()
    found = lines[lines.index(ANSWERED) + 1]
    assert found == "20m" + " " * 15 + "269 of 1,959 (14%)" + " " * 21 + "-"
    assert len(found) == len(ANSWERED)


def test_forecast_says_which_bands_got_busier_or_quieter(setup, db, capsys):
    newest = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
    conn = open_db(db)  # 20m had 4 a day 15+ days back (now 1); 15m went from 2 to 6
    save_decodes(conn, [Decode(newest - timedelta(days=n), 14_074_000, False, -10, f"N{i}CALL/M", None, f"CQ N{i}CALL/M")
                        for n in (15, 16, 17) for i in range(4)])
    save_decodes(conn, [Decode(newest - timedelta(days=n), 21_074_000, False, -10, f"N{i}CALL", None, f"CQ N{i}CALL")
                        for n, count in [(0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (15, 2), (16, 2), (17, 2)]
                        for i in range(count)])
    conn.close()
    lines = forecast_run(capsys, db)[1].splitlines()
    assert "Busier in the last 15 days: 15m (6 a day, up from 2)" in lines
    assert "Quieter in the last 15 days: 20m (1 a day, down from 4)" in lines


def test_long_summary_lines_wrap_between_bands(setup, db, capsys):
    """Over 80 characters, a line breaks after a comma between items, never inside brackets."""
    newest = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
    conn = open_db(db)  # 15m, 17m and 10m each went from 2 to 6 a day
    save_decodes(conn, [Decode(newest - timedelta(days=n), dial, False, -10, f"N{i}CALL", None, f"CQ N{i}CALL")
                        for dial in (18_100_000, 21_074_000, 28_074_000)
                        for n, count in [(0, 6), (1, 6), (2, 6), (3, 6), (4, 6), (15, 2), (16, 2), (17, 2)]
                        for i in range(count)])
    conn.close()
    lines = forecast_run(capsys, db)[1].splitlines()
    top = next(i for i, line in enumerate(lines) if line.startswith("Busier"))
    assert lines[top:top + 2] == ["Busier in the last 15 days: 17m (6 a day, up from 2), 15m (6 a day, up from 2),",
                                  "  10m (6 a day, up from 2)"]


def test_no_trend_line_without_a_clear_change(setup, db, capsys):
    assert "in the last 15 days" not in forecast_run(capsys, db)[1]


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
    lines = forecast_run(capsys, db, "--details")[1].splitlines()
    # Busiest (default): 20m and 40m tie at 1 station a day; 40m's 2 contacts put it first.
    assert lines[2] == "Best bet (busiest): 40m - about 1 station on a typical day; worked out to 69 mi"
    top = lines.index(HEADER[1]) + 1
    assert [line.split()[0] for line in lines[top:top + 2]] == ["40m", "20m"]
    assert row(lines, "40m") == ["40m", "1", "5", "-5", "-", "69", "mi", "2"]
    assert lines[-7:] == ["", "Farthest contact ever: 415 mi on 20m, 2026-04-08",
                          "", "Farthest contact by day (30 days, any hour):",
                          "Date        Band  Farthest",
                          "2026-10-25  40m     138 mi",
                          "2026-10-23  -            -"]
    out = forecast_run(capsys, db, "--rank", "contacts")[1]
    assert "Best bet (most contacts): 40m - 2 contacts in 30 days; worked out to 69 mi" in out
    assert "N0CALL" not in out and "JJ" not in out  # no callsigns; grids only on the web page


@pytest.fixture
def summary_db(setup, db):
    """setup's 20m at 15 UTC (1 station a day), plus 40m: 2 a day at 15 UTC, 3 a day at 14 UTC,
    and one 40m contact at 15 UTC with a grid 138 mi from JJ00."""
    setup.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, hour, 0, tzinfo=UTC), 7_074_000, False, -5, f"N{i}CALL/P",
                               None, f"CQ N{i}CALL/P")
                        for n in range(5) for hour, stations in [(15, 2), (14, 3)] for i in range(stations)])
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 7_074_000, "JJ10")])
    conn.close()


def test_summary_under_the_best_bet(summary_db, db, capsys):
    lines = unwrap(forecast_run(capsys, db, "--hour", "15")[1])
    assert lines[2:7] == ["Best bet (busiest): 40m - about 2 stations on a typical day; worked out to 138 mi",
                          "Next: 20m - about 1 station on a typical day",
                          "40m is busiest at 14 UTC (10 am EDT): about 3 stations on a typical day",
                          "Farthest contact at this hour: 138 mi on 40m",
                          ""]


def test_summary_at_the_best_bands_peak_hour(summary_db, db, capsys):
    lines = forecast_run(capsys, db, "--hour", "14")[1].splitlines()
    # No other band at 14 UTC and no contact then: just the peak line.
    assert lines[2:5] == ["Best bet (busiest): 40m - about 3 stations on a typical day",
                          "This is 40m's busiest hour", ""]


def test_summary_by_contacts(summary_db, db, capsys):
    lines = forecast_run(capsys, db, "--hour", "15", "--rank", "contacts")[1].splitlines()
    # 20m has no contacts, so there's no "Next".
    assert lines[2:6] == ["Best bet (most contacts): 40m - 1 contact in 30 days; worked out to 138 mi",
                          "This is the hour you've made the most 40m contacts",
                          "Farthest contact at this hour: 138 mi on 40m", ""]


def test_summary_for_all_hours_has_no_peak_line(summary_db, db, capsys):
    lines = unwrap(forecast_run(capsys, db, "--hour", "all")[1])
    assert lines[2:6] == ["Best bet (busiest): 40m - about 3 stations on a typical day; worked out to 138 mi",
                          "Next: 20m - about 1 station on a typical day",
                          "Farthest contact in these 30 days: 138 mi on 40m", ""]


def test_no_summary_without_a_best_bet(summary_db, db, capsys):
    lines = forecast_run(capsys, db, "--hour", "3")[1].splitlines()
    assert lines[2].startswith("Best bet (busiest): none") and lines[3] == ""


def test_next_hours_under_the_best_bet_even_when_this_hour_has_none(summary_db, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=13))
    lines = forecast_run(capsys, db)[1].splitlines()
    assert lines[2].startswith("Best bet (busiest): none")
    assert lines[3:5] == ["Later: 14 UTC (10 am EDT) 40m, 15 UTC (11 am EDT) 40m", ""]


def test_next_hours_says_none_for_an_hour_without_a_pick(summary_db, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=14))
    lines = unwrap(forecast_run(capsys, db)[1])
    assert lines[3] == "Later: 15 UTC (11 am EDT) 40m, 16 UTC (12 pm EDT) none"
    # At 15 UTC neither 16 nor 17 has a pick, so there's no line: test_summary_under_the_best_bet.


@pytest.mark.parametrize("hour", ["14", "all"])
def test_next_hours_only_for_the_current_hour(summary_db, db, capsys, monkeypatch, hour):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=13))  # 14 and 15 would have picks
    assert "Later:" not in forecast_run(capsys, db, "--hour", hour)[1]


def test_next_hours_follow_the_ranking(summary_db, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=13))
    # By contacts only 15 UTC has a pick: 14 UTC has 40m stations but no contacts.
    assert "Later: 14 UTC (10 am EDT) none, 15 UTC (11 am EDT) 40m" in unwrap(
        forecast_run(capsys, db, "--rank", "contacts")[1])


def test_next_hours_wraps_past_midnight(setup, db, capsys, monkeypatch):
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 26 - n, 0, 0, tzinfo=UTC), 7_074_000, False, -5, "N1CALL",
                               None, "CQ N1CALL") for n in range(5)])
    conn.close()
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=23))
    lines = unwrap(forecast_run(capsys, db)[1])
    assert "Later: 00 UTC (8 pm EDT) 40m, 01 UTC (9 pm EDT) none" in lines


def test_rank_contacts_without_contacts_names_no_band(setup, db, capsys):
    out = forecast_run(capsys, db, "--rank", "contacts")[1]
    assert "Best bet (most contacts): none - no contacts at this hour in these 30 days" in out


def test_no_band_with_enough_data_has_no_table_or_legend(setup, db, capsys):
    conn = open_db(db)  # 40m on 1 day at 15 UTC; 20m has 5
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 7_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL")])
    conn.close()
    lines = forecast_run(capsys, db, "--hour", "15", "--details")[1].splitlines()
    assert LEGEND[0] in lines  # 20m has a table row
    conn = open_db(db)
    conn.execute("DELETE FROM decodes WHERE dial_hz = 14074000")
    conn.execute("INSERT INTO decodes VALUES ('2026-10-25 15:59:00', 14074000, 1, 0, 'N0CALL', NULL, 'CQ')")
    conn.commit()
    conn.close()
    lines = unwrap(forecast_run(capsys, db, "--hour", "15", "--details")[1])
    assert lines[2] == "Best bet (busiest): none yet - no band has 5 days of listening at this hour"
    assert HEADER[1] not in lines and LEGEND[0] not in lines
    assert "Too little data at this hour (need 5 days): 160m 80m 30m 17m 15m 12m 10m (0 days), 40m 20m (1 day)" in lines


def test_no_listening_at_this_hour_says_so_once(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    lines = forecast_run(capsys, db)[1].splitlines()
    assert "Every hour at a glance: ft8cast overview" in lines  # most useful when this hour is empty
    assert lines[2] == "Best bet (busiest): none - no listening at this hour in these 30 days"
    assert not any(line.startswith("Too little data") for line in lines)
    assert HEADER[1] not in lines and LEGEND[0] not in lines


@pytest.mark.parametrize("rank", ["", "Busiest", "most", "contacts "])
def test_bad_rank_is_a_usage_error(setup, db, capsys, rank):
    code, _, err = forecast_run(capsys, db, "--rank", rank)
    assert code == 2 and "must be 'busiest' or 'contacts'" in err


def test_forecast_uses_the_current_utc_hour_by_default(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW.replace(hour=3))
    out = forecast_run(capsys, db)[1]
    assert out.startswith("FT8 forecast for 03:00-03:59 UTC, 11 pm EDT")


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
    assert lines[0] == "FT8 forecast for all hours (00:00-23:59 UTC) (your last 30 days, through 2026-10-25 15:30 UTC, 2 days ago)"
    assert row(lines, "20m")[2] == "6"  # total heard
    assert "Too little data (need 5 days): 160m 80m 40m 30m 17m 15m 12m 10m (0 days)" in lines
    assert "at this hour" not in out


def test_thin_bands_are_grouped_by_days_and_one_day_is_singular(setup, db, capsys):
    conn = open_db(db)
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), dial, False, -5, "N0CALL", None,
                               "CQ N0CALL") for dial, days in [(7_074_000, 1), (28_074_000, 3), (21_074_000, 3)]
                        for n in range(days)])
    conn.close()
    lines = unwrap(forecast_run(capsys, db)[1])
    assert "Too little data at this hour (need 5 days): 160m 80m 30m 17m 12m (0 days), 40m (1 day), 15m 10m (3 days)" in lines


def test_without_my_grid_distances_are_blank_and_explained(setup, db, capsys):
    lines = forecast_run(capsys, db)[1].splitlines()
    assert row(lines, "20m") == ["20m", "1", "5", "-12", "-", "-", "0"]
    assert lines[-1] == "Farthest heard and worked need your grid: set MY_GRID in .env (see .env.example)."
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
        "24-hour overview (your last 30 days, through 2026-10-25 15:30 UTC, 2 days ago)",
        "Typical-day stations; * = best bet (busiest); . = too little data; Local = EDT", "",
        "UTC Local   40m    20m",
        "15  11 am     2*     1", "",
        # Rows and columns that would be all dots are summed up instead.
        "Too little data on every band: 03 UTC (11 pm EDT)",
        "Hours with no listening: 00-02 UTC (8 pm-10 pm EDT), 04-14 UTC (12 am-10 am EDT), 16-23 UTC (12 pm-7 pm EDT)",
        "Too little data at every hour: 160m 80m 30m 17m 15m 12m 10m"]


def test_overview_keeps_a_dot_for_a_band_with_data_at_other_hours(overview_db, db, capsys):
    conn = open_db(db)  # 20m at 03 UTC on 5 days: 03 gets a row, and 40m shows "." there
    save_decodes(conn, [Decode(datetime(2026, 10, 24 - n, 3, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL") for n in range(4)])
    conn.close()
    lines = overview_run(capsys, db)[1].splitlines()
    assert lines[3:6] == ["UTC Local   40m    20m", "03  11 pm     .      1*", "15  11 am     2*     1"]
    assert not any(line.startswith("Too little data on every band") for line in lines)


def test_overview_with_no_band_ready_at_any_hour(setup, db, capsys):
    conn = open_db(db)
    conn.execute("DELETE FROM decodes WHERE time < '2026-10-23'")  # 20m now has 3 days
    conn.commit()
    conn.close()
    lines = overview_run(capsys, db)[1].splitlines()
    assert lines[2:] == ["", "No band has 5 days of listening at any hour yet.", "",
                         "Hours with no listening: 00-14 UTC (8 pm-10 am EDT), 16-23 UTC (12 pm-7 pm EDT)"]


def test_overview_rank_contacts_moves_the_star(overview_db, db, capsys):
    # Restored 2026-10-29: lost by mistake in the round-3 rewrite of these tests.
    lines = overview_run(capsys, db, "--rank", "contacts")[1].splitlines()
    assert lines[1] == "Typical-day stations; * = best bet (most contacts); . = too little data; Local = EDT"
    assert lines[4] == "15  11 am     2      1*"  # 20m has the 2 contacts at 15 UTC


def test_overview_on_a_utc_computer_has_no_local_column(overview_db, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_local_zone", lambda: ZoneInfo("UTC"))
    lines = overview_run(capsys, db)[1].splitlines()
    assert lines[1] == "Typical-day stations; * = best bet (busiest); . = too little data"
    assert lines[3:5] == ["UTC   40m    20m", "15      2*     1"]
    assert "Hours with no listening: 00-02, 04-14, 16-23" in lines  # UTC only
    assert forecast_run(capsys, db, "--hour", "15")[1].startswith("FT8 forecast for 15:00-15:59 UTC (your last")


def test_overview_matches_the_forecast_for_each_hour(overview_db, db, capsys):
    grid = overview_run(capsys, db)[1].splitlines()[4].split()
    forecast_lines = forecast_run(capsys, db, "--hour", "15")[1].splitlines()
    assert grid[:3] == ["15", "11", "am"]  # UTC, then local
    assert grid[3] == row(forecast_lines, "40m")[1] + "*" and grid[4] == row(forecast_lines, "20m")[1]
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
    assert cli.STALE_NOTE in overview_run(capsys, db)[1]


@pytest.mark.parametrize("hour, now, text", [
    (17, datetime(2026, 10, 29, 17, 49, tzinfo=UTC), "1 pm EDT"),  # UTC-4 until DST ends 2026-11-01
    (17, datetime(2026, 11, 2, 17, 0, tzinfo=UTC), "12 pm EST"),  # UTC-5 after; today's offset counts
    (16, datetime(2026, 10, 29, 9, 0, tzinfo=UTC), "12 pm EDT"),  # noon
    (4, datetime(2026, 10, 29, 9, 0, tzinfo=UTC), "12 am EDT"),  # midnight
    (3, datetime(2026, 10, 29, 9, 0, tzinfo=UTC), "11 pm EDT"),  # the evening before, locally
])
def test_local_hour(hour, now, text):
    assert cli.local_hour(hour, now) == text


def test_no_local_hour_on_a_utc_computer(monkeypatch):
    monkeypatch.setattr(cli, "_local_zone", lambda: ZoneInfo("UTC"))
    assert cli.local_hour(17, NOW) is None


class WindowsEastern(tzinfo):
    """Eastern time named the way Windows names it."""
    def utcoffset(self, dt): return timedelta(hours=-4)
    def dst(self, dt): return timedelta(hours=1)
    def tzname(self, dt): return "Eastern Daylight Time"


def test_a_long_windows_zone_name_is_shortened(monkeypatch):
    monkeypatch.setattr(cli, "_local_zone", WindowsEastern)
    assert cli.local_hour(17, NOW) == "1 pm EDT"


@pytest.mark.parametrize("newest, text", [("2026-10-27 00:01", "today"), ("2026-10-26 23:59", "yesterday"),
                                          ("2026-10-25 15:30", "2 days ago"), ("2026-09-27 15:30", "30 days ago")])
def test_data_age_counts_calendar_days(newest, text):
    assert cli.data_age(datetime.strptime(newest, "%Y-%m-%d %H:%M"), NOW) == text


def test_hour_ranges_with_local_times():
    assert cli.hour_ranges([0, 1, 2, 9], NOW) == "00-02 UTC (8 pm-10 pm EDT), 09 UTC (5 am EDT)"


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
    assert row(forecast_run(capsys, db)[1].splitlines(), "20m")[4:6] == ["69", "mi"]  # Farthest heard


@pytest.mark.parametrize("bad", ["ZZ99", "FN3", "my house"])
def test_invalid_my_grid_is_an_error(setup, db, capsys, bad):
    setup.write_text(f"MY_GRID={bad}\n")
    code, out, err = forecast_run(capsys, db)
    assert (code, out) == (2, "")
    assert "MY_GRID in .env:" in err and "isn't a grid square" in err


def test_stale_data_gets_a_note(setup, db, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 2, 15, 31, tzinfo=UTC))  # 8 days on
    assert cli.STALE_NOTE in forecast_run(capsys, db)[1]


def test_stale_note_counts_calendar_days_like_the_heading(setup, db, capsys, monkeypatch):
    # Newest decode 2026-10-25 15:30; 8 calendar days but under 8 full days later.
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 2, 9, 0, tzinfo=UTC))
    out = forecast_run(capsys, db)[1]
    assert "8 days ago" in out.splitlines()[0]
    assert "Note: this data is over a week old" in out


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
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "ALL.TXT").write_bytes(RX)
    assert run(capsys, "--dir", logs, "--db", db)[0] == 0
    monkeypatch.setattr(cli, "_sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    assert main(["watch", "--dir", str(logs), "--db", str(db)]) == 0


# --- LICENSE_CLASS (removed 2026-11-07) ---

@pytest.mark.parametrize("command", ["forecast", "overview"])
def test_an_old_license_class_line_is_ignored(setup, db, capsys, command):
    setup.write_text("LICENSE_CLASS=novice\n")  # even an invalid one, from before it was removed
    code, _, err = main([command, "--db", str(db)]), *capsys.readouterr()
    assert (code, err) == (0, "")


# --- answering vs calling CQ in the summary (README: Replies to you) ---

def opener_band(name, cqs_answered, cqs, calls_answered, calls):
    from ft8_forecast import forecast
    return forecast.BandStats(name, 5, 10.0, 0, None, None, None, None, None, 0,
                              cqs, cqs_answered, calls, calls_answered, None, None)


def test_opener_lines_name_each_band_with_a_real_difference():
    bands = [opener_band("20m", 21, 240, 10, 42),  # answering: 9% vs 24%
             opener_band("15m", 3, 22, 0, 25),  # 14% vs 0%, could be luck: left out
             opener_band("10m", 3, 124, 8, 41),  # answering: 2% vs 20%
             opener_band("40m", 20, 40, 1, 30)]  # calling: 50% vs 3%
    assert cli.opener_lines(bands) == [
        "Answering CQs got more replies than calling CQ: 20m (24% vs 9%), 10m (20% vs 2%)",
        "Calling CQ got more replies than answering CQs: 40m (50% vs 3%)"]


def test_no_opener_line_without_a_real_difference():
    assert cli.opener_lines([opener_band("15m", 3, 22, 0, 25), opener_band("20m", 0, 0, 0, 0)]) == []


def test_the_summary_says_when_answering_cqs_works_better(setup, db, capsys):
    conn = open_db(db)
    start = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
    decodes = []
    for n in range(10):  # 10 CQs, no replies
        decodes.append(Decode(start + timedelta(minutes=n), 14_074_000, True, 0, "N0CALL/P", "AA00", "CQ N0CALL/P AA00"))
    for n in range(5):  # 5 calls to a station, each answered 15 s later
        when = start + timedelta(minutes=20 + n)
        decodes += [Decode(when, 14_074_000, True, 0, "N0CALL/P", "AA00", f"N{n}CALL N0CALL/P AA00"),
                    Decode(when + timedelta(seconds=15), 14_074_000, False, -9, f"N{n}CALL", "FN31",
                           f"N0CALL/P N{n}CALL -09")]
    save_decodes(conn, decodes)
    conn.close()
    lines = unwrap(forecast_run(capsys, db)[1])
    assert "Answering CQs got more replies than calling CQ: 20m (100% vs 0%)" in lines[:8]  # with the summary
    assert "N0CALL" not in "\n".join(lines)  # still no callsigns
    details = forecast_run(capsys, db, "--details")[1]
    assert cli.ANSWERED_NOTES[-1] in details and "1 in 20" in cli.ANSWERED_NOTES[-1]
