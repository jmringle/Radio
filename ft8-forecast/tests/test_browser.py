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
    page.get_by_label("License class").select_option("extra")
    page.get_by_role("button", name="Save settings").click()
    expect(page.get_by_role("status")).to_have_text("Settings saved.")
    expect(page.get_by_label("Grid square")).to_have_value("EM79")
    expect(page.get_by_label("License class")).to_have_value("extra")


def test_settings_form_fits_a_phone(page, server):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(server)
    assert not overflows(page, "html")
