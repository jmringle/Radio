"""ft8cast serve: the local web page (README acceptance criteria, web section)."""

import io
import re
import signal
import socket
from datetime import UTC, datetime, timedelta

import pytest

from ft8_forecast import Contact, Decode, cli, forecast, logs, web
from ft8_forecast.cli import main
from ft8_forecast.store import open_db, save_contacts, save_decodes

BASE = "http://127.0.0.1:8074"
NOW = datetime(2026, 10, 27, 15, 5, tzinfo=UTC)
RX = b"261027_143015    14.074 Rx FT8     -9  0.2  627 CQ N0CALL FN31\r\n"
RX2 = b"261027_143015    14.074 Rx FT8    -12  0.1 1200 N0CALL/M N0CALL -07\r\n"
FT4 = b"261027_143015    14.080 Rx FT4     -9  0.2  627 CQ N0CALL FN31\r\n"
ADIF = (b"WSJT-X ADIF Export<eoh>\n<call:6>N0CALL <gridsquare:4>FN31 <mode:3>FT8 "
        b"<qso_date:8>20261027 <time_on:6>143015 <freq:9>14.075800 <eor>\n")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "ft8cast.sqlite"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fixed clock and an empty .env; returns the .env path."""
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    return tmp_path / ".env"


@pytest.fixture
def client(db, env):
    return web.create_app(db).test_client()


@pytest.fixture
def five_days(db):
    """5 days of 20 m at 15 UTC, newest 2026-10-25 15:30, grids one square north of JJ00."""
    conn = open_db(db)
    newest = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
    save_decodes(conn, [Decode(newest - timedelta(days=n), 14_074_000, False, -10 - n, f"N{n}CALL",
                               "JJ01", f"CQ N{n}CALL JJ01") for n in range(5)])
    conn.close()


def get(client, path="/", base_url=BASE, **kwargs):
    response = client.get(path, base_url=base_url, **kwargs)
    return response, response.get_data(as_text=True)


def upload(client, data, name="ALL.TXT", headers=None, base_url=BASE):
    response = client.post("/import", base_url=base_url, headers={"Origin": BASE} if headers is None else headers,
                           data={"log": (io.BytesIO(data), name)}, content_type="multipart/form-data")
    return response, response.get_data(as_text=True)


def stored(db, table="decodes"):
    if not db.exists():
        return 0
    conn = open_db(db)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# --- the forecast page ---

def cells(page, band):
    row = re.search(rf"<tr>\s*<th[^>]*>{band}</th>(.*?)</tr>", page, re.S).group(1)
    return re.findall(r"<td[^>]*>(.*?)</td>", row)


def test_page_shows_the_best_bet_and_forecast_for_the_current_utc_hour(client, db, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)  # N0CALL on a second day, so its grid can set Heard out to
    save_decodes(conn, [Decode(datetime(2026, 10, 24, 15, 30, tzinfo=UTC), 14_074_000, False, -12, "N0CALL",
                               "JJ01", "CQ N0CALL JJ01")])
    conn.close()
    response, page = get(client)
    assert response.status_code == 200
    assert "FT8 forecast for 15:00-15:59 UTC, 11 am EDT" in page
    assert "Your last 30 days, through 2026-10-25 15:30 UTC" in page
    assert '<p class="verdict">Best bet (busiest): 20m - about 1 station on a typical day</p>' in page
    head = re.search(r"<thead>(.*?)</thead>", page, re.S).group(1)
    assert re.findall(r"<th[^>]*>(.*?)</th>", head) == ["Band", "Stations<br>per day", "Stations<br>30 days",
                                                         "Median<br>SNR dB", "Farthest<br>heard",
                                                         "Farthest<br>worked", "Contacts<br>30 days"]
    assert cells(page, "20m") == ["1", "5", "-12", "69 mi<br><span class=\"grid\">JJ01</span>", "-", "0"]  # the page keeps grids
    assert "Too little data at this hour (need 5 days): 160m 80m 40m 30m 17m 15m 12m 10m (0 days)" in page
    assert "need your grid" not in page


def test_summary_lines_match_the_terminal(client, db, five_days, env, capsys):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)  # 40m at 15 UTC, 2 stations a day: best bet, with 20m next
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, False, -5, call, None,
                               f"CQ {call}") for n in range(5) for call in ("N0CALL/P", "N0CALL/M")])
    conn.close()
    _, page = get(client)
    main(["forecast", "--db", str(db)])
    lines = capsys.readouterr().out.splitlines()
    assert lines[3:5] == ["Next: 20m - about 1 station on a typical day", "This is 40m's busiest hour"]
    assert '<p class="summary">Next: 20m - about 1 station on a typical day<br>This is 40m&#39;s busiest hour</p>' in page


def test_answered_table_shows_cqs_and_calls_apart(client, db, five_days):
    conn = open_db(db)
    cq = datetime(2026, 10, 24, 15, 10, tzinfo=UTC)
    save_decodes(conn, [Decode(cq, 14_074_000, True, 0, "N0CALL/P", "AA00", "CQ N0CALL/P AA00"),
                        Decode(cq + timedelta(seconds=15), 14_074_000, False, -9, "N1CALL", "FN31", "N0CALL/P N1CALL FN31")])
    conn.close()
    _, page = get(client)
    table = re.search(r'<table class="answered">(.*?)</table>', page, re.S).group(1)
    assert "<caption>Replies to you</caption>" in table
    assert re.findall(r"<th\b[^>]*>(.*?)</th>", table) == ["Band", "Calling CQ", "Answering CQs", "20m"]
    assert re.findall(r"<td[^>]*>(.*?)</td>", table) == ["1 of 1 (100%)", "-"]
    assert "<br>".join(cli.ANSWERED_NOTES) in page


def test_no_answered_table_without_your_tx(client, five_days):
    _, page = get(client)
    assert 'class="answered"' not in page and cli.ANSWERED_NOTES[0] not in page


def test_columns_are_explained_like_the_terminal(client, five_days):
    _, page = get(client)
    assert "Nothing leaves this machine." in page
    for line in cli.LEGEND:
        assert line in page


def test_column_notes_and_farthest_contacts_start_collapsed(client, db, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    _, page = get(client)
    notes = re.search(r"<details>\s*<summary>Column notes</summary>(.*?)</details>", page, re.S)
    assert notes and cli.LEGEND[0] in notes.group(1)
    farthest = re.search(r'<details>\s*<summary><h2 id="farthest-title">Farthest contacts</h2></summary>(.*?)</details>',
                         page, re.S)
    assert farthest and "Farthest contact ever" in farthest.group(1)
    assert "<details open" not in page


def test_rank_by_contacts(client, db, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)  # 40m: 5 days of 1 station, and 2 contacts at 15 UTC
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, False, -5, f"N{n}CALL/P",
                               None, f"CQ N{n}CALL/P") for n in range(5)])
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, "JJ01")
                         for n in range(2)])
    conn.close()
    _, page = get(client, query_string={"rank": "contacts"})
    assert "Best bet (most contacts): 40m - 2 contacts in 30 days; worked out to 69 mi" in page
    assert '<option value="contacts" selected>Most contacts</option>' in page
    assert re.findall(r"<tbody>\s*<tr>\s*<th[^>]*>(\w+)</th>", page) == ["40m"]  # first row
    _, page = get(client, query_string={"rank": "contacts", "hour": "9"})
    assert '<option value="9" selected>' in page and '<option value="contacts" selected>' in page


def test_busiest_is_selected_by_default(client, five_days):
    _, page = get(client)
    assert '<option value="busiest" selected>Busiest typical day</option>' in page


@pytest.mark.parametrize("rank", ["", "Busiest", "most", "contacts "])
def test_bad_rank_is_a_400(client, five_days, rank):
    response, page = get(client, query_string={"rank": rank})
    assert response.status_code == 400
    assert "Best bet must be &#39;busiest&#39; or &#39;contacts&#39;" in page  # escaped, like all text


def test_page_shows_farthest_contacts_like_the_terminal(client, db, five_days, env, capsys):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [
        Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01"),
        Contact("N0CALL/P", datetime(2026, 10, 25, 3, 0, tzinfo=UTC), 7_074_000, "JJ10"),  # other hour
        Contact("N0CALL/M", datetime(2026, 10, 23, 15, 0, tzinfo=UTC), 14_074_000, None),  # no grid
        Contact("N0CALL/QRP", datetime(2026, 4, 8, 15, 0, tzinfo=UTC), 14_074_000, "JJ30"),  # before the window
    ])
    conn.close()
    _, page = get(client)
    assert cells(page, "20m")[3:] == ["-", "69 mi<br><span class=\"grid\">JJ01</span>", "2"]
    assert "Farthest contact ever: 415 mi (JJ30) on 20m, 2026-04-08" in page
    assert "Farthest contact by day (30 days, any hour)" in page
    days = re.search(r'<table class="daily"[^>]*>.*?<tbody>(.*?)</tbody>', page, re.S).group(1)
    assert [re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r) for r in re.findall(r"<tr>(.*?)</tr>", days, re.S)] == [
        ["2026-10-25", "40m", "138 mi (JJ10)"], ["2026-10-23", "-", "-"]]
    assert "N0CALL" not in page  # grids only, never callsigns
    # The terminal shows the same lines, without the grids.
    main(["forecast", "--db", str(db), "--details"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[2] in page  # the best bet
    assert next(line for line in lines if line.startswith("Too little data")) in page
    assert "Farthest contact ever: 415 mi on 20m, 2026-04-08" in lines


def test_without_my_grid_no_farthest_contact_sections(client, db, five_days):
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    _, page = get(client)
    assert "Farthest contact ever" not in page and "Farthest contact by day" not in page


def test_hour_option(client, five_days):
    _, page = get(client, query_string={"hour": "9"})
    assert "FT8 forecast for 09:00-09:59 UTC" in page
    assert '<option value="9" selected>' in page
    assert "Best bet (busiest): none - no listening at this hour in these 30 days" in page
    assert '<th scope="col">Stations<br>per day</th>' not in page and cli.LEGEND[0] not in page  # no band to list
    assert "Too little data at this hour" not in page


def test_all_hours_option(client, five_days):
    _, page = get(client, query_string={"hour": "all"})
    assert "FT8 forecast for all hours (00:00-23:59 UTC)" in page
    assert '<option value="all" selected>All hours</option>' in page
    assert "at this hour" not in page


def test_page_shows_the_24_hour_overview_like_the_terminal(client, db, five_days, capsys):
    conn = open_db(db)  # 40m at 15 UTC on 5 days, 2 stations a day: the best bet; 20m once at 03 UTC
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 7_074_000, False, -5, call, None,
                               f"CQ {call}") for n in range(5) for call in ("N0CALL/P", "N0CALL/M")])
    save_decodes(conn, [Decode(datetime(2026, 10, 25, 3, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL")])
    conn.close()
    _, page = get(client, query_string={"rank": "busiest"})
    table = re.search(r'<table class="overview"[^>]*>(.*?)</table>', page, re.S).group(1)
    head = re.findall(r"<th[^>]*>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", table, re.S).group(1))
    assert head == ["UTC", "Local", "40m", "20m"]  # all-dot columns and rows are summed up instead
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", re.search(r"<tbody>(.*?)</tbody>", table, re.S).group(1), re.S)
    assert len(rows) == 1
    # Each hour links to its forecast, keeping the ranking; the hour on show is marked.
    assert '<tr class="current"><th scope="row"><a href="/?hour=15&amp;rank=busiest" aria-current="true">15</a></th>' in table
    assert re.findall(r"<td[^>]*>(.*?)</td>", rows[0]) == ["11 am", "2*", "1"]
    assert '<td class="local">11 am</td>' in rows[0]
    assert '<td class="best">2*</td>' in rows[0]
    main(["overview", "--db", str(db)])
    out = capsys.readouterr().out.splitlines()
    assert out[1] in page  # the key
    assert out[-3:] == ["Too little data on every band: 03 UTC (11 pm EDT)",
                        "Hours with no listening: 00-02 UTC (8 pm-10 pm EDT), 04-14 UTC (12 am-10 am EDT), "
                        "16-23 UTC (12 pm-7 pm EDT)",
                        "Too little data at every hour: 160m 80m 30m 17m 15m 12m 10m"]
    for line in out[-3:]:
        assert line in page


def test_overview_dots_are_muted_and_other_hours_unmarked(client, db, five_days):
    conn = open_db(db)  # 40m at 14 UTC on 5 days: a 14 row, where 20m is "."
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 14, 0, tzinfo=UTC), 7_074_000, False, -5, "N0CALL/P",
                               None, "CQ N0CALL/P") for n in range(5)])
    conn.close()
    _, page = get(client, query_string={"hour": "14"})
    assert '<td class="thin">.</td>' in page
    assert '<tr><th scope="row"><a href="/?hour=15&amp;rank=busiest">15</a></th>' in page  # not current
    assert '<tr class="current"><th scope="row"><a href="/?hour=14&amp;rank=busiest" aria-current="true">14</a>' in page


def test_overview_comes_before_farthest_contacts(client, db, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    _, page = get(client)
    assert page.index("Best bet (busiest)") < page.index("24-hour overview") < page.index("Farthest contact ever")


def test_narrow_screens_get_a_scroll_hint_under_the_forecast_table(client, five_days):
    _, page = get(client)
    assert re.search(r'</table>\s*</div>\s*<p class="scroll-hint">Scroll the table sideways for more</p>', page)
    assert page.count('class="scroll-hint"') == 1  # the other tables fit a phone
    css = client.get("/static/style.css", base_url=BASE).get_data(as_text=True)
    assert ".scroll-hint { display: none;" in css
    assert re.search(r"@media \(max-width: 44rem\) \{\s*\.scroll-hint \{ display: block;", css)


def test_no_scroll_hint_without_a_table(client, five_days):
    _, page = get(client, query_string={"hour": "3"})
    assert "scroll-hint" not in page


def test_tables_scroll_in_their_own_box(client, db, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, "JJ01")])
    conn.close()
    _, page = get(client)
    tables = re.findall(r"(.{40})<table", page, re.S)
    assert len(tables) == 3 and all('<div class="scroll">' in before for before in tables)
    css = client.get("/static/style.css", base_url=BASE).get_data(as_text=True)
    assert ".scroll { overflow-x: auto;" in css and "white-space: nowrap" in css


def test_overview_follows_best_bet_by(client, db, five_days):
    conn = open_db(db)
    save_contacts(conn, [Contact("N0CALL", datetime(2026, 10, 25, 15, 0, tzinfo=UTC), 14_074_000, None)])
    conn.close()
    _, page = get(client, query_string={"rank": "contacts"})
    assert "* = best bet (most contacts)" in page
    assert '<a href="/?hour=15&amp;rank=contacts" aria-current="true">15</a>' in page


def test_no_overview_without_data(client, db):
    _, page = get(client)
    assert "24-hour overview" not in page


def test_current_hour_is_selected_by_default_not_all(client, five_days):
    _, page = get(client)
    assert '<option value="15" selected>' in page
    assert '<option value="all">All hours</option>' in page


@pytest.mark.parametrize("hour", ["24", "-1", "abc", "", " 1", "1.0", "٣", "999", "ALL", "all "])
def test_bad_hour_is_a_400(client, five_days, hour):
    response, page = get(client, query_string={"hour": hour})
    assert response.status_code == 400
    assert "must be a UTC hour from 0 to 23" in page


def test_without_my_grid_farthest_is_blank_and_explained(client, five_days):
    _, page = get(client)
    assert "Farthest heard and worked need your grid: set it in Settings below." in page


def test_invalid_my_grid_is_explained(client, five_days, env):
    env.write_text("MY_GRID=FN3\n")
    response, page = get(client)
    assert response.status_code == 500
    assert "Grid square in Settings: &#39;FN3&#39; isn&#39;t a grid square like FN31" in page


def test_stale_data_gets_a_note(client, five_days, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 3, 15, 31, tzinfo=UTC))
    assert cli.STALE_NOTE in get(client)[1]


def test_no_database_invites_an_upload_and_creates_none(client, db):
    response, page = get(client)
    assert response.status_code == 200
    assert ("No data yet. Import your WSJT-X ALL.TXT below; add wsjtx_log.adi too for your contacts. "
            "To import from a folder instead, set the log folder in Settings.") in page
    assert 'name="log"' in page
    assert 'name="hour"' not in page and 'name="rank"' not in page  # nothing to pick until there's data
    assert not db.exists()


def test_no_data_with_log_dir_points_at_the_folder_button(client, db, env, tmp_path):
    env.write_text(f"LOG_DIR={tmp_path}\n")
    _, page = get(client)
    assert "No data yet. Import your WSJT-X ALL.TXT below, or press Import from folder." in page


def test_only_adif_imported_asks_for_all_txt(client, db):
    upload(client, ADIF, "log.adi")
    page = get(client)[1]
    assert "No ALL.TXT data imported yet: the forecast is built from it. Import it below." in page
    assert 'name="hour"' not in page


def test_tab_title_shows_the_hour_and_best_bet(client, db, five_days):
    _, page = get(client)
    assert "<title>FT8 forecast · 15:00 UTC · best bet 20m</title>" in page
    _, page = get(client, query_string={"hour": "all"})
    assert "<title>FT8 forecast · all hours · best bet 20m</title>" in page
    _, page = get(client, query_string={"hour": "3"})
    assert "<title>FT8 forecast · 03:00 UTC</title>" in page  # no best bet at that hour


def test_tab_title_without_data(client, db):
    assert "<title>FT8 forecast</title>" in get(client)[1]


def test_native_controls_follow_dark_mode(client):
    css = client.get("/static/style.css", base_url=BASE).get_data(as_text=True)
    assert "color-scheme: light dark;" in css


def test_database_that_isnt_ours_is_explained_and_left_alone(tmp_path, env):
    other = tmp_path / "notes.txt"
    other.write_bytes(b"not a database\n")
    client = web.create_app(other).test_client()
    response, page = get(client)
    assert response.status_code == 500
    assert "isn&#39;t an ft8cast database" in page
    assert upload(client, RX)[0].status_code == 500
    assert other.read_bytes() == b"not a database\n"


def test_unknown_page_is_404_and_import_needs_post(client):
    assert get(client, "/nope")[0].status_code == 404
    assert get(client, "/import")[0].status_code == 405


# --- uploading ---

def test_upload_all_txt_imports_and_reports_counts(client, db):
    response, page = upload(client, RX + RX2 + FT4)
    assert response.status_code == 200
    # Compact: "read as" only when the type isn't what the name says; details on one muted line.
    assert "ALL.TXT: 2 FT8 lines, 2 new, 0 already stored" in page and "read as" not in page
    assert '<span class="muted">Skipped 1 other modes · No problems</span>' in page
    assert "Problems: 0" not in page
    assert "FT8 forecast for 15:00-15:59 UTC" in page  # the page carries on to the forecast
    assert stored(db) == 2


def test_an_all_txt_uploaded_as_adi_says_how_it_was_read(client, db):
    _, page = upload(client, RX, "wsjtx_log.adi")
    assert "wsjtx_log.adi (read as ALL.TXT): 1 FT8 lines, 1 new" in page


def test_hour_list_marks_the_current_utc_hour(client, five_days):
    _, page = get(client, query_string={"hour": "9"})
    assert '<option value="15">15:00 (11 am, now)</option>' in page
    assert '<option value="9" selected>09:00 (5 am)</option>' in page
    assert '<option value="all">All hours</option>' in page


def test_data_age_is_shown(client, five_days):
    _, page = get(client)  # newest 2026-10-25, clock 2026-10-27
    assert "Your last 30 days, through 2026-10-25 15:30 UTC, 2 days ago" in page


def test_upload_adif_is_detected_by_content(client, db):
    _, page = upload(client, ADIF, "export.txt")
    assert "export.txt (read as ADIF): 1 FT8 contacts, 1 new" in page
    assert stored(db, "contacts") == 1


def test_uploading_again_adds_nothing(client, db):
    upload(client, RX + RX2)
    _, page = upload(client, RX + RX2)
    assert "2 FT8 lines, 0 new, 2 already stored" in page
    assert stored(db) == 2


def test_problems_are_listed_with_line_numbers_and_the_rest_imports(client, db):
    _, page = upload(client, RX + b"garbage\n" * 25)
    assert "Problems: 25" in page
    assert "line 2: not an ALL.TXT decode line" in page
    assert page.count("not an ALL.TXT decode line") == cli.SHOW_PROBLEMS
    assert "and 15 more" in page
    assert stored(db) == 1


@pytest.mark.parametrize("data, kind", [(b"", "ALL.TXT"), (FT4, "ALL.TXT"), (b"\x89PNG\r\n\x1a\n\0\0", "ALL.TXT"),
                                        (b"WSJT-X ADIF Export<eoh>\n", "ADIF")])
def test_file_with_no_ft8_records_is_a_400_and_stores_nothing(client, db, data, kind):
    response, page = upload(client, data)
    assert response.status_code == 400
    assert f"no FT8 records found (read as {kind})" in page
    assert not db.exists()


def test_no_file_chosen_is_a_400(client, db):
    response = client.post("/import", base_url=BASE, headers={"Origin": BASE}, data={},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "Choose an ALL.TXT or .adi file" in response.get_data(as_text=True)
    assert not db.exists()


def test_oversized_upload_is_a_413(client, db, monkeypatch):
    client.application.config["MAX_CONTENT_LENGTH"] = 1000
    response, page = upload(client, RX * 100)
    assert response.status_code == 413
    assert "larger than" in page
    assert not db.exists()


def test_upload_limit_is_500_mb(db):
    assert web.create_app(db).config["MAX_CONTENT_LENGTH"] == 500 * 1024 * 1024


def test_oversized_adif_is_a_400(client, db, monkeypatch):
    monkeypatch.setattr(logs, "MAX_ADIF_BYTES", len(ADIF) - 1)
    response, page = upload(client, ADIF, "log.adi")
    assert response.status_code == 400
    assert "not an ADIF log?" in page
    assert not db.exists()


# --- import from the LOG_DIR folder ---

@pytest.fixture
def logdir(tmp_path, env):
    folder = tmp_path / "wsjt x"
    folder.mkdir()
    (folder / "ALL.TXT").write_bytes(RX + RX2)
    (folder / "wsjtx_log.adi").write_bytes(ADIF)
    env.write_text(f"LOG_DIR={folder}\n")
    return folder


def import_folder(client, headers=None):
    response = client.post("/import-folder", base_url=BASE, headers={"Origin": BASE} if headers is None else headers)
    return response, response.get_data(as_text=True)


def test_folder_button_shows_only_with_log_dir(client, db, logdir, env):
    _, page = get(client)
    assert '<form method="post" action="/import-folder"' in page
    assert f"From {logdir}" in page
    env.write_text("")
    _, page = get(client)
    assert "/import-folder" not in page


def test_page_never_takes_a_folder_path(client, db, logdir, tmp_path):
    # Only LOG_DIR from .env: nothing open in the browser can make the page read another folder.
    other = tmp_path / "other"
    other.mkdir()
    (other / "ALL.TXT").write_bytes(RX + RX2 + FT4.replace(b"FT4", b"FT8"))
    _, page = get(client)
    assert 'name="dir"' not in page
    client.post("/import-folder", base_url=BASE, headers={"Origin": BASE}, data={"dir": str(other)})
    assert stored(db) == 2  # LOG_DIR's two lines, not the other folder's three


def test_import_folder_imports_every_log(client, db, logdir):
    response, page = import_folder(client)
    assert response.status_code == 200
    assert "ALL.TXT: 2 FT8 lines, 2 new, 0 already stored" in page
    assert "wsjtx_log.adi: 1 FT8 contacts, 1 new, 0 already stored" in page
    assert page.count('<p class="file">') == 2  # one block per file
    assert (stored(db), stored(db, "contacts")) == (2, 1)


def test_import_folder_reports_a_bad_file_and_imports_the_rest(client, db, logdir):
    (logdir / "broken.adi").write_bytes(b"<call:6>N0CALL <mode:3>FT4 <eor>")
    response, page = import_folder(client)
    assert response.status_code == 200
    assert "broken.adi: no FT8 records found (read as ADIF)" in page
    assert stored(db) == 2


def test_import_folder_without_log_dir_is_a_400(client, db, env):
    response, page = import_folder(client)
    assert response.status_code == 400 and "Set the log folder in Settings" in page and not db.exists()


def test_import_folder_that_isnt_there_is_a_400_and_stores_nothing(client, db, logdir, tmp_path):
    logdir.rename(tmp_path / "away")
    response, page = import_folder(client)
    assert response.status_code == 400 and "isn&#39;t a folder" in page and not db.exists()


@pytest.mark.parametrize("origin", ["http://evil.example", "null", ""])
def test_import_folder_from_any_other_origin_is_refused(client, db, logdir, origin):
    response, _ = import_folder(client, headers={"Origin": origin} if origin else {})
    assert response.status_code == 403 and not db.exists()


def test_no_copy_of_the_upload_is_kept(client, db, tmp_path):
    upload(client, RX, "kept.txt")
    assert sorted(p.name for p in db.parent.iterdir()) == ["ft8cast.sqlite"]
    assert not list(tmp_path.rglob("kept.txt"))


# --- abuse cases: only this page, on this machine, can use the server ---

@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8074", "192.0.2.1:8074", "[::1]:8074",
                                  "127.0.0.1.example.com:8074"])
def test_other_host_names_are_refused(client, db, five_days, host):
    # DNS rebinding: an attacker's domain pointed at 127.0.0.1 sends its own name as Host.
    assert get(client, base_url=f"http://{host}")[0].status_code == 400
    response, _ = upload(client, RX2, headers={"Origin": f"http://{host}"}, base_url=f"http://{host}")
    assert response.status_code == 400
    assert stored(db) == 5


@pytest.mark.parametrize("host", ["127.0.0.1:8074", "localhost:8074", "LOCALHOST:8074", "127.0.0.1"])
def test_local_host_names_are_accepted(client, five_days, host):
    assert get(client, base_url=f"http://{host}")[0].status_code == 200


@pytest.mark.parametrize("origin", [None, "null", "http://evil.example.com", "http://localhost:8074",
                                    "https://127.0.0.1:8074", "http://127.0.0.1:9999"])
def test_upload_from_any_other_origin_is_refused(client, db, origin):
    # CSRF: another site's page posting a file to this server through your browser.
    response, page = upload(client, RX, headers={} if origin is None else {"Origin": origin})
    assert response.status_code == 403
    assert "only accepts uploads from its own page" in page
    assert not db.exists()


def test_on_air_text_and_file_names_are_escaped(client, db):
    # A crafted ALL.TXT line is echoed in the problem list; it must show as text, not run.
    line = b"<script>alert(1)</script>\n"
    # (No '"' in the name: browsers send it as %22, and a raw one breaks the multipart header.)
    _, page = upload(client, RX + line, name="<img src=x onerror=alert(1)>.txt")
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img src=x" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_long_file_names_are_cut_short(client):
    _, page = upload(client, RX, name="A" * 500 + ".txt")
    assert "A" * 80 in page and "A" * 81 not in page


@pytest.mark.parametrize("path", ["/", "/nope", "/static/style.css"])
def test_security_headers_on_every_response(client, path):
    headers = client.get(path, base_url=BASE).headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "form-action 'self'" in csp
    assert "script-src" not in csp  # no JavaScript at all
    assert headers["X-Content-Type-Options"] == "nosniff"
    # Not "no-referrer": under it, browsers send "Origin: null" on form posts (Fetch standard,
    # "serializing a request origin"), and the Origin check then refuses this page's own uploads.
    assert headers["Referrer-Policy"] == "same-origin"


def test_errors_show_no_traceback(client, five_days, monkeypatch):
    def boom(*args):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(forecast, "compute", boom)
    response, page = get(client)
    assert response.status_code == 500
    assert "secret internals" not in page and "Traceback" not in page


def test_page_loads_nothing_from_other_sites(client, five_days):
    _, page = get(client)
    links = re.findall(r'(?:href|src|action)="([^"]*)"', page)
    assert links and all(link.startswith("/") and not link.startswith("//") for link in links)
    assert "<script" not in page


def test_page_never_uses_the_network(client, five_days, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the web page tried to use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert get(client)[0].status_code == 200
    assert upload(client, RX)[0].status_code == 200
    assert upload(client, ADIF, "log.adi")[0].status_code == 200


# --- ft8cast serve ---

@pytest.fixture
def served(monkeypatch):
    """Captures the server settings instead of starting a server."""
    calls = []
    monkeypatch.setattr("werkzeug.serving.run_simple", lambda host, port, app, **kw: calls.append((host, port, kw)))
    return calls


def test_serve_listens_only_on_this_machine_with_debug_off(served, db, monkeypatch, capsys):
    monkeypatch.setenv("FLASK_DEBUG", "1")  # must not switch the debugger on
    assert main(["serve", "--db", str(db)]) == 0
    host, port, options = served[0]
    assert (host, port) == ("127.0.0.1", 8074)
    assert not options.get("use_debugger") and not options.get("use_reloader")
    assert "http://127.0.0.1:8074" in capsys.readouterr().out


def test_serve_port_option(served, db):
    assert main(["serve", "--port", "8080", "--db", str(db)]) == 0
    assert served[0][1] == 8080


@pytest.mark.parametrize("port", ["0", "80", "1023", "65536", "abc", "-1"])
def test_bad_port_is_a_usage_error(served, port, capsys):
    assert main(["serve", "--port", port]) == 2
    assert "must be a port from 1024 to 65535" in capsys.readouterr().err
    assert served == []


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM, which Windows lacks")
def test_port_in_use_is_an_error(db, capsys):
    def started(*args):
        raise AssertionError("a server started; it should have found the port taken")
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    previous = signal.signal(signal.SIGALRM, started)
    signal.alarm(5)  # if a server does start, fail instead of serving forever
    try:
        port = taken.getsockname()[1]
        if port < 1024:
            pytest.skip("OS gave a privileged port")
        assert main(["serve", "--port", str(port), "--db", str(db)]) == 2
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        taken.close()
    assert "in use" in capsys.readouterr().err


# --- settings (README: standalone app; T13, T14) ---

def save(client, grid="", log_dir="", headers=None, base_url=BASE):
    response = client.post("/settings", base_url=base_url, headers={"Origin": BASE} if headers is None else headers,
                           data={"my_grid": grid, "log_dir": log_dir})
    return response, response.get_data(as_text=True)


def test_saved_settings_are_used_and_shown(client, env, five_days):
    response, page = save(client, grid="fn31pr", log_dir="/logs/wsjt x")
    assert response.status_code == 200 and "Settings saved." in page
    assert 'name="my_grid" value="FN31"' in page  # 6 characters are cut to 4: keeps your location coarse
    assert 'name="log_dir" value="/logs/wsjt x"' in page
    assert "License class" not in page
    assert env.read_text() == "MY_GRID=FN31\nLOG_DIR=/logs/wsjt x\n"


def test_saving_changes_only_the_settings_lines(client, env):
    env.write_text("# my notes\nOTHER=1\nMY_GRID=JJ00\n")
    save(client, grid="FN31")
    assert env.read_text() == "# my notes\nOTHER=1\nMY_GRID=FN31\n"


def test_an_empty_value_clears_the_setting(client, env):
    env.write_text("MY_GRID=FN31\nLOG_DIR=/logs\n")
    save(client)
    assert env.read_text() == ""


@pytest.mark.parametrize("fields, reason", [
    ({"grid": "ZZ99"}, "grid square"),
    ({"grid": "FN31\nLOG_DIR=/etc"}, "grid square"),
    ({"log_dir": "/logs\nMY_GRID=JJ00"}, "line break"),
    ({"log_dir": "/logs\rMY_GRID=JJ00"}, "line break"),
    ({"log_dir": "/logs\x00"}, "line break"),
    ({"log_dir": "/logs # old"}, "#"),
    ({"log_dir": "/" + "x" * 1001}, "too long"),
])
def test_a_bad_setting_saves_nothing_and_says_why(client, env, fields, reason):
    env.write_text("MY_GRID=JJ00\n")
    response, page = save(client, **({"grid": "FN31"} | fields))
    assert response.status_code == 400 and reason in page
    assert env.read_text() == "MY_GRID=JJ00\n"


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {}])
def test_settings_from_any_other_origin_are_refused(client, env, headers):
    response, _ = save(client, log_dir="/somewhere/else", headers=headers)
    assert response.status_code == 403 and not env.exists()


def test_saved_folder_text_is_escaped(client, env):
    _, page = save(client, log_dir='"><script>alert(1)</script>')
    assert "<script>" not in page


def test_a_bad_grid_in_the_file_can_be_fixed_from_the_page(client, env):
    env.write_text("MY_GRID=ZZ99\n")
    response, page = get(client)
    assert response.status_code == 500 and 'name="my_grid" value="ZZ99"' in page
    response, page = save(client, grid="FN31")
    assert response.status_code == 200


def test_messages_point_to_settings_not_a_file(client, env, five_days):
    _, page = get(client, "/?hour=15")
    assert "in Settings" in page and ".env" not in page
