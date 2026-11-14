"""The web page in a real browser (Chromium via Playwright): layout, dark mode, the form, the CSP.

The HTML tests in test_web.py check what the server sends; these check what a
browser makes of it, which they can't: CSS widths, media queries, form navigation.
Setup: `playwright install chromium` once (README).
"""

import re
import threading
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from ft8_forecast import Contact, Decode, cli, web
from ft8_forecast.store import open_db, save_contacts, save_decodes

NOW = datetime(2026, 10, 27, 15, 5, tzinfo=UTC)
HINT = "Scroll the table sideways for more"
RX = b"261027_143015    14.074 Rx FT8     -9  0.2  627 CQ N0CALL FN31\n"


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The real app on a free 127.0.0.1 port; yields its URL. 5 days of 20 m at 15 UTC, and the
    widest cells the author's real data gives (all hours, 2026-10-29): 5-digit distances with
    grids in both Farthest columns, 3-digit contacts and "269 of 1,959" Calling CQ."""
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("MY_GRID=FN31\n")
    db = tmp_path / "ft8cast.sqlite"
    conn = open_db(db)
    newest = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
    save_decodes(conn, [Decode(newest - timedelta(days=n), 14_074_000, False, -10, f"N{n}CALL", "PF95",
                               f"CQ N{n}CALL PF95") for n in range(5)])
    save_decodes(conn, [Decode(newest - timedelta(days=1), 14_074_000, False, -10, "N0CALL", "PF95", "CQ N0CALL PF95")])
    midnight = newest.replace(hour=0, minute=0, second=0)
    cqs = [midnight - timedelta(days=2) + timedelta(seconds=30 * n) for n in range(1959)]
    save_decodes(conn, [Decode(when, 14_074_000, True, 0, "N9CALL", "FN31", "CQ N9CALL FN31") for when in cqs])
    save_decodes(conn, [Decode(when + timedelta(seconds=15), 14_074_000, False, -10, "N1CALL", "PF95", "N9CALL N1CALL PF95")
                        for when in cqs[:269]])
    save_contacts(conn, [Contact("N1CALL", midnight - timedelta(days=1) + timedelta(minutes=5 * n), 14_074_000, "PF95")
                         for n in range(110)])
    conn.close()
    httpd = make_server("127.0.0.1", 0, web.create_app(db))  # port 0: the OS picks a free one
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()
    thread.join()


def overflows(page, selector):
    return page.eval_on_selector(selector, "el => el.scrollWidth > el.clientWidth")


@pytest.mark.parametrize("width", [360, 600, 700, 720, 740, 760, 780, 900, 1280])
def test_the_scroll_hint_shows_whenever_the_table_overflows(page, server, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(server)
    hint = page.get_by_text(HINT)
    if overflows(page, "div.scroll"):
        expect(hint).to_be_visible()
    if width >= 1280:
        assert not overflows(page, "div.scroll")
        expect(hint).to_be_hidden()


@pytest.mark.parametrize("width", [800, 1024, 1440])
def test_on_a_computer_the_widest_table_fits_without_scrolling(page, server, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(server + "?hour=all")
    # The forecast table is the one with a Contacts column; the overview and daily tables repeat values.
    table = page.get_by_role("table").filter(has=page.get_by_role("columnheader", name=re.compile("Contacts")))
    expect(table.get_by_role("cell", name=re.compile(r"10,\d{3} mi"))).to_have_count(2)  # in both Farthest columns
    expect(page.locator("table.answered").get_by_role("cell", name="269 of 1,959 (14%)")).to_be_visible()
    assert not overflows(page, "div.scroll")
    assert not overflows(page, "html")  # the Answered table doesn't push the page sideways either
    expect(page.get_by_text(HINT)).to_be_hidden()


def test_on_a_phone_the_table_scrolls_not_the_page(page, server):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(server)
    assert overflows(page, "div.scroll")
    assert not overflows(page, "html")  # no sideways scrolling of the whole page
    last = page.get_by_role("columnheader", name=re.compile("Contacts"))
    last.scroll_into_view_if_needed()
    expect(last).to_be_in_viewport()


def body_brightness(page):
    rgb = page.evaluate("getComputedStyle(document.body).backgroundColor")
    return sum(int(n) for n in re.findall(r"\d+", rgb)[:3])


def test_dark_mode_darkens_the_page(page, server):
    page.goto(server)
    page.emulate_media(color_scheme="light")
    light = body_brightness(page)
    page.emulate_media(color_scheme="dark")
    assert body_brightness(page) < light / 2


def test_choosing_an_hour_shows_its_forecast(page, server):
    page.goto(server)
    page.get_by_label("UTC hour").select_option("9")
    page.get_by_role("button", name="Show").click()
    expect(page).to_have_url(re.compile(r"[?&]hour=9(&|$)"))
    expect(page.get_by_role("heading", level=2, name=re.compile("FT8 forecast for 09:00-09:59 UTC"))).to_be_visible()
    expect(page.get_by_label("UTC hour")).to_have_value("9")


def test_the_csp_blocks_an_injected_script(page, server):
    """An attacker's <script> in the page (say, via a missed escape) must not run."""
    page.goto(server)
    violations = []
    page.on("console", lambda message: violations.append(message.text) if "Content Security Policy" in message.text else None)
    with pytest.raises(Exception):
        page.add_script_tag(content="window.injected = true")
    assert page.evaluate("window.injected") is None
    assert violations


def test_settings_can_be_saved_from_the_page(page, server):
    page.goto(server)
    page.get_by_label("Grid square").fill("em79")
    page.get_by_role("button", name="Save settings").click()
    expect(page.get_by_role("status")).to_have_text("Settings saved.")
    expect(page.get_by_label("Grid square")).to_have_value("EM79")


def test_settings_form_fits_a_phone(page, server):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(server)
    assert not overflows(page, "html")


# --- the Importing... indicator (2026-11-13): the app's window has no browser spinner ---

def _stay_on_the_page(page):
    """Cancel the form's navigation after the page's own script has seen the submit: Playwright
    waits for a page load to finish before looking, so a held load would hide the busy state."""
    page.evaluate("window.addEventListener('submit', (event) => event.preventDefault())")


def test_importing_shows_it_is_working_and_blocks_a_second_click(page, server):
    page.goto(server)
    _stay_on_the_page(page)
    page.set_input_files("#log", files=[{"name": "ALL.TXT", "mimeType": "text/plain", "buffer": RX}])
    page.click("form.upload button")
    expect(page.get_by_role("status")).to_have_text("Importing ALL.TXT\u2026 a big file takes a few seconds.")
    expect(page.locator("form[data-busy] button")).to_have_count(1)  # no folder set: just Import
    expect(page.locator("form.upload button")).to_be_disabled()


def test_the_import_still_goes_through_with_the_script(page, server):
    page.goto(server)
    page.set_input_files("#log", files=[{"name": "ALL.TXT", "mimeType": "text/plain", "buffer": RX}])
    page.click("form.upload button")
    expect(page.get_by_role("heading", name="Imported")).to_be_visible()
    expect(page.get_by_role("status")).to_be_hidden()
    expect(page.locator("form.upload button")).to_be_enabled()


def test_a_file_name_is_shown_as_text_never_html(page, server):
    page.goto(server)
    _stay_on_the_page(page)
    name = "<img src=x onerror=window.pwned=1>.txt"
    page.set_input_files("#log", files=[{"name": name, "mimeType": "text/plain", "buffer": RX}])
    page.click("form.upload button")
    expect(page.get_by_role("status")).to_contain_text(name)
    assert page.evaluate("window.pwned") is None and page.locator("#busy img").count() == 0


# --- heard map zoom (static/map.js, 2026-11-13) ---

WORLD = [0, 10, 360, 150]


def box(page):
    return [float(n) for n in page.locator("svg.map").get_attribute("viewBox").split()]


def map_point(page, x, y):
    """The map coordinates (degrees) under a screen point."""
    return page.eval_on_selector("svg.map", """(svg, [x, y]) => {
        const p = new DOMPoint(x, y).matrixTransform(svg.getScreenCTM().inverse());
        return [p.x, p.y]; }""", [x, y])


@pytest.fixture
def map_page(page, server):
    errors = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.set_viewport_size({"width": 1000, "height": 900})
    page.goto(server)
    page.locator("svg.map").scroll_into_view_if_needed()
    yield page
    assert errors == []  # a CSP refusal would show here


def test_zoom_buttons_appear_and_the_map_opens_at_the_fitted_view(map_page):
    expect(map_page.locator(".zoom")).to_be_visible()
    svg = map_page.locator("svg.map")
    assert svg.get_attribute("viewBox") == svg.get_attribute("data-fit")


def test_plus_and_minus_zoom_about_the_middle_and_stop_at_their_limits(map_page):
    x, y, w, h = box(map_page)
    map_page.get_by_role("button", name="Zoom in").click()
    x2, y2, w2, h2 = box(map_page)
    assert w2 == pytest.approx(w / 1.5) and (x2 + w2 / 2, y2 + h2 / 2) == pytest.approx((x + w / 2, y + h / 2))
    for _ in range(20):
        map_page.get_by_role("button", name="Zoom in").click()
    assert box(map_page)[2] == pytest.approx(6)  # about 6 degrees: closer shows nothing new
    for _ in range(20):
        map_page.get_by_role("button", name="Zoom out").click()
    assert box(map_page) == WORLD


def test_world_and_fit_buttons(map_page):
    fit = map_page.locator("svg.map").get_attribute("data-fit")
    map_page.get_by_role("button", name="World").click()
    assert box(map_page) == WORLD
    map_page.get_by_role("button", name="Fit").click()
    expect(map_page.locator("svg.map")).to_have_attribute("viewBox", fit)


def test_wheel_zooms_toward_the_pointer(map_page):
    r = map_page.locator("svg.map").bounding_box()
    px, py = r["x"] + r["width"] * 0.25, r["y"] + r["height"] * 0.6
    before = map_point(map_page, px, py)
    width = box(map_page)[2]
    map_page.mouse.move(px, py)
    map_page.mouse.wheel(0, -200)
    expect(map_page.locator("svg.map")).not_to_have_attribute("viewBox", map_page.locator("svg.map").get_attribute("data-fit"))
    assert box(map_page)[2] < width
    assert map_point(map_page, px, py) == pytest.approx(before, abs=0.05)  # the spot under the pointer stays put


def test_dragging_pans_with_the_pointer_and_stops_at_the_edge(map_page):
    map_page.get_by_role("button", name="Zoom in").click()
    r = map_page.locator("svg.map").bounding_box()
    cx, cy = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
    grabbed = map_point(map_page, cx, cy)
    map_page.mouse.move(cx, cy)
    map_page.mouse.down()
    map_page.mouse.move(cx + 60, cy + 20, steps=5)
    map_page.mouse.up()
    assert map_point(map_page, cx + 60, cy + 20) == pytest.approx(grabbed, abs=0.05)  # the map moved with it
    map_page.mouse.move(cx, cy)
    map_page.mouse.down()
    map_page.mouse.move(cx + 5000, cy, steps=5)  # far past the map's west edge
    map_page.mouse.up()
    assert box(map_page)[0] == 0
