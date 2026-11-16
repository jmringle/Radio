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
window.__cableCalls = [];
window.__calCalls = [];
window.__calError = null;
window.__cableAnswer = {ok: true, report: "Cable: 1.000-48.000 MHz sweep, 101 points\\n\\nFar end: open\\n",
                        smith_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-cable-smith" viewBox="0 0 10 10"><circle class="edge" cx="5" cy="5" r="5"/></svg>'};
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
    cable: (noAntenna, vf, length, longest) => {
      window.__cableCalls.push([noAntenna, vf, length, longest]);
      if (!window.__hold) return Promise.resolve(window.__cableAnswer);
      return new Promise(resolve => { window.__release = () => resolve(window.__cableAnswer); });
    },
    calibrate: (band, step) => {
      window.__calCalls.push([band, step]);
      const answer = window.__calError ? {ok: false, error: window.__calError}
                                       : {ok: true, next: {open: "short", short: "load", load: null}[step]};
      if (!window.__hold) return Promise.resolve(answer);
      return new Promise(resolve => { window.__release = () => resolve(answer); });
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
    app.evaluate('window.__answer = {ok: false, error: "The NanoVNA disconnected (unplugged or switched off). Reconnect it, switch it on, and try again."}')
    expect(app.get_by_role("alert")).to_have_text(re.compile("The NanoVNA disconnected"))
    expect(app.get_by_role("button", name="Live")).to_be_enabled()
    passes = len(app.evaluate("window.__calls"))
    app.wait_for_timeout(1000)
    assert len(app.evaluate("window.__calls")) == passes


def test_live_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    expect(page.get_by_role("button", name="Live")).to_be_disabled()


# --- the cable check: its own tab, and only with "No antenna connected" ticked -----------------
# The ARIA tab pattern: role=tab buttons in a role=tablist, each controlling a role=tabpanel; the
# arrow keys move between tabs. get_by_role("tab") finds them the way a screen reader does.

def cable_tab(app: Page):
    app.get_by_role("tab", name="Cable").click()
    return app


def test_tabs_switch_by_click_and_by_arrow_keys(app: Page):
    antenna, cable = app.get_by_role("tab", name="Antenna"), app.get_by_role("tab", name="Cable")
    expect(antenna).to_have_attribute("aria-selected", "true")
    expect(app.get_by_label("Velocity factor")).to_be_hidden()
    cable.click()
    expect(cable).to_have_attribute("aria-selected", "true")
    expect(app.get_by_label("Velocity factor")).to_be_visible()
    expect(app.get_by_label("Band", exact=True)).to_be_hidden()
    cable.press("ArrowLeft")
    expect(antenna).to_have_attribute("aria-selected", "true")
    expect(antenna).to_be_focused()
    expect(app.get_by_label("Band", exact=True)).to_be_visible()


def test_check_cable_needs_the_no_antenna_box(app: Page):
    cable_tab(app)
    check, box = app.get_by_role("button", name="Check cable"), app.get_by_label("No antenna connected")
    expect(check).to_be_disabled()
    box.check()
    expect(check).to_be_enabled()
    box.uncheck()
    expect(check).to_be_disabled()


def test_a_cable_check_shows_the_report_and_smith_chart_then_clears_the_box(app: Page):
    cable_tab(app)
    app.get_by_label("Velocity factor").fill("0.66")
    app.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.locator("#report")).to_contain_text("Far end: open")
    expect(app.locator("#smith svg.test-cable-smith")).to_be_visible()
    expect(app.locator("#swr svg")).to_have_count(0)  # no SWR plot for a cable
    assert app.evaluate("window.__cableCalls") == [[True, "0.66", "", "50 m"]]
    # Confirm again every time: the antenna might be back on by the next check.
    expect(app.get_by_label("No antenna connected")).not_to_be_checked()
    expect(app.get_by_role("button", name="Check cable")).to_be_disabled()


def test_a_cable_error_is_shown_and_the_box_clears_too(app: Page):
    app.evaluate('window.__cableAnswer = {ok: false, error: "Give Velocity factor or Length (one of them)"}')
    cable_tab(app)
    app.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.get_by_role("alert")).to_have_text("Give Velocity factor or Length (one of them)")
    expect(app.get_by_label("No antenna connected")).not_to_be_checked()


def test_nothing_else_can_start_during_a_cable_check(app: Page):
    app.evaluate("window.__hold = true")
    cable_tab(app)
    app.get_by_label("Length").fill("50ft")
    app.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text(re.compile("Checking the cable"))
    for control in (app.get_by_role("tab", name="Antenna"), app.get_by_role("button", name="Check cable"),
                    app.get_by_label("No antenna connected"), app.get_by_label("Length")):
        expect(control).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_role("tab", name="Antenna")).to_be_enabled()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text("")
    assert len(app.evaluate("window.__cableCalls")) == 1


@pytest.mark.parametrize("start", ["Sweep", "Live"])
def test_the_cable_tab_cant_be_opened_during_a_band_sweep(app: Page, start):
    app.evaluate("window.__hold = true")
    app.get_by_role("button", name=start).click()
    expect(app.get_by_role("tab", name="Cable")).to_be_disabled()
    if start == "Live":
        app.get_by_role("button", name="Stop").click()
    app.evaluate("window.__release()")
    expect(app.get_by_role("tab", name="Cable")).to_be_enabled()


def test_switching_tabs_clears_the_box_and_the_old_results(app: Page):
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).not_to_be_empty()
    cable_tab(app)
    expect(app.locator("#report")).to_be_empty()  # a band's SWR isn't this cable's
    expect(app.locator("#swr svg")).to_have_count(0)
    app.get_by_label("No antenna connected").check()
    app.get_by_role("tab", name="Antenna").click()
    cable_tab(app)
    expect(app.get_by_label("No antenna connected")).not_to_be_checked()


def test_check_cable_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    cable_tab(page)
    page.get_by_label("No antenna connected").check()
    expect(page.get_by_role("button", name="Check cable")).to_be_disabled()


# --- the Calibrate tab: open, short, load over one band ----------------------------------------

def calibrate_tab(page):
    page.get_by_role("tab", name="Calibrate").click()
    return page


def test_calibrate_needs_a_band(app: Page):
    calibrate_tab(app)
    band, measure = app.get_by_label("Band to calibrate"), app.get_by_role("button", name="Measure open")
    expect(band.locator("option")).to_have_count(7)  # "Choose a band" + 6 from Python
    expect(measure).to_be_disabled()
    band.select_option("40m")
    expect(measure).to_be_enabled()


def test_calibrating_walks_through_open_short_load(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    step = app.locator("#cal-instruction")
    expect(step).to_contain_text("Step 1 of 3")
    expect(step).to_contain_text("open standard")
    app.get_by_role("button", name="Measure open").click()
    expect(step).to_contain_text("Step 2 of 3")
    expect(step).to_contain_text("short standard")
    app.get_by_role("button", name="Measure short").click()
    expect(step).to_contain_text("Step 3 of 3")
    expect(step).to_contain_text("load standard")
    app.get_by_role("button", name="Measure load").click()
    expect(step).to_contain_text("Calibrated for 40m")
    expect(step).to_contain_text("switch the NanoVNA off and on")
    expect(app.get_by_role("button", name="Measure open")).to_be_enabled()  # ready to start a new one
    assert app.evaluate("window.__calCalls") == [["40m", "open"], ["40m", "short"], ["40m", "load"]]


def test_a_failed_step_stays_on_that_step(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_role("button", name="Measure open").click()
    app.evaluate('window.__calError = "The NanoVNA disconnected"')
    app.get_by_role("button", name="Measure short").click()
    expect(app.get_by_role("alert")).to_have_text("The NanoVNA disconnected")
    expect(app.locator("#cal-instruction")).to_contain_text("Step 2 of 3")
    app.evaluate("window.__calError = null")
    app.get_by_role("button", name="Measure short").click()
    expect(app.locator("#error")).to_be_empty()  # an empty alert leaves the accessibility tree
    expect(app.locator("#cal-instruction")).to_contain_text("Step 3 of 3")


def test_choosing_another_band_starts_over(app: Page):
    calibrate_tab(app)
    band = app.get_by_label("Band to calibrate")
    band.select_option("40m")
    app.get_by_role("button", name="Measure open").click()
    band.select_option("20m")
    expect(app.locator("#cal-instruction")).to_contain_text("Step 1 of 3")
    app.get_by_role("button", name="Measure open").click()
    assert app.evaluate("window.__calCalls")[-1] == ["20m", "open"]


def test_nothing_else_can_start_while_a_standard_is_measured(app: Page):
    app.evaluate("window.__hold = true")
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_role("button", name="Measure open").click()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text(re.compile("Measuring the open standard"))
    for control in (app.get_by_role("tab", name="Antenna"), app.get_by_role("tab", name="Cable"),
                    app.get_by_role("button", name="Measure open"), app.get_by_label("Band to calibrate")):
        expect(control).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_role("button", name="Measure short")).to_be_enabled()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text("")


# --- partway through a calibration (QA 2026-11-16) ----------------------------------------------
# After open, the NanoVNA's calibration is reset: a sweep then would be uncorrected but look normal.
# So the other tabs stay shut until load finishes, or until the calibration is cancelled.

def start_calibrating(app: Page, band="2m"):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option(band)
    app.get_by_role("button", name="Measure open").click()
    expect(app.get_by_role("button", name="Measure short")).to_be_enabled()


def test_the_other_tabs_stay_shut_partway_through_a_calibration(app: Page):
    start_calibrating(app)
    for name in ("Antenna", "Cable"):
        expect(app.get_by_role("tab", name=name)).to_be_disabled()
    expect(app.locator("#cal-instruction")).to_contain_text("other tabs open again")
    app.get_by_role("button", name="Measure short").click()
    expect(app.get_by_role("tab", name="Antenna")).to_be_disabled()
    app.get_by_role("button", name="Measure load").click()
    for name in ("Antenna", "Cable"):
        expect(app.get_by_role("tab", name=name)).to_be_enabled()


def test_the_arrow_keys_cant_get_round_the_shut_tabs(app: Page):
    start_calibrating(app)
    app.get_by_role("tab", name="Calibrate").press("ArrowRight")
    app.get_by_role("tab", name="Calibrate").press("ArrowLeft")
    expect(app.get_by_role("tab", name="Calibrate")).to_have_attribute("aria-selected", "true")
    expect(app.get_by_label("Band to calibrate")).to_be_visible()


def test_choosing_no_band_cancels_a_calibration_and_opens_the_tabs(app: Page):
    start_calibrating(app)
    app.get_by_label("Band to calibrate").select_option("")
    expect(app.get_by_role("tab", name="Antenna")).to_be_enabled()


def test_a_failed_open_keeps_the_tabs_open(app: Page):
    # Nothing to finish on the page: the error itself says how to get the saved calibration back.
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("2m")
    app.evaluate('window.__calError = "The NanoVNA disconnected"')
    app.get_by_role("button", name="Measure open").click()
    expect(app.get_by_role("alert")).to_have_text("The NanoVNA disconnected")
    expect(app.get_by_role("tab", name="Antenna")).to_be_enabled()


# --- a sweep of another band than the one just calibrated (QA 2026-11-16) -------------------------

def calibrate_fully(app: Page, band):
    start_calibrating(app, band)
    app.get_by_role("button", name="Measure short").click()
    app.get_by_role("button", name="Measure load").click()
    expect(app.locator("#cal-instruction")).to_contain_text(f"Calibrated for {band}")
    app.get_by_role("tab", name="Antenna").click()


def test_sweeping_another_band_than_the_calibrated_one_says_so(app: Page):
    calibrate_fully(app, "2m")  # the fake sweep answers for 40m
    app.get_by_role("button", name="Sweep").click()
    report = app.locator("#report")
    expect(report).to_contain_text("Best match")
    expect(report).to_contain_text("calibrated for 2m")
    expect(report).to_contain_text("not for 40m")


def test_sweeping_the_calibrated_band_says_nothing_of_it(app: Page):
    calibrate_fully(app, "40m")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).to_contain_text("Best match")
    expect(app.locator("#report")).not_to_contain_text("calibrated for")


def test_with_no_calibration_this_session_a_sweep_says_nothing_of_it(app: Page):
    app.get_by_label("Band", exact=True).select_option("40m")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).to_contain_text("Best match")
    expect(app.locator("#report")).not_to_contain_text("calibrated for")


def test_the_arrow_keys_reach_the_calibrate_tab(app: Page):
    antenna = app.get_by_role("tab", name="Antenna")
    antenna.press("ArrowLeft")  # wraps round from the first tab to the last
    expect(app.get_by_role("tab", name="Calibrate")).to_have_attribute("aria-selected", "true")
    expect(app.get_by_label("Band to calibrate")).to_be_visible()


def test_calibrate_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    calibrate_tab(page)
    expect(page.get_by_role("button", name="Measure open")).to_be_disabled()


def test_the_app_is_called_dipstick_with_a_capital_d(app: Page):
    expect(app).to_have_title("Dipstick")
    expect(app.get_by_role("heading", level=1)).to_have_text("Dipstick")
