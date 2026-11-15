"""The app's page in real browser engines (Chromium, which Windows' WebView2 uses, and WebKit,
which macOS and Linux use), with a fake window.pywebview.api: no Python bridge, no hardware.

Playwright notes (compared with Robot Framework's Browser library):
- `page` is a fresh browser tab per test, like `New Page` in a test setup.
- get_by_role / get_by_label find elements the way a user or screen reader does, so an unlabeled
  control fails the test.
- expect(...) retries until it passes or times out: auto-waiting, like `Wait Until ...` keywords.
- add_init_script runs before the page's own scripts: here it plants the fake API.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

PAGE = (Path(__file__).parents[1] / "src" / "dipstick" / "ui" / "index.html").as_uri()

FAKE_API = """
window.__calls = [];
window.__answer = {ok: true, band: "40m", report: "40m: 7.000-7.300 MHz, 101 points\\n\\nBest match: SWR 1.20 at 7.150 MHz (excellent)\\n",
                   swr_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-swr" viewBox="0 0 10 10"><polyline class="swr" points="0,0 10,10"/></svg>',
                   smith_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-smith" viewBox="0 0 10 10"><circle class="edge" cx="5" cy="5" r="5"/></svg>'};
window.__hold = false;
window.__nanovna = {connected: true, text: "NanoVNA connected (/dev/cu.usbmodem401)"};
window.__release = null;
// Like real pywebview (its js/api.js and js/finish.js, 6.2.1): window.pywebview.api starts as an
// EMPTY object, the functions are added later, and only then does "pywebviewready" fire.
window.pywebview = {api: {}};
setTimeout(() => {
  Object.assign(window.pywebview.api, {
    bands: async () => ["160m", "80m", "40m", "20m", "2m", "70cm"],
    nanovna: async () => window.__nanovna,
    sweep: (band, target, points) => {
      window.__calls.push([band, target, points]);
      if (!window.__hold) return Promise.resolve(window.__answer);
      return new Promise(resolve => { window.__release = () => resolve(window.__answer); });
    },
  });
  window.dispatchEvent(new CustomEvent("pywebviewready"));
}, 50);
"""


# WebKit draws a <select>'s insides with an inline style of its own, then reports its own CSP
# violation for it (found 2026-11-15 by removing controls one at a time: only the <select> does
# it). It's harmless and not from dipstick's code; Chromium has no such quirk, so it still catches
# any real inline style.
WEBKIT_SELECT_QUIRK = ("Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' "
                       "does not appear in the style-src directive of the Content Security Policy.")


@pytest.fixture
def app(page: Page, browser_name):
    errors = []

    def on_console(msg):
        if msg.type == "error" and not (browser_name == "webkit" and msg.text == WEBKIT_SELECT_QUIRK):
            errors.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.add_init_script(FAKE_API)
    page.goto(PAGE)
    yield page
    assert errors == []  # includes Content Security Policy violations


def test_sweep_waits_until_python_is_reachable(page: Page):
    # pywebview's functions arrive a moment after the page loads; a click before then would fail.
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))  # Python never gets there in time
    page.goto(PAGE)
    expect(page.get_by_role("button", name="Sweep")).to_be_disabled()


def test_the_band_list_comes_from_python_and_starts_on_choose_a_band(app: Page):
    band = app.get_by_label("Band", exact=True)
    expect(band).to_have_value("")
    expect(band.locator("option")).to_have_count(7)  # "Choose a band" + 6 from Python
    expect(band.locator("option").first).to_have_text("Choose a band")


def test_sweep_shows_the_report_and_both_plots(app: Page):
    app.get_by_label("Band", exact=True).select_option("40m")
    app.get_by_label("Target").fill("7.074")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).to_contain_text("Best match: SWR 1.20 at 7.150 MHz")
    expect(app.locator("#swr svg.test-swr")).to_be_visible()
    expect(app.locator("#smith svg.test-smith")).to_be_visible()
    assert app.evaluate("window.__calls") == [["40m", "7.074", 101]]


def test_a_target_alone_is_sent_with_no_band_and_the_band_used_is_shown(app: Page):
    app.evaluate('window.__answer = Object.assign({}, window.__answer, {band: "2m"})')
    app.get_by_label("Target").fill("146.520")
    app.get_by_role("button", name="Sweep").click()
    expect(app.get_by_label("Band", exact=True)).to_have_value("2m")
    assert app.evaluate("window.__calls") == [["", "146.520", 101]]


def test_the_chosen_band_is_sent(app: Page):
    app.get_by_label("Band", exact=True).select_option("2m")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).not_to_be_empty()
    assert app.evaluate("window.__calls")[0][0] == "2m"


def test_an_error_is_shown_as_an_alert_and_old_results_are_cleared(app: Page):
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).not_to_be_empty()
    app.evaluate('window.__answer = {ok: false, error: "No NanoVNA found. Is it plugged in?"}')
    app.get_by_role("button", name="Sweep").click()
    expect(app.get_by_role("alert")).to_have_text("No NanoVNA found. Is it plugged in?")
    expect(app.locator("#report")).to_be_empty()
    expect(app.locator("#swr svg")).to_have_count(0)


def test_one_sweep_at_a_time_from_the_page(app: Page):
    app.evaluate("window.__hold = true")
    sweep = app.get_by_role("button", name="Sweep")
    sweep.click()
    expect(sweep).to_be_disabled()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text(re.compile("Sweeping"))
    sweep.click(force=True)  # a second click while it runs does nothing
    app.get_by_label("Target", exact=True).press("Enter")  # nor does Enter in the target field
    app.evaluate("window.__release()")
    expect(sweep).to_be_enabled()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text("")
    assert len(app.evaluate("window.__calls")) == 1


def test_report_text_is_shown_as_text_not_markup(app: Page):
    # The report is plain text: markup in it must show as characters, never run (defense in depth).
    app.evaluate('window.__answer = {ok: true, report: "<img src=x onerror=alert(1)>", swr_svg: "", smith_svg: ""}')
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).to_have_text("<img src=x onerror=alert(1)>")
    expect(app.locator("#report img")).to_have_count(0)



def test_the_pages_security_policy():
    # pywebview runs everything through eval (its bridge functions are built with new Function, and
    # evaluate_js wraps code in eval), so 'unsafe-eval' is required: without it the real window
    # can't reach Python (found 2026-11-15). Playwright's own evaluate skips the policy, so a browser
    # test can't catch that; test_window.py does, in the real window. Everything else stays shut.
    html = (Path(__file__).parents[1] / "src" / "dipstick" / "ui" / "index.html").read_text()
    policy = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html).group(1)
    rules = {d.split()[0]: d.split()[1:] for d in policy.split(";") if d.strip()}
    assert rules["default-src"] == ["'none'"]
    assert rules["script-src"] == ["'self'", "'unsafe-eval'"]  # no 'unsafe-inline', no hosts
    assert rules["style-src"] == ["'self'"]
    assert rules["form-action"] == ["'none'"] and rules["base-uri"] == ["'none'"]


# --- is a NanoVNA plugged in? ------------------------------------------------------------------

def test_the_connection_line_follows_the_nanovna(app: Page):
    connection = app.get_by_role("status", name="NanoVNA")
    expect(connection).to_have_text("NanoVNA connected (/dev/cu.usbmodem401)")
    app.evaluate('window.__nanovna = {connected: false, text: "No NanoVNA found. Is it plugged in and switched on?"}')
    expect(connection).to_have_text("No NanoVNA found. Is it plugged in and switched on?")  # within a poll or two
    expect(connection).to_have_class(re.compile("missing"))


# --- live mode: sweep again and again while you trim -------------------------------------------
# page.wait_for_function retries a JavaScript condition until it's true, the way expect() retries
# an assertion (like Robot's `Wait Until Keyword Succeeds`).

def test_live_sweeps_again_and_again_until_stopped(app: Page):
    app.get_by_label("Band", exact=True).select_option("40m")
    app.get_by_role("button", name="Live").click()
    app.wait_for_function("window.__calls.length >= 3")
    expect(app.get_by_role("status", name="Sweep status")).to_have_text(re.compile(r"Live: pass \d+"))
    app.get_by_role("button", name="Stop").click()
    expect(app.get_by_role("button", name="Live")).to_be_enabled()
    passes = len(app.evaluate("window.__calls"))
    app.wait_for_timeout(1000)
    assert len(app.evaluate("window.__calls")) == passes  # stopped means stopped
    assert all(call == ["40m", "", 101] for call in app.evaluate("window.__calls"))


def test_stop_lets_the_pass_in_progress_finish(app: Page):
    # A pass can't be cut off halfway: the NanoVNA's settings are put back at the end of each one.
    app.evaluate("window.__hold = true")
    app.get_by_role("button", name="Live").click()
    app.get_by_role("button", name="Stop").click()
    stopping = app.get_by_role("button", name="Stopping…")
    expect(stopping).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_role("button", name="Live")).to_be_enabled()
    expect(app.locator("#report")).not_to_be_empty()  # the last pass is still shown
    assert len(app.evaluate("window.__calls")) == 1


def test_the_controls_are_locked_during_live(app: Page):
    app.evaluate("window.__hold = true")
    app.get_by_role("button", name="Live").click()
    for control in (app.get_by_label("Band", exact=True), app.get_by_label("Target", exact=True),
                    app.get_by_role("button", name="Sweep")):
        expect(control).to_be_disabled()
    app.get_by_role("button", name="Stop").click()
    app.evaluate("window.__release()")
    for control in (app.get_by_label("Band", exact=True), app.get_by_label("Target", exact=True),
                    app.get_by_role("button", name="Sweep")):
        expect(control).to_be_enabled()


def test_an_error_stops_live_and_says_why(app: Page):
    app.get_by_role("button", name="Live").click()
    app.wait_for_function("window.__calls.length >= 2")
    app.evaluate('window.__answer = {ok: false, error: "The NanoVNA disconnected (read failed). Plug it back in and try again."}')
    expect(app.get_by_role("alert")).to_have_text(re.compile("The NanoVNA disconnected"))
    expect(app.get_by_role("button", name="Live")).to_be_enabled()
    passes = len(app.evaluate("window.__calls"))
    app.wait_for_timeout(1000)
    assert len(app.evaluate("window.__calls")) == passes


def test_live_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    expect(page.get_by_role("button", name="Live")).to_be_disabled()
