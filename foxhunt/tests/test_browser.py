"""The page in headless Chromium against the real server and the simulator (README: acceptance
criteria; T2). Only things a browser can show: live updates, banners, layout, the CSP."""
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import expect

from foxhunt.meter import Meter, Settings
from foxhunt.server import create_app
from foxhunt.sources import SimSource


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = free_port()
    app = create_app(SimSource(seed=1, realtime=True), Meter(Settings(146_565_000, 20.0, 0.0), tmp_path), port)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        assert time.monotonic() < deadline, "server didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)


def test_readings_update_live(page, server):
    page.goto(server)
    expect(page.locator("#over-noise")).not_to_have_text("--")
    first = page.locator("#over-noise").text_content()
    expect(page.locator("#over-noise")).not_to_have_text(first, timeout=5000)  # it keeps changing
    expect(page.locator("#tuned")).to_contain_text("146.5650 MHz")
    assert page.locator("#bar-fill").evaluate("el => parseFloat(el.style.width)") > 0
    expect(page.locator("#error")).to_be_hidden()


def test_too_much_gain_shows_the_overload_banner(page, server):
    page.goto(server)
    page.get_by_label("Gain (dB)").fill("50")
    page.get_by_role("button", name="Apply").click()
    expect(page.locator("#overload")).to_be_visible()
    expect(page.locator("#advice")).to_contain_text("add 10 dB of attenuation")
    page.get_by_label("Gain (dB)").fill("20")
    page.get_by_role("button", name="Apply").click()
    expect(page.locator("#overload")).to_be_hidden()


def test_a_bad_frequency_is_refused_with_the_reason(page, server):
    page.goto(server)
    expect(page.locator("#freq")).to_have_value("146.565")
    page.get_by_label("Frequency (MHz)").fill("2000")
    page.get_by_role("button", name="Apply").click()
    expect(page.locator("#settings-message")).to_contain_text("Frequency must be 0.5-1766 MHz")
    expect(page.locator("#tuned")).to_contain_text("146.5650 MHz")


def test_tone_and_record_buttons_show_their_state(page, server):
    page.goto(server)
    page.get_by_role("button", name="Tone off").click()
    expect(page.locator("#tone")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Record").click()
    expect(page.locator("#recording")).to_contain_text("Recording to data/sessions/")
    page.get_by_role("button", name="Stop recording").click()
    expect(page.locator("#recording")).to_have_text("")


def test_a_bearing_is_marked_and_shown(page, server):
    page.goto(server)
    expect(page.locator("#over-noise")).not_to_have_text("--")
    page.get_by_label("Heading").fill("275")
    page.get_by_role("button", name="Mark bearing").click()
    expect(page.locator("#bearings > li")).to_have_count(1)  # spot 1, made for it
    expect(page.locator("#bearings > li")).to_contain_text("Spot 1 (no position): bearing 275° ±15° (strongest mark; ± assumed)")
    page.get_by_label("Heading").fill("400")
    page.get_by_role("button", name="Mark bearing").click()
    expect(page.locator("#bearing-message")).to_contain_text("Heading must be 0-360")
    expect(page.locator("#bearings ul li")).to_have_count(1)


def test_two_spots_put_the_fox_on_the_map(page, server):
    page.goto(server)
    expect(page.locator("#over-noise")).not_to_have_text("--")
    expect(page.locator("#map-text")).to_contain_text("Needs bearings from 2 or more spots")
    for lat, lon, heading in [("40.0", "-100.0", "45"), ("40.0", "-99.98", "315")]:  # made-up coordinates
        page.get_by_label("Latitude").fill(lat)
        page.get_by_label("Longitude").fill(lon)
        page.get_by_role("button", name="New spot").click()
        page.get_by_label("Heading").fill(heading)
        page.get_by_role("button", name="Mark bearing").click()
    expect(page.locator("#bearings > li")).to_have_count(2)
    expect(page.locator("#map-text")).to_contain_text("Most likely spot 40.0")
    page.get_by_label("Latitude").fill("95")
    page.get_by_label("Longitude").fill("0")
    page.get_by_role("button", name="New spot").click()
    expect(page.locator("#spot-message")).to_contain_text("Latitude must be -90 to 90")


def test_the_schedule_line_shows(page, server):
    page.goto(server)
    expect(page.locator("#schedule")).not_to_be_empty()


def test_the_csp_blocks_an_injected_script(page, server):
    page.goto(server)
    with pytest.raises(Exception):
        page.add_script_tag(content="window.injected = true")
    assert page.evaluate("window.injected") is None


def test_the_page_fits_a_phone(page, server):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(server)
    expect(page.locator("#over-noise")).not_to_have_text("--")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_dark_mode_follows_the_system(page, server):
    page.emulate_media(color_scheme="dark")
    page.goto(server)
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(20, 20, 20)"
