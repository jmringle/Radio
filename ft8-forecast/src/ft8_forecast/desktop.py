"""The standalone app: the same page as `ft8cast serve`, in a native window.

Only this machine can reach the server (127.0.0.1), on a free port chosen at start. Every
protection in web.py still applies. Nothing here calls the web; the only connections are the
window's to its own server. pywebview loads only when a window opens, so tests and `ft8cast`
don't need it.
"""

import ctypes
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path, PurePath

from werkzeug.serving import BaseWSGIServer, make_server

from ft8_forecast import cli, web

APP_NAME = "FT8 Forecast"
LOG_NAME = "ft8forecast.log"
# The osascript text is fixed: the message arrives as an argument, so it can't act as a script.
_MAC_DIALOG = 'on run argv\n display alert "FT8 Forecast" message (item 1 of argv) as critical\nend run'


def app_dir(platform: str = sys.platform, environ: Mapping[str, str] = os.environ, home: PurePath | None = None) -> PurePath:
    """The user's own folder for the app's database, settings and log."""
    home = Path.home() if home is None else home
    if platform == "win32":
        base = environ.get("APPDATA")
        return type(home)(base) / APP_NAME if base else home / "AppData" / "Roaming" / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return home / ".local" / "share" / APP_NAME


def start_server(folder: Path) -> BaseWSGIServer:
    """Serve the page from `folder`'s settings and database on a free 127.0.0.1 port."""
    folder.mkdir(parents=True, exist_ok=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # one line per request, and no terminal to show it
    cli.ENV_FILE = folder / ".env"
    app = web.create_app(folder / "ft8cast.sqlite", log_file=folder / LOG_NAME, prompt_on_start=True)
    server = make_server("127.0.0.1", 0, app)  # port 0: the OS picks a free one
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def url(server: BaseWSGIServer) -> str:
    return f"http://127.0.0.1:{server.server_port}/"


def open_window(address: str) -> None:
    """Show the page; returns when the window closes."""
    import webview

    webview.create_window(APP_NAME, address, width=1100, height=850, min_size=(420, 500))
    webview.start()


def run(folder: Path, window: Callable[[str], None] = open_window) -> int:
    server = None
    try:
        server = start_server(folder)
        window(url(server))
    except Exception as error:
        log = folder / LOG_NAME
        web.log_failure(log, error)
        show_error(f"FT8 Forecast couldn't start. Details are in {log}")
        return 1
    finally:
        if server is not None:
            server.shutdown()
    return 0


def self_test(folder: Path) -> int:
    """Start, answer one local request, stop: 0 if it worked. The build check in CI runs this."""
    if getattr(sys, "frozen", False):
        import webview  # noqa: F401  proves the build includes it

    server = start_server(folder)
    try:
        # No proxy: a proxy setting on this computer must not see, or break, a local request.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url(server), timeout=10) as response:
            return 0 if response.status == 200 and "FT8 forecast" in response.read().decode() else 1
    finally:
        server.shutdown()


def show_error(message: str) -> None:
    """A native message box: the app has no terminal to print to."""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)  # 0x10: error icon
    elif sys.platform == "darwin":
        subprocess.run(["osascript", "-e", _MAC_DIALOG, message], check=False)
    else:
        print(message, file=sys.stderr)


def main() -> int:
    folder = Path(app_dir())
    return self_test(folder) if "--self-test" in sys.argv[1:] else run(folder)


if __name__ == "__main__":
    sys.exit(main())
