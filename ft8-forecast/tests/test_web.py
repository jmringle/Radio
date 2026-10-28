"""ft8cast serve: the local web page (README acceptance criteria, web section)."""

import io
import re
import signal
import socket
from datetime import UTC, datetime, timedelta

import pytest

from ft8_forecast import Decode, cli, forecast, logs, web
from ft8_forecast.cli import main
from ft8_forecast.store import open_db, save_decodes

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

def test_page_shows_the_forecast_for_the_current_utc_hour(client, five_days, env):
    env.write_text("MY_GRID=JJ00\n")
    response, page = get(client)
    assert response.status_code == 200
    assert "FT8 forecast for 15:00-15:59 UTC" in page
    assert "30 days through 2026-10-25 15:30 UTC" in page
    row = re.search(r"<tr>\s*<th[^>]*>20m</th>(.*?)</tr>", page, re.S).group(1)
    assert re.findall(r"<td[^>]*>(.*?)</td>", row) == ["1", "5", "-12 dB", "69 mi", "0"]
    assert "not enough data (0 days listening; need 5)" in page
    assert "needs your grid" not in page


def test_station_columns_are_grouped_and_explained(client, five_days):
    _, page = get(client)
    assert '<th scope="colgroup" colspan="2">Stations heard</th>' in page
    assert '<th scope="col">Typical day</th><th scope="col">30-day total</th>' in page
    assert "Typical day: stations heard on the median day you listened at this hour." in page
    assert "30-day total: different stations heard over the whole 30 days." in page


def test_hour_option(client, five_days):
    _, page = get(client, query_string={"hour": "9"})
    assert "FT8 forecast for 09:00-09:59 UTC" in page
    assert '<option value="9" selected>' in page
    assert "not enough data (0 days listening; need 5)" in page


@pytest.mark.parametrize("hour", ["24", "-1", "abc", "", " 1", "1.0", "٣", "999"])
def test_bad_hour_is_a_400(client, five_days, hour):
    response, page = get(client, query_string={"hour": hour})
    assert response.status_code == 400
    assert "must be a UTC hour from 0 to 23" in page


def test_without_my_grid_farthest_is_blank_and_explained(client, five_days):
    _, page = get(client)
    assert "Farthest needs your grid: set MY_GRID in .env" in page


def test_invalid_my_grid_is_explained(client, five_days, env):
    env.write_text("MY_GRID=FN3\n")
    response, page = get(client)
    assert response.status_code == 500
    assert "MY_GRID in .env: &#39;FN3&#39; isn&#39;t a grid square like FN31" in page


def test_stale_data_gets_a_note(client, five_days, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 11, 3, 15, 31, tzinfo=UTC))
    assert "your newest data is 9 days old" in get(client)[1]


def test_no_database_invites_an_upload_and_creates_none(client, db):
    response, page = get(client)
    assert response.status_code == 200
    assert "No data yet" in page
    assert 'name="log"' in page
    assert not db.exists()


def test_only_adif_imported_asks_for_all_txt(client, db):
    upload(client, ADIF, "log.adi")
    assert "No ALL.TXT data imported yet" in get(client)[1]


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
    assert "ALL.TXT (read as ALL.TXT): 2 FT8 lines, 2 new, 0 already stored" in page
    assert "Skipped: 1 other modes" in page
    assert "Problems: 0" in page
    assert "FT8 forecast for 15:00-15:59 UTC" in page  # the page carries on to the forecast
    assert stored(db) == 2


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


def test_no_copy_of_the_upload_is_kept(client, db, tmp_path):
    upload(client, RX, "kept.txt")
    assert sorted(p.name for p in db.parent.iterdir()) == ["ft8cast.sqlite"]
    assert not list(tmp_path.rglob("kept.txt"))


# --- abuse cases: only this page, on this Mac, can use the server ---

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


def test_serve_listens_only_on_this_mac_with_debug_off(served, db, monkeypatch, capsys):
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
