"""ft8cast import: output, exit codes and file handling (README acceptance criteria)."""

import os

import pytest

from ft8_forecast import cli
from ft8_forecast.cli import main

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
    monkeypatch.setattr(cli, "MAX_ADIF_BYTES", len(ADIF) - 1)
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
