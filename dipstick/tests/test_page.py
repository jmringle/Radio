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
window.__lengths = [];
window.__answer = {ok: true, band: "40m", report: "40m: 7.000-7.300 MHz, 101 points\\n\\nBest match: SWR 1.20 at 7.150 MHz (excellent)\\n",
                   detail: "What the NanoVNA measured: 101 frequencies\\n  At each one it sent a tiny test signal\\n",
                   swr_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-swr" viewBox="0 0 10 10"><polyline class="swr" points="0,0 10,10"/></svg>',
                   smith_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-smith" viewBox="0 0 10 10"><circle class="edge" cx="5" cy="5" r="5"/></svg>'};
window.__hold = false;
window.__nanovna = {connected: true, text: "NanoVNA connected (/dev/cu.usbmodem401)"};
window.__release = null;
window.__cableCalls = [];
window.__calCalls = [];
window.__calBoxes = [];
window.__calBoth = [];
window.__balunCalls = [];
window.__balunAnswer = {ok: true, report: "49:1 transformer, 2450-ohm resistor: SWR 2 or under on every band from 160m to 6m.\\n",
                        swr_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-balun-swr" viewBox="0 0 10 10"><rect class="ham-band" x="1" y="0" width="1" height="10"/></svg>'};
window.__chokeCalls = [];
window.__chokeAnswer = {ok: true, report: "Choke: good on 160m, 80m, 40m.\\n"};
window.__lossCalls = [];
window.__lossAnswer = {ok: true, report: "Through loss, direct: most 0.50 dB on 6m, least 0.10 dB on 160m.\\n"};
window.__calError = null;
window.__settings = {quiz: true, detail: false};
window.__saved = [];
window.__detailSaved = [];
window.__saveAnswer = {ok: true};
window.__ports = {ports: [], remembered: []};
window.__portCalls = 0;
window.__used = [];
window.__forgot = 0;
window.__portAnswer = {ok: true};
window.__cableAnswer = {ok: true, report: "Cable: 1.000-48.000 MHz sweep, 101 points\\n\\nFar end: open\\n",
                        smith_svg: '<svg xmlns="http://www.w3.org/2000/svg" class="test-cable-smith" viewBox="0 0 10 10"><circle class="edge" cx="5" cy="5" r="5"/></svg>'};
// Like real pywebview (its js/api.js and js/finish.js, 6.2.1): window.pywebview.api starts as an
// EMPTY object, the functions are added later, and only then does "pywebviewready" fire.
window.pywebview = {api: {}};
setTimeout(() => {
  Object.assign(window.pywebview.api, {
    bands: async () => ["160m", "80m", "40m", "20m", "2m", "70cm"],
    nanovna: async () => window.__nanovna,
    settings: async () => window.__settings,
    set_quiz: async (on) => { window.__saved.push(on); return window.__saveAnswer; },
    set_detail: async (on) => { window.__detailSaved.push(on); return window.__saveAnswer; },
    serial_ports: async () => { window.__portCalls++; if (window.__portsFail) throw new Error("port list failed"); return window.__ports; },
    use_port: async (device) => { window.__used.push(device); return window.__portAnswer; },
    forget_ports: async () => { window.__forgot++; return window.__portAnswer; },
    sweep: (band, target, points, length) => {
      window.__calls.push([band, target, points]);
      window.__lengths.push(length);
      if (!window.__hold) return Promise.resolve(window.__answer);
      return new Promise(resolve => { window.__release = () => resolve(window.__answer); });
    },
    cable: (noAntenna, vf, length, longest) => {
      window.__cableCalls.push([noAntenna, vf, length, longest]);
      if (!window.__hold) return Promise.resolve(window.__cableAnswer);
      return new Promise(resolve => { window.__release = () => resolve(window.__cableAnswer); });
    },
    transformer: (noAntenna, ratio, resistor) => {
      window.__balunCalls.push([noAntenna, ratio, resistor]);
      if (!window.__hold) return Promise.resolve(window.__balunAnswer);
      return new Promise(resolve => { window.__release = () => resolve(window.__balunAnswer); });
    },
    choke: (noAntenna) => {
      window.__chokeCalls.push(noAntenna);
      if (!window.__hold) return Promise.resolve(window.__chokeAnswer);
      return new Promise(resolve => { window.__release = () => resolve(window.__chokeAnswer); });
    },
    loss: (noAntenna, connection) => {
      window.__lossCalls.push([noAntenna, connection]);
      if (!window.__hold) return Promise.resolve(window.__lossAnswer);
      return new Promise(resolve => { window.__release = () => resolve(window.__lossAnswer); });
    },
    calibrate: (band, step, noAntenna, bothPorts) => {
      window.__calCalls.push([band, step]);
      window.__calBoxes.push(noAntenna);
      window.__calBoth.push(bothPorts);
      const next = {open: "short", short: "load", load: bothPorts ? "isoln" : null, isoln: "thru", thru: null}[step];
      const answer = window.__calError ? {ok: false, error: window.__calError} : {ok: true, next};
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


TARGET = "Target (MHz, optional)"  # the field's full label


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
    app.get_by_label(TARGET, exact=True).press("Enter")  # nor does Enter in the target field
    app.evaluate("window.__release()")
    expect(sweep).to_be_enabled()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text("")
    assert len(app.evaluate("window.__calls")) == 1


# --- UI review 2026-11-16 ------------------------------------------------------------------------

def test_explanation_lines_are_shown_dimmer_than_the_answers(app: Page):
    # The report marks explanations with a two-space indent; the answers should stand out.
    app.evaluate('window.__answer = Object.assign({}, window.__answer, '
                 '{report: "40m: best match SWR 1.20\\n  SWR says how well it matches\\nAcross the band: 1.3\\n"})')
    app.get_by_role("button", name="Sweep").click()
    report = app.locator("#report")
    expect(report).to_contain_text("40m: best match SWR 1.20")
    explain = report.locator(".explain")
    expect(explain).to_have_count(1)
    expect(explain).to_have_text("  SWR says how well it matches")
    color = "(el) => getComputedStyle(el).color"
    assert explain.evaluate(color) != report.evaluate(color)


def test_an_explanation_line_with_markup_is_still_text(app: Page):
    app.evaluate('window.__answer = {ok: true, report: "  <img src=x onerror=alert(1)>", swr_svg: "", smith_svg: ""}')
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report .explain")).to_have_text("  <img src=x onerror=alert(1)>")
    expect(app.locator("#report img")).to_have_count(0)


def test_the_target_field_says_mhz_and_optional(app: Page):
    expect(app.get_by_label(TARGET, exact=True)).to_have_attribute("placeholder", "e.g. 7.074")


def test_the_live_button_says_it_repeats_before_and_after(app: Page):
    expect(app.locator("#live")).to_have_text("Live (repeat)")
    app.locator("#live").click()
    app.get_by_role("button", name="Stop").click()
    expect(app.locator("#live")).to_have_text("Live (repeat)")


# --- UI review 2026-11-16: the Cable and Calibrate tabs ----------------------------------------

def test_a_cable_smith_chart_stays_chart_sized(app: Page):
    # With no SWR plot beside it, it stretched across two-thirds of the window and its labels doubled.
    cable_tab(app)
    app.get_by_label("Velocity factor").fill("0.66")
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.locator("#smith svg")).to_be_visible()
    assert app.locator("#smith").bounding_box()["width"] <= 450


def test_the_cable_hint_says_up_to_200_mhz(app: Page):
    cable_tab(app)
    expect(app.locator("#cable-hint")).to_contain_text("up to 200 MHz")


def test_the_length_example_fits_its_field(app: Page):
    cable_tab(app)
    field = app.get_by_label("Length", exact=True)
    expect(field).to_have_attribute("placeholder", "e.g. 15.2 or 50ft")  # checked by eye: it fits


def test_the_step_is_bold_and_the_stop_partway_note_is_apart(app: Page):
    start_calibrating(app)
    expect(app.locator("#cal-instruction")).to_contain_text("Step 2 of 3")
    expect(app.locator("#cal-instruction")).not_to_contain_text("stop partway")
    expect(app.locator("#cal-partway")).to_contain_text("To stop partway")


def test_no_stop_partway_note_before_or_after(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    expect(app.locator("#cal-partway")).to_be_hidden()  # at the open step, nothing to stop yet


def test_calibrating_names_the_port_and_says_off_and_on_once(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    expect(app.locator("#calibrate-panel")).to_contain_text("CH0")
    expect(app.locator("#cal-hint")).not_to_contain_text("off and on")


# --- Phase 4: "Check yourself" under the report ---------------------------------------------------
# The questions come from Python with the answer; the page only shows them and says right or not.

QUIZ = ('[{ask: "Should the antenna be longer or shorter?", choices: ["Longer", "Shorter", "Leave it as it is"], '
        'answer: 1, why: "The best match is below your target."}, '
        '{ask: "Could you use 7.300 MHz without a tuner?", choices: ["Yes", "No"], answer: 1, why: "SWR is 4.92 there."}]')


def with_quiz(app: Page, quiz=QUIZ):
    app.evaluate(f"window.__answer = Object.assign({{}}, window.__answer, {{quiz: {quiz}}})")


def test_check_yourself_appears_under_a_sweep(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    quiz = app.get_by_role("region", name="Check yourself")
    expect(quiz).to_be_visible()
    expect(quiz.get_by_role("group")).to_have_count(2)
    expect(quiz.get_by_role("group", name="Should the antenna be longer or shorter?")).to_be_visible()


def test_the_right_choice_says_right_and_why(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    question = app.get_by_role("group", name="Should the antenna be longer or shorter?")
    question.get_by_role("radio", name="Shorter").check()
    expect(question.get_by_role("status")).to_have_text("Right. The best match is below your target.")


def test_a_wrong_choice_gives_the_answer_and_why_and_can_be_changed(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    question = app.get_by_role("group", name="Should the antenna be longer or shorter?")
    question.get_by_role("radio", name="Longer").check()
    expect(question.get_by_role("status")).to_have_text(
        "Not quite: the answer is Shorter. The best match is below your target.")
    question.get_by_role("radio", name="Shorter").check()  # try again
    expect(question.get_by_role("status")).to_contain_text("Right.")


def test_questions_answer_from_the_keyboard(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    question = app.get_by_role("group", name="Could you use 7.300 MHz without a tuner?")
    question.get_by_role("radio", name="Yes").focus()
    app.keyboard.press("Space")
    app.keyboard.press("ArrowDown")  # radio buttons in a group move with the arrow keys
    expect(question.get_by_role("radio", name="No")).to_be_checked()
    expect(question.get_by_role("status")).to_contain_text("Right.")


def test_quiz_text_is_shown_as_text_not_markup(app: Page):
    with_quiz(app, '[{ask: "<img src=x onerror=alert(1)>", choices: ["<b>a</b>", "b"], answer: 0, why: "<i>w</i>"}]')
    app.get_by_role("button", name="Sweep").click()
    app.get_by_role("radio", name="<b>a</b>").check()
    expect(app.locator("#quiz")).to_contain_text("<img src=x onerror=alert(1)>")
    expect(app.locator("#quiz img, #quiz b, #quiz i")).to_have_count(0)


def test_no_questions_no_section(app: Page):
    app.get_by_role("button", name="Sweep").click()  # the fake answer carries no quiz
    expect(app.locator("#report")).not_to_be_empty()
    expect(app.locator("#quiz")).to_be_hidden()


def test_an_error_clears_the_questions(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#quiz")).to_be_visible()
    app.evaluate('window.__answer = {ok: false, error: "No NanoVNA found."}')
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#quiz")).to_be_hidden()


def test_live_shows_questions_only_after_stop(app: Page):
    # Redrawn every pass, they'd reset while you answered.
    with_quiz(app)
    app.get_by_role("button", name="Live").click()
    app.wait_for_function("window.__calls.length >= 2")
    expect(app.locator("#quiz")).to_be_hidden()
    app.get_by_role("button", name="Stop").click()
    expect(app.get_by_role("button", name="Live")).to_be_enabled()
    expect(app.locator("#quiz")).to_be_visible()


def test_a_cable_check_shows_its_questions_too(app: Page):
    app.evaluate('window.__cableAnswer = Object.assign({}, window.__cableAnswer, {quiz: '
                 '[{ask: "A 20 W radio feeds this cable at 28 MHz. How much reaches the far end?", '
                 'choices: ["20.0 W", "15.9 W", "12.6 W"], answer: 1, why: "1.00 dB one way."}]})')
    cable_tab(app)
    app.get_by_label("Velocity factor").fill("0.66")
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.get_by_role("group", name="A 20 W radio feeds this cable at 28 MHz. How much reaches the far end?")).to_be_visible()


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
    for control in (app.get_by_label("Band", exact=True), app.get_by_label(TARGET, exact=True),
                    app.get_by_role("button", name="Sweep")):
        expect(control).to_be_disabled()
    app.get_by_role("button", name="Stop").click()
    app.evaluate("window.__release()")
    for control in (app.get_by_label("Band", exact=True), app.get_by_label(TARGET, exact=True),
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
    check, box = app.get_by_role("button", name="Check cable"), app.locator("#cable-panel").get_by_label("No antenna connected")
    expect(check).to_be_disabled()
    box.check()
    expect(check).to_be_enabled()
    box.uncheck()
    expect(check).to_be_disabled()


def test_a_cable_check_shows_the_report_and_smith_chart_then_clears_the_box(app: Page):
    cable_tab(app)
    app.get_by_label("Velocity factor").fill("0.66")
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.locator("#report")).to_contain_text("Far end: open")
    expect(app.locator("#smith svg.test-cable-smith")).to_be_visible()
    expect(app.locator("#swr svg")).to_have_count(0)  # no SWR plot for a cable
    assert app.evaluate("window.__cableCalls") == [[True, "0.66", "", "50 m"]]
    # Confirm again every time: the antenna might be back on by the next check.
    expect(app.locator("#cable-panel").get_by_label("No antenna connected")).not_to_be_checked()
    expect(app.get_by_role("button", name="Check cable")).to_be_disabled()


def test_a_cable_error_is_shown_and_the_box_clears_too(app: Page):
    app.evaluate('window.__cableAnswer = {ok: false, error: "Give Velocity factor or Length (one of them)"}')
    cable_tab(app)
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.get_by_role("alert")).to_have_text("Give Velocity factor or Length (one of them)")
    expect(app.locator("#cable-panel").get_by_label("No antenna connected")).not_to_be_checked()


def test_nothing_else_can_start_during_a_cable_check(app: Page):
    app.evaluate("window.__hold = true")
    cable_tab(app)
    app.get_by_label("Length", exact=True).fill("50ft")
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Check cable").click()
    expect(app.get_by_role("status", name="Sweep status")).to_have_text(re.compile("Checking the cable"))
    for control in (app.get_by_role("tab", name="Antenna"), app.get_by_role("button", name="Check cable"),
                    app.locator("#cable-panel").get_by_label("No antenna connected"), app.get_by_label("Length", exact=True)):
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
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_role("tab", name="Antenna").click()
    cable_tab(app)
    expect(app.locator("#cable-panel").get_by_label("No antenna connected")).not_to_be_checked()


def test_check_cable_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    cable_tab(page)
    page.locator("#cable-panel").get_by_label("No antenna connected").check()
    expect(page.get_by_role("button", name="Check cable")).to_be_disabled()


# --- the Calibrate tab: open, short, load over one band ----------------------------------------

def calibrate_tab(page):
    page.get_by_role("tab", name="Calibrate").click()
    return page


def test_calibrate_needs_a_band(app: Page):
    calibrate_tab(app)
    band, measure = app.get_by_label("Band to calibrate"), app.get_by_role("button", name="Measure open")
    expect(band.locator("option")).to_have_count(8)  # "Choose a band" + 6 from Python + HF wide
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


def test_one_port_calibration_says_so_to_python(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    for step in ("open", "short", "load"):
        app.get_by_role("button", name=f"Measure {step}").click()
    expect(app.locator("#cal-instruction")).to_contain_text("Calibrated for 40m")
    assert app.evaluate("window.__calBoth") == [False] * 3


# --- both ports: isolation and thru after the load, for the S21 tests ----------------------------

def test_calibrating_both_ports_walks_through_five_steps(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_label("Both ports").check()
    step = app.locator("#cal-instruction")
    expect(step).to_contain_text("Step 1 of 5")
    for name in ("open", "short", "load"):
        app.get_by_role("button", name=f"Measure {name}").click()
    expect(step).to_contain_text("Step 4 of 5")
    expect(step).to_contain_text("CH1")                    # where the second load goes, if you have one
    expect(step).to_contain_text("only one load")          # and what to do if you don't
    app.get_by_role("button", name="Measure isolation").click()
    expect(step).to_contain_text("Step 5 of 5")
    expect(step).to_contain_text("CH0 to CH1")
    app.get_by_role("button", name="Measure thru").click()
    expect(step).to_contain_text("Calibrated both ports for 40m")
    assert app.evaluate("window.__calCalls") == [["40m", s] for s in ("open", "short", "load", "isoln", "thru")]
    assert app.evaluate("window.__calBoth") == [True] * 5


def test_ticking_both_ports_partway_starts_over(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_role("button", name="Measure open").click()
    app.get_by_label("Both ports").check()
    expect(app.locator("#cal-instruction")).to_contain_text("Step 1 of 5")
    expect(app.get_by_role("button", name="Measure open")).to_be_enabled()


def test_both_ports_cant_change_while_a_standard_is_measured(app: Page):
    app.evaluate("window.__hold = true")
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_role("button", name="Measure open").click()
    expect(app.get_by_label("Both ports")).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_label("Both ports")).to_be_enabled()


def test_with_both_ports_the_other_tabs_stay_shut_until_the_thru(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option("40m")
    app.get_by_label("Both ports").check()
    for name in ("open", "short", "load", "isolation"):
        app.get_by_role("button", name=f"Measure {name}").click()
    expect(app.get_by_role("button", name="Measure thru")).to_be_enabled()
    expect(app.get_by_role("tab", name="Antenna")).to_be_disabled()
    expect(app.locator("#cal-partway")).to_contain_text("after the last step")
    app.get_by_role("button", name="Measure thru").click()
    expect(app.get_by_role("tab", name="Antenna")).to_be_enabled()


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
    expect(app.locator("#cal-partway")).to_contain_text("other tabs open again")
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


# --- turning Check yourself off and on (2026-11-16) -------------------------------------------------
# Python remembers the choice; the page asks for it at start and tells Python when it changes.

SHOW_QUIZ = "Show Check yourself questions"


def test_the_box_starts_ticked_when_python_says_on(app: Page):
    expect(app.get_by_label(SHOW_QUIZ)).to_be_checked()
    expect(app.get_by_label(SHOW_QUIZ)).to_be_enabled()


def test_the_box_starts_unticked_when_python_remembers_off(page: Page):
    page.add_init_script(FAKE_API + "window.__settings = {quiz: false};")
    page.goto(PAGE)
    expect(page.get_by_label(SHOW_QUIZ)).to_be_enabled()
    expect(page.get_by_label(SHOW_QUIZ)).not_to_be_checked()


def test_the_box_waits_for_python(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    expect(page.get_by_label(SHOW_QUIZ)).to_be_disabled()


def test_off_means_no_questions_after_a_sweep(page: Page):
    page.add_init_script(FAKE_API + "window.__settings = {quiz: false};")
    page.goto(PAGE)
    expect(page.get_by_label(SHOW_QUIZ)).to_be_enabled()
    with_quiz(page)
    page.get_by_role("button", name="Sweep").click()
    expect(page.locator("#report")).not_to_be_empty()
    expect(page.locator("#quiz")).to_be_hidden()


def test_unticking_hides_the_questions_and_tells_python(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#quiz")).to_be_visible()
    app.get_by_label(SHOW_QUIZ).uncheck()
    expect(app.locator("#quiz")).to_be_hidden()
    assert app.evaluate("window.__saved") == [False]


def test_ticking_again_brings_back_the_same_questions_with_answers_kept(app: Page):
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    question = app.get_by_role("group", name="Should the antenna be longer or shorter?")
    question.get_by_role("radio", name="Shorter").check()
    app.get_by_label(SHOW_QUIZ).uncheck()
    app.get_by_label(SHOW_QUIZ).check()
    expect(question.get_by_role("radio", name="Shorter")).to_be_checked()
    expect(question.get_by_role("status")).to_contain_text("Right.")
    assert app.evaluate("window.__saved") == [False, True]


def test_ticking_with_no_result_shows_nothing(app: Page):
    app.get_by_label(SHOW_QUIZ).uncheck()
    app.get_by_label(SHOW_QUIZ).check()
    expect(app.locator("#quiz")).to_be_hidden()


def test_a_failed_save_is_shown_and_the_choice_still_applies(app: Page):
    app.evaluate('window.__saveAnswer = {ok: false, error: "Couldn\'t save the Check yourself setting (disk full)."}')
    with_quiz(app)
    app.get_by_role("button", name="Sweep").click()
    app.get_by_label(SHOW_QUIZ).uncheck()
    expect(app.get_by_role("alert")).to_contain_text("Couldn't save")
    expect(app.locator("#quiz")).to_be_hidden()


def test_the_box_is_on_the_cable_tab_too_but_not_calibrate(app: Page):
    app.get_by_role("tab", name="Cable").click()
    expect(app.get_by_label(SHOW_QUIZ)).to_be_visible()
    app.get_by_role("tab", name="Calibrate").click()
    expect(app.get_by_label(SHOW_QUIZ)).to_be_hidden()
    app.get_by_role("tab", name="Antenna").click()
    expect(app.get_by_label(SHOW_QUIZ)).to_be_visible()


def test_cable_questions_follow_the_box_too(app: Page):
    app.evaluate(f"window.__cableAnswer = Object.assign({{}}, window.__cableAnswer, {{quiz: {QUIZ}}})")
    app.get_by_label(SHOW_QUIZ).uncheck()
    app.get_by_role("tab", name="Cable").click()
    app.locator("#cable-panel").get_by_label("No antenna connected").check()
    app.get_by_label("Velocity factor").fill("0.66")
    app.get_by_role("button", name="Check cable").click()
    expect(app.locator("#report")).not_to_be_empty()
    expect(app.locator("#quiz")).to_be_hidden()


# --- "Is your NanoVNA one of these?" (2026-11-16) ---------------------------------------------------
# For a NanoVNA whose USB chip Dipstick won't guess at. Python lists the ports and remembers the choice;
# the page offers the choice only when no NanoVNA is found, and never picks one itself (T3).

MISSING = 'window.__nanovna = {connected: false, text: "No NanoVNA found. Is it plugged in and switched on?"};'
CH340 = '{device: "COM7", id: "1A86:7523", label: "COM7: USB-SERIAL CH340 (COM7)"}'
FTDI = '{device: "COM9", id: "0403:6001", label: "COM9: USB Serial Port (COM9)"}'


def open_with(page: Page, setup: str) -> Page:
    """The page with the fake bridge plus `setup`, failing the test on any console error, like `app`."""
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.add_init_script(FAKE_API + setup)
    page.goto(PAGE)
    page.wait_for_function("window.__portCalls >= 1")
    assert errors == []
    return page


def test_no_choice_while_a_nanovna_is_found(page: Page):
    open_with(page, f"window.__ports = {{ports: [{CH340}], remembered: []}};")
    expect(page.locator("#connection")).to_have_class("connected")
    expect(page.get_by_label("Is your NanoVNA one of these?")).to_be_hidden()


def test_no_choice_when_nothing_else_is_plugged_in(page: Page):
    open_with(page, MISSING)
    expect(page.locator("#connection")).to_have_class("missing")
    expect(page.get_by_label("Is your NanoVNA one of these?")).to_be_hidden()


def test_the_choice_lists_the_other_usb_serial_ports_with_their_ids(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}, {FTDI}], remembered: []}};")
    choice = page.get_by_label("Is your NanoVNA one of these?")
    expect(choice).to_be_visible()
    expect(choice.locator("option")).to_have_text(["COM7: USB-SERIAL CH340 (COM7) (USB ID 1A86:7523)",
                                                   "COM9: USB Serial Port (COM9) (USB ID 0403:6001)"])
    expect(page.locator("#port-picker")).to_contain_text("could change the radio's settings")


def test_nothing_is_chosen_until_you_press_yes(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}, {FTDI}], remembered: []}};")
    page.wait_for_function("window.__portCalls >= 3")  # a few checks go by
    assert page.evaluate("window.__used") == []


def test_yes_sends_the_chosen_port_and_checks_again(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}, {FTDI}], remembered: []}};")
    page.get_by_label("Is your NanoVNA one of these?").select_option("COM9")
    page.evaluate('window.__nanovna = {connected: true, text: "NanoVNA connected (COM9)"};'
                  'window.__ports = {ports: [], remembered: ["0403:6001"]};')
    page.get_by_role("button", name="Yes, use this one").click()
    expect(page.locator("#connection")).to_have_text("NanoVNA connected (COM9)")
    assert page.evaluate("window.__used") == ["COM9"]
    expect(page.get_by_label("Is your NanoVNA one of these?")).to_be_hidden()
    expect(page.locator("#port-remembered")).to_contain_text("Remembered USB ID: 0403:6001")


def test_a_refused_choice_is_shown(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}], remembered: []}};"
              'window.__portAnswer = {ok: false, error: "COM7 isn\'t a USB serial port that\'s plugged in now"};')
    page.get_by_role("button", name="Yes, use this one").click()
    expect(page.get_by_role("alert")).to_have_text("COM7 isn't a USB serial port that's plugged in now")


def test_the_open_choice_isnt_reset_by_the_checks_every_2_seconds(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}, {FTDI}], remembered: []}};")
    choice = page.get_by_label("Is your NanoVNA one of these?")
    choice.select_option("COM9")
    calls = page.evaluate("window.__portCalls")
    page.wait_for_function(f"window.__portCalls >= {calls + 2}")  # two more checks, list unchanged
    expect(choice).to_have_value("COM9")


def test_a_new_port_updates_the_list(page: Page):
    open_with(page, MISSING + f"window.__ports = {{ports: [{CH340}], remembered: []}};")
    page.evaluate(f"window.__ports = {{ports: [{CH340}, {FTDI}], remembered: []}};")
    expect(page.get_by_label("Is your NanoVNA one of these?").locator("option")).to_have_count(2)


def test_a_remembered_id_is_shown_and_can_be_forgotten(page: Page):
    open_with(page, 'window.__ports = {ports: [], remembered: ["1A86:7523"]};')
    remembered = page.locator("#port-remembered")
    expect(remembered).to_contain_text("Remembered USB ID: 1A86:7523")
    page.evaluate("window.__ports = {ports: [], remembered: []};")
    page.get_by_role("button", name="Forget").click()
    expect(remembered).to_be_hidden()
    assert page.evaluate("window.__forgot") == 1


def test_a_failed_forget_is_shown(page: Page):
    open_with(page, 'window.__ports = {ports: [], remembered: ["1A86:7523"]};'
              'window.__portAnswer = {ok: false, error: "Couldn\'t save forgetting the port choice (disk full)."};')
    page.get_by_role("button", name="Forget").click()
    expect(page.get_by_role("alert")).to_contain_text("Couldn't save forgetting")


def test_port_names_from_usb_devices_are_shown_as_text_not_markup(page: Page):
    # A USB device names itself, so a hostile gadget could call itself anything.
    evil = '{device: "COM5", id: "1234:5678", label: "COM5: <img src=x onerror=alert(1)>"}'
    open_with(page, MISSING + f'window.__ports = {{ports: [{evil}], remembered: ["<b>1234:5678</b>"]}};')
    expect(page.get_by_label("Is your NanoVNA one of these?").locator("option")).to_have_text(
        "COM5: <img src=x onerror=alert(1)> (USB ID 1234:5678)")
    expect(page.locator("#port-ids")).to_have_text("<b>1234:5678</b>")
    expect(page.locator("header img, header b")).to_have_count(0)


def test_the_page_keeps_working_if_the_port_list_fails(page: Page):
    # A Python error (say, Windows failing to list its ports) reaches the page as a rejected call.
    open_with(page, MISSING + "window.__portsFail = true;")
    page.wait_for_function("window.__portCalls >= 2")
    expect(page.locator("#connection")).to_have_text("No NanoVNA found. Is it plugged in and switched on?")


# --- the Balun tab: the transformer test (a wide sweep, so only with no antenna connected) -------

def balun_tab(app: Page):
    app.get_by_role("tab", name="Balun").click()
    return app.get_by_role("tabpanel", name="Balun")


def test_test_transformer_needs_the_no_antenna_box(app: Page):
    panel = balun_tab(app)
    test, box = app.get_by_role("button", name="Test transformer"), panel.get_by_label("No antenna connected")
    expect(test).to_be_disabled()
    box.check()
    expect(test).to_be_enabled()
    box.uncheck()
    expect(test).to_be_disabled()


def test_a_transformer_test_shows_the_report_and_swr_plot_then_clears_the_box(app: Page):
    panel = balun_tab(app)
    app.get_by_label("Ratio").select_option("49:1")
    app.get_by_label("Resistor").fill("2.4k")
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test transformer").click()
    expect(app.locator("#report")).to_contain_text("SWR 2 or under on every band")
    expect(app.locator("#swr svg.test-balun-swr")).to_be_visible()
    expect(app.locator("#smith")).to_be_empty()  # no Smith chart for a transformer
    assert app.evaluate("window.__balunCalls") == [[True, "49:1", "2.4k"]]
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()
    expect(app.get_by_role("button", name="Test transformer")).to_be_disabled()


def test_the_resistor_hint_follows_the_ratio(app: Page):
    balun_tab(app)
    resistor = app.get_by_label("Resistor")
    for ratio, ohms in (("49:1", "2450"), ("1:1", "50"), ("9:1", "450"), ("4:1", "200")):
        app.get_by_label("Ratio").select_option(ratio)
        expect(resistor).to_have_attribute("placeholder", f"{ohms} (default)")


def test_a_transformer_error_is_shown_and_the_box_clears_too(app: Page):
    app.evaluate('window.__balunAnswer = {ok: false, error: "Resistor must be close to 2450 ohms (1634 to 3675)"}')
    panel = balun_tab(app)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test transformer").click()
    expect(app.get_by_role("alert")).to_have_text("Resistor must be close to 2450 ohms (1634 to 3675)")
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()


def test_nothing_else_can_start_during_a_transformer_test(app: Page):
    app.evaluate("window.__hold = true")
    panel = balun_tab(app)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test transformer").click()
    expect(app.get_by_role("button", name="Test transformer")).to_be_disabled()
    for name in ("Antenna", "Cable", "Calibrate"):
        expect(app.get_by_role("tab", name=name)).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_role("tab", name="Antenna")).to_be_enabled()


def test_the_balun_hint_says_the_range_and_never_to_connect_a_radio(app: Page):
    balun_tab(app)
    hint = app.locator("#balun-hint")
    expect(hint).to_contain_text("1.8 to 54 MHz")
    expect(hint).to_contain_text("Never connect a radio")
    expect(hint).to_contain_text("2450 ohms")


def test_no_check_yourself_box_on_the_balun_tab(app: Page):
    balun_tab(app)
    expect(app.get_by_label(SHOW_QUIZ)).to_be_hidden()


# --- the Balun tab: the choke test (a current balun between CH0 and CH1) -----------------------------

def choke_mode(app: Page):
    panel = balun_tab(app)
    app.get_by_label("What to test").select_option("Choke")
    return panel


def test_choosing_choke_swaps_the_fields_button_and_hint(app: Page):
    choke_mode(app)
    expect(app.get_by_label("Ratio")).to_be_hidden()   # auto-waits, like Wait Until Element Is Not Visible
    expect(app.get_by_label("Resistor")).to_be_hidden()
    expect(app.get_by_role("button", name="Test choke")).to_be_visible()
    expect(app.locator("#balun-hint")).to_be_hidden()
    hint = app.locator("#choke-hint")
    for words in ("CH0", "CH1", "Both ports", "1.8 to 54 MHz", "Never connect a radio"):
        expect(hint).to_contain_text(words)
    app.get_by_label("What to test").select_option("Transformer")
    expect(app.get_by_label("Ratio")).to_be_visible()
    expect(app.get_by_role("button", name="Test transformer")).to_be_visible()
    expect(app.locator("#choke-hint")).to_be_hidden()


def test_a_choke_test_shows_the_report_with_no_plots_then_clears_the_box(app: Page):
    panel = choke_mode(app)
    test = app.get_by_role("button", name="Test choke")
    expect(test).to_be_disabled()  # the same box gates both tests
    panel.get_by_label("No antenna connected").check()
    test.click()
    expect(app.locator("#report")).to_contain_text("Choke: good on 160m")
    expect(app.locator("#swr")).to_be_empty()
    expect(app.locator("#smith")).to_be_empty()
    assert app.evaluate("window.__chokeCalls") == [True]
    assert app.evaluate("window.__balunCalls") == []
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()
    expect(test).to_be_disabled()


def test_a_choke_error_is_shown_and_the_box_clears_too(app: Page):
    app.evaluate('window.__chokeAnswer = {ok: false, error: "Almost nothing arrives at CH1"}')
    panel = choke_mode(app)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test choke").click()
    expect(app.get_by_role("alert")).to_have_text("Almost nothing arrives at CH1")
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()


def test_the_page_sends_the_boxs_real_state_so_python_decides(app: Page):
    # The disabled button is a convenience; Python's check is the safety gate (T5), so the page must
    # pass on an unticked box as false. requestSubmit() submits even with the button disabled.
    box = choke_mode(app).get_by_label("No antenna connected")
    box.check()
    expect(app.get_by_role("button", name="Test choke")).to_be_enabled()  # Python is ready: no race
    box.uncheck()
    app.evaluate('document.getElementById("balun-controls").requestSubmit()')
    expect(app.locator("#report")).to_contain_text("Choke")
    assert app.evaluate("window.__chokeCalls") == [False]


def test_nothing_else_can_start_or_change_during_a_choke_test(app: Page):
    app.evaluate("window.__hold = true")
    panel = choke_mode(app)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test choke").click()
    expect(app.get_by_label("What to test")).to_be_disabled()
    for name in ("Antenna", "Cable", "Calibrate"):
        expect(app.get_by_role("tab", name=name)).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_label("What to test")).to_be_enabled()
    expect(app.get_by_role("button", name="Test choke")).to_be_visible()


def test_test_transformer_waits_until_python_is_reachable(page: Page):
    page.add_init_script(FAKE_API.replace("}, 50);", "}, 10_000);"))
    page.goto(PAGE)
    page.get_by_role("tab", name="Balun").click()
    page.get_by_role("tabpanel", name="Balun").get_by_label("No antenna connected").check()
    expect(page.get_by_role("button", name="Test transformer")).to_be_disabled()


# --- calibrating HF wide: the transformer test's range, so only with no antenna connected ------------

HF_WIDE = "HF wide, 1.8 to 54 MHz (Balun tab)"


def test_hf_wide_asks_for_the_no_antenna_box(app: Page):
    calibrate_tab(app)
    panel = app.get_by_role("tabpanel", name="Calibrate")
    box, measure = panel.get_by_label("No antenna connected"), app.get_by_role("button", name="Measure open")
    expect(box).to_be_hidden()
    app.get_by_label("Band to calibrate").select_option(label=HF_WIDE)
    expect(box).to_be_visible()
    expect(measure).to_be_disabled()
    box.check()
    expect(measure).to_be_enabled()
    app.get_by_label("Band to calibrate").select_option("40m")
    expect(box).to_be_hidden()
    expect(measure).to_be_enabled()  # a band needs no box


def test_calibrating_hf_wide_sends_the_box_and_says_what_comes_after(app: Page):
    calibrate_tab(app)
    panel = app.get_by_role("tabpanel", name="Calibrate")
    app.get_by_label("Band to calibrate").select_option(label=HF_WIDE)
    panel.get_by_label("No antenna connected").check()
    for step in ("open", "short", "load"):
        app.get_by_role("button", name=f"Measure {step}").click()
    step = app.locator("#cal-instruction")
    expect(step).to_contain_text("Calibrated for 1.8 to 54 MHz")
    expect(step).to_contain_text("keeps sweeping")
    expect(step).to_contain_text("Balun tab")
    assert app.evaluate("window.__calCalls") == [["wide", "open"], ["wide", "short"], ["wide", "load"]]
    assert app.evaluate("window.__calBoxes") == [True, True, True]
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()  # confirmed afresh next time


def test_a_band_sweep_after_hf_wide_says_it_isnt_calibrated_for_the_band(app: Page):
    calibrate_tab(app)
    app.get_by_label("Band to calibrate").select_option(label=HF_WIDE)
    app.get_by_role("tabpanel", name="Calibrate").get_by_label("No antenna connected").check()
    for step in ("open", "short", "load"):
        app.get_by_role("button", name=f"Measure {step}").click()
    expect(app.locator("#cal-instruction")).to_contain_text("Calibrated for")
    app.get_by_role("tab", name="Antenna").click()
    app.get_by_label("Band", exact=True).select_option("40m")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).to_contain_text("calibrated for 1.8 to 54 MHz (HF wide)")


@pytest.mark.parametrize("tab, form, calls", [("Cable", "cable-controls", "__cableCalls"),
                                              ("Balun", "balun-controls", "__balunCalls")])
def test_the_older_tabs_send_the_boxs_real_state_too(app: Page, tab, form, calls):
    # Same as the choke test above: an unticked box must reach Python as false, button or no button.
    app.get_by_role("tab", name=tab).click()
    panel = app.get_by_role("tabpanel", name=tab)
    box = panel.get_by_label("No antenna connected")
    box.check()
    expect(panel.get_by_role("button")).to_be_enabled()  # Python is ready, so nothing is racing it
    box.uncheck()
    app.evaluate(f'document.getElementById("{form}").requestSubmit()')
    expect(app.locator("#report")).not_to_be_empty()
    assert app.evaluate(f"window.{calls}")[0][0] is False


# --- the through-loss test on the Balun tab ------------------------------------------------------


def loss_mode(app: Page):
    panel = balun_tab(app)
    app.get_by_label("What to test").select_option("Through loss")
    return panel


def test_choosing_through_loss_shows_connected_its_button_and_hint(app: Page):
    loss_mode(app)
    expect(app.get_by_label("Ratio")).to_be_hidden()
    expect(app.get_by_label("Connected", exact=True)).to_be_visible()
    expect(app.get_by_role("button", name="Test through loss")).to_be_visible()
    expect(app.locator("#balun-hint")).to_be_hidden()
    expect(app.locator("#choke-hint")).to_be_hidden()
    hint = app.locator("#loss-hint")
    for words in ("CH0", "CH1", "Both ports", "back to back", "1:1", "1.8 to 54 MHz", "Never connect a radio"):
        expect(hint).to_contain_text(words)
    app.get_by_label("What to test").select_option("Choke")
    expect(app.get_by_label("Connected", exact=True)).to_be_hidden()
    expect(app.locator("#loss-hint")).to_be_hidden()
    expect(app.locator("#choke-hint")).to_be_visible()


@pytest.mark.parametrize("label, sent", [("One item, direct", "direct"),
                                         ("Two transformers back to back", "back-to-back")])
def test_a_through_loss_test_sends_the_connection_and_shows_the_report(app: Page, label, sent):
    panel = loss_mode(app)
    app.get_by_label("Connected", exact=True).select_option(label=label)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test through loss").click()
    expect(app.locator("#report")).to_contain_text("Through loss, direct")
    expect(app.locator("#swr")).to_be_empty()
    expect(app.locator("#smith")).to_be_empty()
    assert app.evaluate("window.__lossCalls") == [[True, sent]]
    assert app.evaluate("window.__chokeCalls") == [] and app.evaluate("window.__balunCalls") == []
    expect(panel.get_by_label("No antenna connected")).not_to_be_checked()


def test_the_through_loss_test_sends_the_boxs_real_state(app: Page):
    box = loss_mode(app).get_by_label("No antenna connected")
    box.check()
    expect(app.get_by_role("button", name="Test through loss")).to_be_enabled()  # Python is ready: no race
    box.uncheck()
    app.evaluate('document.getElementById("balun-controls").requestSubmit()')
    expect(app.locator("#report")).not_to_be_empty()
    assert app.evaluate("window.__lossCalls") == [[False, "direct"]]


def test_connected_is_locked_while_a_through_loss_test_runs(app: Page):
    app.evaluate("window.__hold = true")
    panel = loss_mode(app)
    panel.get_by_label("No antenna connected").check()
    app.get_by_role("button", name="Test through loss").click()
    expect(app.get_by_label("Connected", exact=True)).to_be_disabled()
    expect(app.get_by_label("What to test")).to_be_disabled()
    app.evaluate("window.__release()")
    expect(app.get_by_label("Connected", exact=True)).to_be_enabled()


def test_hf_wide_sends_the_boxs_real_state_too(app: Page):
    # As on the other tabs: an unticked box reaches Python as false even past the disabled button.
    calibrate_tab(app)
    box = app.get_by_role("tabpanel", name="Calibrate").get_by_label("No antenna connected")
    app.get_by_label("Band to calibrate").select_option(label=HF_WIDE)
    box.check()
    expect(app.get_by_role("button", name="Measure open")).to_be_enabled()  # Python is ready: no race
    box.uncheck()
    app.evaluate('document.getElementById("cal-controls").requestSubmit()')
    app.wait_for_function("window.__calBoxes.length > 0")  # like Wait Until Keyword Succeeds on a JS check
    assert app.evaluate("window.__calBoxes") == [False]


# --- More detail: the band report's background, folded away (display review 2026-11-19) -------------
# Python sends the Tune section as `report` and the rest as `detail`; the page folds the detail into
# a closed <details>, and Python remembers whether you left it open.

MORE = "More detail"


def test_more_detail_is_there_but_closed_after_a_sweep(app: Page):
    expect(app.locator("#detail")).to_be_hidden()  # nothing to show before a sweep
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#detail")).to_be_visible()
    expect(app.get_by_text(MORE)).to_be_visible()
    expect(app.locator("#detail-text")).to_be_hidden()


def test_opening_more_detail_shows_it_and_tells_python(app: Page):
    app.get_by_role("button", name="Sweep").click()
    app.get_by_text(MORE).click()
    expect(app.locator("#detail-text")).to_contain_text("What the NanoVNA measured: 101 frequencies")
    expect(app.locator("#detail-text .explain")).to_have_text("  At each one it sent a tiny test signal\n")  # dimmer
    app.get_by_text(MORE).click()
    expect(app.locator("#detail-text")).to_be_hidden()
    app.wait_for_function("window.__detailSaved.length === 2")
    assert app.evaluate("window.__detailSaved") == [True, False]


def test_more_detail_opens_by_itself_when_python_remembers_open(page: Page):
    page.add_init_script(FAKE_API + "window.__settings = {quiz: true, detail: true};")
    page.goto(PAGE)
    page.get_by_role("button", name="Sweep").click()
    expect(page.locator("#detail-text")).to_contain_text("What the NanoVNA measured")
    assert page.evaluate("window.__detailSaved") == []  # opening it from the setting isn't a change to save


def test_open_more_detail_stays_open_for_the_next_sweep(app: Page):
    app.get_by_role("button", name="Sweep").click()
    app.get_by_text(MORE).click()
    app.evaluate("window.__answer = Object.assign({}, window.__answer, {detail: 'Across the band: second sweep\\n'})")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#detail-text")).to_have_text("Across the band: second sweep\n")


def test_more_detail_is_text_not_markup(app: Page):
    app.evaluate("window.__answer = Object.assign({}, window.__answer, {detail: '<img src=x onerror=alert(1)>\\n'})")
    app.get_by_role("button", name="Sweep").click()
    app.get_by_text(MORE).click()
    expect(app.locator("#detail-text")).to_have_text("<img src=x onerror=alert(1)>\n")
    expect(app.locator("#detail-text img")).to_have_count(0)


def test_an_error_or_another_test_hides_more_detail(app: Page):
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#detail")).to_be_visible()
    app.evaluate('window.__answer = {ok: false, error: "No NanoVNA found. Is it plugged in?"}')
    app.get_by_role("button", name="Sweep").click()
    expect(app.get_by_role("alert")).to_be_visible()
    expect(app.locator("#detail")).to_be_hidden()


def test_a_failed_save_of_more_detail_says_so(app: Page):
    app.evaluate('window.__saveAnswer = {ok: false, error: "Couldn\'t save whether More detail is open (disk full)"}')
    app.get_by_role("button", name="Sweep").click()
    app.get_by_text(MORE).click()
    expect(app.get_by_role("alert")).to_contain_text("Couldn't save whether More detail is open")


# --- the antenna's length, for the trim in inches (2026-11-19) ---------------------------------------

LENGTH = "Antenna length (optional)"


def test_the_antenna_length_typed_is_sent_with_the_sweep(app: Page):
    app.get_by_label(LENGTH).fill("66 ft")
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).not_to_be_empty()
    assert app.evaluate("window.__lengths") == ["66 ft"]


def test_an_empty_antenna_length_is_sent_empty(app: Page):
    app.get_by_role("button", name="Sweep").click()
    expect(app.locator("#report")).not_to_be_empty()
    assert app.evaluate("window.__lengths") == [""]


def test_the_antenna_length_is_locked_while_live_runs(app: Page):
    app.get_by_label(LENGTH).fill("20 m")
    app.get_by_role("button", name="Live").click()
    expect(app.get_by_label(LENGTH)).to_be_disabled()
    app.wait_for_function("window.__calls.length >= 2")
    app.get_by_role("button", name="Stop").click()
    expect(app.get_by_label(LENGTH)).to_be_enabled()
    assert set(app.evaluate("window.__lengths")) == {"20 m"}
