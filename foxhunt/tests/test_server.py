"""The local web server (README: acceptance criteria; threat model T1, T2, T4). Uses the
simulator and FastAPI's test client: no dongle, no network."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from foxhunt.meter import Meter, Settings
from foxhunt.server import create_app
from foxhunt.sources import SimSource, SourceError

PORT = 8075
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
WS = f"ws://127.0.0.1:{PORT}/ws"  # the test client ignores base_url for WebSockets
FOX = Settings(146_565_000, 20.0, 0.0)


def make_client(tmp_path, source=None, retry_s=2.0):
    app = create_app(source or SimSource(seed=1, realtime=True), Meter(FOX, tmp_path), PORT, retry_s=retry_s)
    return TestClient(app, base_url=BASE)


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def next_reading(ws):
    while "reading" not in (message := ws.receive_json()):
        pass
    return message["reading"]


def test_the_page_is_served_with_a_strict_csp(client):
    response = client.get("/")
    assert response.status_code == 200 and "dB over noise" in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"


def test_readings_stream_over_the_websocket(client):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        first, second = next_reading(ws), next_reading(ws)
    assert first["freq_hz"] == FOX.freq_hz and "over_noise_db" in first and second["time"] >= first["time"]


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {}])
def test_a_websocket_from_any_other_origin_is_refused(client, headers):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS, headers=headers) as ws:
        ws.receive_json()


@pytest.mark.parametrize("host", ["evil.example", "192.0.2.1:8075", "127.0.0.1:9999"])
def test_another_host_name_is_refused(client, host):
    # DNS rebinding: a hostile name pointed at 127.0.0.1 still sends its own Host header.
    assert client.get("/", headers={"Host": host}).status_code == 400


def test_settings_change_what_is_measured(client):
    response = client.post("/settings", headers=ORIGIN, json={"freq_mhz": "147.000", "gain_db": 20, "attenuator_db": 10})
    assert response.status_code == 200 and response.json()["settings"]["attenuator_db"] == 10.0
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        for _ in range(20):  # the loop applies new settings before its next reading
            reading = next_reading(ws)
            if reading["freq_hz"] == 147_000_000:
                break
    assert reading["freq_hz"] == 147_000_000 and reading["attenuator_db"] == 10.0


@pytest.mark.parametrize("body, reason", [
    ({"freq_mhz": 2000, "gain_db": 20, "attenuator_db": 0}, "Frequency"),
    ({"freq_mhz": 146.565, "gain_db": 80, "attenuator_db": 0}, "Gain"),
    ({"freq_mhz": 146.565, "gain_db": 20, "attenuator_db": "lots"}, "Attenuator"),
    ({"freq_mhz": 146.565}, "Gain"),
])
def test_bad_settings_are_refused_and_change_nothing(client, body, reason):
    response = client.post("/settings", headers=ORIGIN, json=body)
    assert response.status_code == 400 and reason in response.json()["error"]
    assert client.get("/state").json()["settings"]["freq_mhz"] == 146.565


@pytest.mark.parametrize("path, body", [("/settings", {"freq_mhz": 147, "gain_db": 20, "attenuator_db": 0}),
                                        ("/record", {"on": True}), ("/peak/reset", {}),
                                        ("/bearing", {"heading": 90}), ("/spot", {"lat": 40, "lon": -100})])
@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {}])
def test_posts_from_any_other_origin_are_refused(client, tmp_path, path, body, headers):
    assert client.post(path, headers=headers, json=body).status_code == 403
    assert not (tmp_path / "sessions").exists()


def test_a_bearing_is_marked_and_listed(client):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        next_reading(ws)
    response = client.post("/bearing", headers=ORIGIN, json={"heading": "275"})
    assert response.status_code == 200 and response.json()["bearing"]["heading"] == 275.0
    (spot,) = client.get("/state").json()["spots"]
    assert [b["heading"] for b in spot["marks"]] == [275.0] and spot["bearing"]["heading"] == 275.0


@pytest.mark.parametrize("body", [{"heading": 400}, {"heading": "north"}, {}])
def test_a_bad_heading_is_refused_and_nothing_is_saved(client, body):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        next_reading(ws)
    response = client.post("/bearing", headers=ORIGIN, json=body)
    assert response.status_code == 400 and "Heading" in response.json()["error"]
    assert client.get("/state").json()["spots"] == []


def test_readings_come_with_the_schedule_and_advice(client):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        while "reading" not in (message := ws.receive_json()):
            pass
    assert "text" in message["schedule"] and "advice" in message


def test_spots_and_the_map(client):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        next_reading(ws)
    for lat, lon, heading in [(40.0, -100.0, 45), (40.0, -99.98, 315)]:
        assert client.post("/spot", headers=ORIGIN, json={"lat": lat, "lon": lon}).status_code == 200
        client.post("/bearing", headers=ORIGIN, json={"heading": heading})
    result = client.get("/map").json()
    assert result["estimate"]["lat"] > 40.0 and len(result["spots"]) == 2  # the two bearings cross to the north


@pytest.mark.parametrize("body, reason", [({"lat": 40}, "both"), ({"lat": 91, "lon": 0}, "Latitude"), ([1], "JSON object")])
def test_a_bad_position_is_refused(client, body, reason):
    response = client.post("/spot", headers=ORIGIN, json=body)
    assert response.status_code == 400 and reason in response.json()["error"]
    assert client.get("/state").json()["spots"] == []


def test_the_map_without_enough_spots_says_what_it_needs(client):
    assert client.get("/map").json()["estimate"] is None


def test_no_bearing_while_the_fox_is_between_transmissions(tmp_path):
    # Bursts of 1 s every 3 s: wait until the learner has heard one and it has gone quiet.
    with make_client(tmp_path, source=SimSource(seed=1, realtime=True, burst=(1.0, 2.0))) as client:
        with client.websocket_connect(WS, headers=ORIGIN) as ws:
            while True:
                message = ws.receive_json()
                if "schedule" in message and message["schedule"]["text"].startswith("Fox off"):
                    break
        response = client.post("/bearing", headers=ORIGIN, json={"heading": 90})
    assert response.status_code == 400 and "off the air" in response.json()["error"]


def test_recording_starts_and_stops(client, tmp_path):
    started = client.post("/record", headers=ORIGIN, json={"on": True}).json()
    assert started["recording"].endswith(".jsonl") and "/" not in started["recording"]  # the name only
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        next_reading(ws)
    assert client.post("/record", headers=ORIGIN, json={"on": False}).json()["recording"] is None
    (session,) = (tmp_path / "sessions").iterdir()
    assert session.read_text().count("\n") >= 1


def test_a_source_error_is_shown_and_retried(tmp_path):
    class Flaky(SimSource):
        opens = 0

        def open(self, settings):
            Flaky.opens += 1
            if Flaky.opens == 1:
                raise SourceError("No RTL-SDR found: is it plugged in?")
            return super().open(settings)

    with make_client(tmp_path, Flaky(seed=1, realtime=True), retry_s=0.5) as c, \
            c.websocket_connect(WS, headers=ORIGIN) as ws:
        first = ws.receive_json()  # sent on connect: someone opening the page later still sees why
        recovered = ws.receive_json()
    assert first == {"error": "No RTL-SDR found: is it plugged in?"}
    assert "reading" in recovered and Flaky.opens == 2  # retried on its own


def test_an_unexpected_error_doesnt_stop_the_server(tmp_path):
    class Broken(SimSource):
        def read(self, n, t=None):
            raise RuntimeError("boom")

    with make_client(tmp_path, Broken(seed=1), retry_s=0.05) as c, c.websocket_connect(WS, headers=ORIGIN) as ws:
        message = ws.receive_json()
        assert "Unexpected error" in message["error"] and "boom" not in message["error"]
        assert c.get("/").status_code == 200
