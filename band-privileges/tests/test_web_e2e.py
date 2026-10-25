"""The web page in a real browser (Playwright + Chromium, headless).

Robot Framework comparison: the `page` fixture is New Browser/New Page in a
Test Setup; `live_server` is a Suite Setup that starts the app; `expect(...)`
assertions wait and retry like Wait Until... keywords, so there are no sleeps.
"""

import threading

import pytest
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server

from band_privileges.web import create_app


@pytest.fixture(scope="module")
def live_server():
    # Port 0 asks the OS for any free port, so parallel runs never collide.
    server = make_server("127.0.0.1", 0, create_app())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _check(page: Page, url: str, freq: str, mode: str, license_class: str) -> None:
    page.goto(url)
    page.get_by_label("Frequency (MHz)").fill(freq)
    page.get_by_label("Mode").select_option(mode)
    page.get_by_label("License class").select_option(license_class)
    page.get_by_role("button", name="Check").click()


def test_allowed_answer_with_citations(page: Page, live_server):
    _check(page, live_server, "14.074", "data", "general")
    expect(page.get_by_role("heading", name="ALLOWED")).to_be_visible()
    expect(page.get_by_text("§97.301(d), §97.305(c)(3)(ix)")).to_be_visible()


def test_note_and_warning_are_visible(page: Page, live_server):
    _check(page, live_server, "28.300", "phone", "technician")
    expect(page.get_by_text("Note: SSB only (J3E/R3E), §97.307(f)(10)")).to_be_visible()
    expect(page.get_by_text("Warning: within 3 kHz of 28.300 MHz")).to_be_visible()


def test_bad_input_shows_the_message_and_keeps_what_was_typed(page: Page, live_server):
    _check(page, live_server, "14074", "data", "general")
    expect(page.get_by_role("alert")).to_contain_text("did you mean 14.074 MHz?")
    expect(page.get_by_label("Frequency (MHz)")).to_have_value("14074")
    expect(page.get_by_label("Mode")).to_have_value("data")  # choices survive too


def test_keyboard_only_enter_submits(page: Page, live_server):
    page.goto(live_server)
    page.get_by_label("Frequency (MHz)").focus()
    page.keyboard.type("7.050")
    page.keyboard.press("Enter")  # defaults: cw, technician
    expect(page.get_by_role("heading", name="ALLOWED")).to_be_visible()


def test_stylesheet_loads_under_the_csp(page: Page, live_server):
    # The CSP allows only our own stylesheet; prove the browser applied it and
    # reported no CSP violations (a too-strict policy would silently unstyle).
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto(live_server)
    expect(page.locator("body")).to_have_css("background-color", "rgb(250, 248, 243)")
    assert errors == []


def test_phone_width_needs_no_sideways_scrolling(page: Page, live_server):
    page.set_viewport_size({"width": 360, "height": 740})
    _check(page, live_server, "28.300", "phone", "technician")  # longest content
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0
