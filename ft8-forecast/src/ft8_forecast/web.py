"""ft8cast serve: the forecast and file import as a local web page.

Only this machine can reach it: `ft8cast serve` binds to 127.0.0.1. Any site open in
your browser can still send requests to localhost, so every request must name
this server in its Host header (stops DNS rebinding) and every upload must come
from this page's own Origin (stops cross-site request forgery). The page's two scripts
(static/busy.js, static/map.js) are served from here, and nothing is loaded from other sites (the heard
map's outline is built in), so it makes no web calls either.
Jinja escapes everything inserted into the page, including text from your files.
"""

import argparse
import traceback
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, current_app, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from ft8_forecast import cli, folder, forecast
from ft8_forecast.logs import TooLarge, read_log, save_log
from ft8_forecast.store import StoreError, open_db

# Your ALL.TXT is about 27 MB for 48 days; 500 MB is years of listening.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
LOCAL_NAMES = {"127.0.0.1", "localhost"}
MAX_NAME = 80  # characters of an uploaded file's name to show
# The heard map: stations in a square at or above each step get the next darker shade (heard1-heard4).
MAP_SHADES = (1, 2, 4, 10)
MAP_KEY = "Lighter to darker: 1, 2-3, 4-9, 10 or more stations heard in a square on 2 or more days."
MAP_BANDS = [name for name, _, _ in forecast.BANDS]
# Map view boxes (degrees, x = longitude + 180, y = 90 - latitude): the whole map, 80 N to 70 S;
# the opening view fits the squares with a margin, at the map's shape, never closer than MAP_MIN_WIDTH.
MAP_WORLD = (0, 10, 360, 150)
MAP_MARGIN = (4, 2)
MAP_MIN_WIDTH = 48
START_MESSAGE = "Import your latest log below to start, or use the data saved from earlier."

_HEADERS = {
    # Scripts and styles only from this server, never inline (static/busy.js only says an import is
    # working; static/map.js only zooms the heard map); no outside fonts or images; forms only post back here; no framing.
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; form-action 'self'; "
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


def log_failure(log: Path, error: BaseException) -> None:
    """One line: the error's type and where. Never its message, which can quote your logs."""
    frames = traceback.extract_tb(error.__traceback__)
    where = f" at {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
    try:
        with log.open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC {type(error).__name__}{where}\n")
    except OSError:
        pass  # nothing can be done, and this already runs while reporting an error


def create_app(db: Path, log_file: Path | None = None, prompt_on_start: bool = False) -> Flask:
    """log_file: for the standalone app, which has no terminal. Without it, errors go to the terminal.
    prompt_on_start: also the app's (the user's choice, 2026-11-13). Saved data is kept, but each
    launch asks for a fresh log first, offering the saved data instead; importing or choosing it
    shows the forecast for the rest of the launch. One flag per server: the app serves one user."""
    app = Flask(__name__)
    app.config["DB"] = db
    app.config["STARTED"] = not prompt_on_start
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

    @app.context_processor
    def settings_form():
        # Raw values, so a bad one can be seen and fixed even on the page showing its error.
        return {"settings": {"my_grid": cli._env("MY_GRID") or "", "log_dir": cli._env("LOG_DIR") or ""}}

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
        band = request.args.get("band")
        if band is not None and band not in MAP_BANDS:
            raise PageError(400, f"Map band must be one of {', '.join(MAP_BANDS)}.")
        return _render(db, hour, by, start=not app.config["STARTED"], band=band)  # hour None: now; cli.ALL_HOURS: the whole day

    @app.post("/start")
    def use_saved_data():
        app.config["STARTED"] = True
        return _render(db, None, "busiest")

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
        app.config["STARTED"] = True
        return _render(db, None, "busiest", imported=[{"name": name, "log": log, "new": new, "error": None}])

    @app.post("/import-folder")
    def import_from_folder():
        # The folder comes only from the saved LOG_DIR, never from this request.
        try:
            logs = cli._log_dir()
        except ValueError as error:
            raise PageError(500, f"Log folder in Settings: {error}") from None
        if logs is None:
            raise PageError(400, "Set the log folder in Settings to import from a folder.")
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
        app.config["STARTED"] = True
        return _render(db, None, "busiest", imported=[
            {"name": r.path.name[:MAX_NAME], "log": r.log, "new": r.new, "error": r.error} for r in results])

    @app.post("/settings")
    def save_settings():
        try:
            cli.save_settings(request.form.get("my_grid", ""), request.form.get("log_dir", ""))
        except ValueError as error:
            raise PageError(400, str(error)) from None
        except OSError as error:
            raise PageError(500, f"Couldn't save settings: {error.strerror}") from None
        return _render(db, None, "busiest", saved=True, start=not app.config["STARTED"])

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
        # Details go to the terminal or log file, never to the page.
        if log_file is None:
            app.logger.exception("unexpected error")
            message = "Something went wrong; see the terminal."
        else:
            log_failure(log_file, error)
            message = f"Something went wrong; details are in {log_file}."
        return render_template("page.html", error=message, hours=range(24)), 500

    return app


def _open(db: Path):
    try:
        return open_db(db)
    except StoreError as error:
        raise PageError(500, str(error)) from None


def _render(db: Path, hour: int | str | None, by: str, imported: list[dict] | None = None, saved: bool = False,
            start: bool = False, band: str | None = None) -> str:
    """start: show the app's start screen instead of a forecast from saved data.
    band: the heard map's band; None: the best bet's."""
    try:
        my_grid = cli._my_grid()  # the same .env and clock as the CLI
    except ValueError as error:
        raise PageError(500, f"Grid square in Settings: {error}") from None
    now = cli._now()
    hour = now.hour if hour is None else None if hour == cli.ALL_HOURS else hour
    result, age, message, overview, summary, use_saved = None, None, None, None, [], None
    if not db.is_file():
        message = ("No data yet. Import your WSJT-X ALL.TXT below, or press Import from folder." if cli._log_dir() else
                   "No data yet. Import your WSJT-X ALL.TXT below; add wsjtx_log.adi too for your contacts. "
                   "To import from a folder instead, set the log folder in Settings.")
    else:
        hours, result = _results(db, hour, my_grid, now)
        if result is not None:
            overview = cli.overview(hours, by)
            summary = cli.summary_lines(result, by, hours if hour is not None else None, now)
        if result is None:
            message = "No ALL.TXT data imported yet: the forecast is built from it. Import it below."
        elif start:
            message = START_MESSAGE
            use_saved = f"Use saved data (through {result.newest:%Y-%m-%d %H:%M} UTC, {cli.data_age(result.newest, now)})"
            result, overview, summary = None, None, []
        else:
            age = cli.age_days(result.newest, now)
    return render_template(
        "page.html", hour=hour, hours=range(24), result=result, message=message, imported=imported,
        stale=age is not None and age > cli.STALE_DAYS, stale_note=cli.STALE_NOTE, my_grid=my_grid,
        saved=saved, window_days=forecast.WINDOW_DAYS, answered=cli.answered, answered_notes=cli.ANSWERED_NOTES,
        show_problems=cli.SHOW_PROBLEMS, legend=cli.LEGEND, title=cli.hour_title(hour, now),
        all_hours=cli.ALL_HOURS, distance=cli.distance, rank=by, log_dir=cli._log_dir(),
        now_hour=now.hour, summary=summary, tab_title=_tab_title(result, hour, by), age_text=result and cli.data_age(result.newest, now), kind_for_name=folder.kind_for_name,
        best_bet=result and cli.best_bet_line(result, by), ranked=result and forecast.rank(result.bands, by),
        thin=result and cli.thin_line(result), overview=overview, overview_key=cli.overview_key(by, now),
        local_short=lambda h: cli.local_short(h, now),
        overview_notes=overview.notes(now) if overview else [],
        overview_empty=cli.OVERVIEW_EMPTY, use_saved=use_saved,
        heard_map=result and _heard_map(result, by, band, my_grid), map_bands=MAP_BANDS, map_key=MAP_KEY, map_world=" ".join(map(str, MAP_WORLD)), band=band,
    )


def _heard_map(result: forecast.Forecast, by: str, band: str | None, my_grid: str | None) -> dict:
    """`band`'s squares (None: the best bet's) as map rectangles, and your square if your grid is set."""
    if band is not None:
        shown = next(stats for stats in result.bands if stats.band == band)
    else:  # without a best bet, the band with the most squares (the lowest band on a tie), if any has one
        most = max(result.bands, key=lambda stats: len(stats.squares))
        shown = forecast.best_bet(result.bands, by) or (most if most.squares else None)
    rects = []
    for grid, stations in sorted(shown.squares.items()) if shown else []:
        shade = sum(stations >= step for step in MAP_SHADES)
        rects.append((*_corner(grid), f"heard{shade}"))
    home = my_grid and _corner(my_grid)
    when = "at any hour" if result.hour is None else "at this hour"
    view = _fit([(x, y) for x, y, _ in rects] + ([home] if home else []))
    return {"band": shown and shown.band, "rects": rects, "home": home, "view": " ".join(f"{n:g}" for n in view),
            "empty": f"No grid squares heard on {shown.band if shown else 'any band'} {when} on 2 or more days."}


def _results(db: Path, hour: int | None, my_grid: str | None, now: datetime) -> tuple[list, forecast.Forecast | None]:
    """compute() for each hour 0-23, and for `hour` (None: all hours). The 24 take about 1 s on
    two months of listening, and only change when the data, the UTC hour or the grid does, so
    they're kept until then. Imports only ever add rows, so the newest row numbers catch an
    import from anywhere (`ft8cast import` and `watch` too); a file's modified time can be a
    whole second coarse."""
    conn = _open(db)
    try:
        newest = conn.execute("SELECT (SELECT max(rowid) FROM decodes), (SELECT max(rowid) FROM contacts)").fetchone()
        key = (newest, now.strftime("%Y-%m-%d %H"), my_grid)
        cache = current_app.config.get("RESULTS")
        if cache is None or cache["key"] != key:
            cache = current_app.config["RESULTS"] = {"key": key, "hours": None, "all": None}
        if cache["hours"] is None:
            cache["hours"] = [forecast.compute(conn, h, my_grid, now) for h in range(24)]
        if hour is None and cache["all"] is None and cache["hours"][0] is not None:  # only when asked for
            cache["all"] = forecast.compute(conn, None, my_grid, now)
    finally:
        conn.close()
    return cache["hours"], cache["all"] if hour is None else cache["hours"][hour]


def _fit(corners: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """The view box around these squares' top-left corners: margin added, widened to the map's
    shape and MAP_MIN_WIDTH, then moved back inside the map (the whole map if it's that big)."""
    left, top, world_w, world_h = MAP_WORLD
    if not corners:
        return MAP_WORLD
    x0, x1 = min(x for x, _ in corners) - MAP_MARGIN[0], max(x for x, _ in corners) + 2 + MAP_MARGIN[0]
    y0, y1 = min(y for _, y in corners) - MAP_MARGIN[1], max(y for _, y in corners) + 1 + MAP_MARGIN[1]
    width = max(x1 - x0, (y1 - y0) * world_w / world_h, MAP_MIN_WIDTH)
    if width >= world_w:
        return MAP_WORLD
    height = width * world_h / world_w
    x = min(max((x0 + x1 - width) / 2, left), left + world_w - width)
    y = min(max((y0 + y1 - height) / 2, top), top + world_h - height)
    return x, y, width, height


def _corner(grid: str) -> tuple[float, float]:
    """A square's top-left corner on the map: x = west longitude + 180, y = 90 - north latitude
    (plate carree, where every 2 x 1 degree square is the same rectangle)."""
    lat, lon = forecast._center(grid)
    return lon - 1 + 180, 90 - (lat + 0.5)


def _tab_title(result: forecast.Forecast | None, hour: int | None, by: str) -> str:
    """The browser tab: the answer at a glance while the page sits in a tab."""
    if result is None:
        return "FT8 forecast"
    parts = ["FT8 forecast", "all hours" if hour is None else f"{hour:02d}:00 UTC"]
    if best := forecast.best_bet(result.bands, by):
        parts.append(f"best bet {best.band}")
    return " · ".join(parts)
