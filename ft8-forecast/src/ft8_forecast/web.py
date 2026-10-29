"""ft8cast serve: the forecast and file import as a local web page.

Only this machine can reach it: `ft8cast serve` binds to 127.0.0.1. Any site open in
your browser can still send requests to localhost, so every request must name
this server in its Host header (stops DNS rebinding) and every upload must come
from this page's own Origin (stops cross-site request forgery). The page has no
JavaScript and loads nothing from other sites, so it makes no web calls either.
Jinja escapes everything inserted into the page, including text from your files.
"""

import argparse
from pathlib import Path

from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from ft8_forecast import cli, folder, forecast
from ft8_forecast.logs import TooLarge, read_log, save_log
from ft8_forecast.store import StoreError, open_db

# Your ALL.TXT is about 27 MB for 48 days; 500 MB is years of listening.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
LOCAL_NAMES = {"127.0.0.1", "localhost"}
MAX_NAME = 80  # characters of an uploaded file's name to show

_HEADERS = {
    # No scripts, no outside fonts or images; forms only post back here; no framing (clickjacking).
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; "
                               "frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    # Not "no-referrer": browsers then send "Origin: null" on form posts, which the Origin check refuses.
    "Referrer-Policy": "same-origin",
}


class PageError(Exception):
    """A problem to show on the page, with its HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def create_app(db: Path) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    @app.before_request
    def only_this_page():
        name = request.host.lower()
        if not name.startswith("["):  # an IPv6 literal; never ours, since we bind IPv4
            name = name.split(":", 1)[0]
        if name not in LOCAL_NAMES:
            raise PageError(400, "This server only answers to 127.0.0.1 or localhost.")
        if request.method == "POST" and request.headers.get("Origin", "").lower() != f"http://{request.host}".lower():
            raise PageError(403, "This server only accepts uploads from its own page.")

    @app.after_request
    def security_headers(response):
        response.headers.update(_HEADERS)
        return response

    @app.get("/")
    def page():
        text = request.args.get("hour")
        try:
            hour = None if text is None else cli._hour(text)
        except argparse.ArgumentTypeError as error:
            raise PageError(400, f"Hour {error}.") from None
        try:
            by = cli._rank(request.args.get("rank", "busiest"))
        except argparse.ArgumentTypeError as error:
            raise PageError(400, f"Best bet {error}.") from None
        return _render(db, hour, by)  # hour None: now; cli.ALL_HOURS: the whole day

    @app.post("/import")
    def upload():
        file = request.files.get("log")
        if file is None or not file.filename:
            raise PageError(400, "Choose an ALL.TXT or .adi file to import.")
        name = file.filename[:MAX_NAME]
        try:
            log = read_log(file.stream)
        except TooLarge as error:
            raise PageError(400, f"{name}: {error}") from None
        if not log.records:
            raise PageError(400, f"{name}: no FT8 records found (read as {log.kind})")
        conn = _open(db)
        try:
            new = save_log(conn, log)
        finally:
            conn.close()
        return _render(db, None, "busiest", imported=[{"name": name, "log": log, "new": new, "error": None}])

    @app.post("/import-folder")
    def import_from_folder():
        # The folder comes only from LOG_DIR in .env, never from the request.
        try:
            logs = cli._log_dir()
        except ValueError as error:
            raise PageError(500, f"LOG_DIR in {cli.ENV_FILE.name}: {error}") from None
        if logs is None:
            raise PageError(400, f"Set LOG_DIR in {cli.ENV_FILE.name} to import from a folder.")
        try:
            folder.find_logs(logs)  # check before creating a database
            conn = _open(db)
        except folder.FolderError as error:
            raise PageError(400, str(error)) from None
        try:
            results = folder.import_folder(conn, logs)
        except folder.FolderError as error:
            raise PageError(400, str(error)) from None
        finally:
            conn.close()
        return _render(db, None, "busiest", imported=[
            {"name": r.path.name[:MAX_NAME], "log": r.log, "new": r.new, "error": r.error} for r in results])

    @app.errorhandler(PageError)
    def page_error(error):
        return render_template("page.html", error=str(error), hours=range(24)), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        if isinstance(error, RequestEntityTooLarge):
            message = f"That file is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        else:
            message = f"{error.code} {error.name}."
        return render_template("page.html", error=message, hours=range(24)), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        # Details go to the terminal running the server, never to the page.
        app.logger.exception("unexpected error")
        return render_template("page.html", error="Something went wrong; see the terminal.", hours=range(24)), 500

    return app


def _open(db: Path):
    try:
        return open_db(db)
    except StoreError as error:
        raise PageError(500, str(error)) from None


def _render(db: Path, hour: int | str | None, by: str, imported: list[dict] | None = None) -> str:
    try:
        my_grid = cli._my_grid()  # the same .env and clock as the CLI
    except ValueError as error:
        raise PageError(500, f"MY_GRID in {cli.ENV_FILE.name}: {error}") from None
    now = cli._now()
    hour = now.hour if hour is None else None if hour == cli.ALL_HOURS else hour
    result, age, message, overview, summary = None, None, None, None, []
    if not db.is_file():
        message = ("No data yet. Import your WSJT-X ALL.TXT below, or press Import from folder." if cli._log_dir() else
                   "No data yet. Import your WSJT-X ALL.TXT below; add wsjtx_log.adi too for your contacts. "
                   f"To import from a folder instead, set LOG_DIR in {cli.ENV_FILE.name}.")
    else:
        conn = _open(db)
        try:
            result = forecast.compute(conn, hour, my_grid, now)
            if result is not None:  # about 0.3 s for a year of listening
                hours = [forecast.compute(conn, h, my_grid, now) for h in range(24)]
                overview = cli.overview(hours, by)
                summary = cli.summary_lines(result, by, hours if hour is not None else None, now)
        finally:
            conn.close()
        if result is None:
            message = "No ALL.TXT data imported yet: the forecast is built from it. Import it below."
        else:
            age = (now.replace(tzinfo=None) - result.newest).days
    return render_template(
        "page.html", hour=hour, hours=range(24), result=result, message=message, imported=imported,
        stale=age if age is not None and age > cli.STALE_DAYS else None, my_grid=my_grid,
        env_name=cli.ENV_FILE.name, window_days=forecast.WINDOW_DAYS,
        show_problems=cli.SHOW_PROBLEMS, legend=cli.LEGEND, title=cli.hour_title(hour, now),
        all_hours=cli.ALL_HOURS, distance=cli.distance, rank=by, log_dir=cli._log_dir(),
        now_hour=now.hour, summary=summary, tab_title=_tab_title(result, hour, by), age_text=result and cli.data_age(result.newest, now), kind_for_name=folder.kind_for_name,
        best_bet=result and cli.best_bet_line(result, by), ranked=result and forecast.rank(result.bands, by),
        thin=result and cli.thin_line(result), overview=overview, overview_key=cli.overview_key(by, now),
        local_short=lambda h: cli.local_short(h, now),
        overview_notes=overview.notes(now) if overview else [],
        overview_empty=cli.OVERVIEW_EMPTY,
    )


def _tab_title(result: forecast.Forecast | None, hour: int | None, by: str) -> str:
    """The browser tab: the answer at a glance while the page sits in a tab."""
    if result is None:
        return "FT8 forecast"
    parts = ["FT8 forecast", "all hours" if hour is None else f"{hour:02d}:00 UTC"]
    if best := forecast.best_bet(result.bands, by):
        parts.append(f"best bet {best.band}")
    return " · ".join(parts)
