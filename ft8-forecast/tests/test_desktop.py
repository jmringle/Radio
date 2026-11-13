"""The standalone app (README acceptance criteria, standalone app section), without opening a window."""

import socket
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from ft8_forecast import cli, desktop, forecast, web
from ft8_forecast.alltxt import Decode
from ft8_forecast.store import open_db, save_decodes

LOCAL_ONLY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", cli.ENV_FILE)  # the app repoints it; this puts it back
    return tmp_path / "FT8 Forecast"


def fetch(url):
    with LOCAL_ONLY.open(url, timeout=5) as response:
        return response.status, response.read().decode()


# --- where data lives ---

def test_macos_folder():
    home = PurePosixPath("/Users/n0call")
    assert desktop.app_dir("darwin", {}, home) == home / "Library/Application Support/FT8 Forecast"


def test_windows_folder():
    roaming = r"C:\Users\n0call\AppData\Roaming"
    assert desktop.app_dir("win32", {"APPDATA": roaming}, PureWindowsPath(r"C:\Users\n0call")) == (
        PureWindowsPath(roaming) / "FT8 Forecast")


def test_windows_folder_without_appdata():
    home = PureWindowsPath(r"C:\Users\n0call")
    assert desktop.app_dir("win32", {}, home) == home / "AppData/Roaming/FT8 Forecast"


# --- the local server ---

def test_serves_only_this_machine_on_a_free_port(folder):
    server = desktop.start_server(folder)
    try:
        assert server.server_address[0] == "127.0.0.1" and server.server_port != cli.DEFAULT_PORT
        status, page = fetch(desktop.url(server))
        assert status == 200 and "No data yet" in page
    finally:
        server.shutdown()


def test_settings_and_data_stay_in_the_app_folder(folder):
    server = desktop.start_server(folder)
    server.shutdown()
    assert cli.ENV_FILE == folder / ".env"
    assert server.app.config["DB"] == folder / "ft8cast.sqlite"


def test_the_app_asks_for_a_log_before_showing_saved_data(folder):
    conn = open_db(folder / "ft8cast.sqlite")  # saved by an earlier launch
    save_decodes(conn, [Decode(datetime(2026, 10, 25 - n, 15, 0, tzinfo=UTC), 14_074_000, False, -5, "N0CALL", None,
                               "CQ N0CALL") for n in range(5)])
    conn.close()
    server = desktop.start_server(folder)
    try:
        page = fetch(desktop.url(server))[1]
        assert "Import your latest log below to start" in page and "Use saved data" in page
    finally:
        server.shutdown()
    assert (folder / "ft8cast.sqlite").is_file()  # kept


def test_two_copies_can_run_at_once(folder):
    first, second = desktop.start_server(folder), desktop.start_server(folder)
    assert first.server_port != second.server_port
    first.shutdown()
    second.shutdown()


# --- running ---

def test_closing_the_window_stops_the_server(folder):
    seen = {}

    def window(url):
        seen["url"] = url
        assert fetch(url)[0] == 200

    assert desktop.run(folder, window) == 0
    port = int(seen["url"].rsplit(":", 1)[1].strip("/"))
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_a_window_that_cant_open_is_explained_and_logged(folder, monkeypatch):
    shown = []
    monkeypatch.setattr(desktop, "show_error", shown.append)

    def window(url):
        raise RuntimeError("no web engine for N0CALL")

    assert desktop.run(folder, window) == 1
    assert "couldn't start" in shown[0] and str(folder / desktop.LOG_NAME) in shown[0]
    log = (folder / desktop.LOG_NAME).read_text()
    assert "RuntimeError" in log and "N0CALL" not in log


def test_a_folder_that_cant_be_made_is_explained(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(desktop, "show_error", shown.append)
    (tmp_path / "file").write_text("")
    assert desktop.run(tmp_path / "file" / "app", lambda url: None) == 1
    assert "couldn't start" in shown[0]


def test_self_test_passes_with_no_window_and_stops(folder):
    assert desktop.self_test(folder) == 0


def test_only_local_connections_are_made(folder, monkeypatch):
    real = socket.socket.connect
    targets = []

    def spy(self, address):
        targets.append(address[0])
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    assert desktop.self_test(folder) == 0
    assert targets and set(targets) == {"127.0.0.1"}


# --- errors (T17) ---

def test_unexpected_errors_name_the_log_and_keep_log_contents_out_of_it(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    db, log = tmp_path / "ft8cast.sqlite", tmp_path / "app.log"
    from ft8_forecast.store import open_db
    open_db(db).close()

    def boom(*args, **kwargs):
        raise ValueError("N0CALL FN31 in a decode")

    monkeypatch.setattr(forecast, "compute", boom)
    response = web.create_app(db, log_file=log).test_client().get("/", base_url="http://127.0.0.1:8074")
    page = response.get_data(as_text=True)
    assert response.status_code == 500 and str(log) in page and "see the terminal" not in page
    text = log.read_text()
    assert "ValueError" in text and "N0CALL" not in text and "FN31" not in text
    assert "Traceback" not in page and "N0CALL" not in page


def test_serve_still_sends_errors_to_the_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    db = tmp_path / "ft8cast.sqlite"
    from ft8_forecast.store import open_db
    open_db(db).close()

    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(forecast, "compute", boom)
    response = web.create_app(db).test_client().get("/", base_url="http://127.0.0.1:8074")
    assert "see the terminal" in response.get_data(as_text=True)
