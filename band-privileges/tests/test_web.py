"""Web page via Flask's test client: status, content, headers (no browser)."""

import pytest

from band_privileges.web import create_app


@pytest.fixture
def client():
    return create_app().test_client()


def test_home_page_shows_the_form(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="freq"' in html
    assert 'name="mode"' in html
    assert 'name="class"' in html


def _page(client, **query):
    response = client.get("/", query_string=query)
    return response.status_code, response.get_data(as_text=True)


def test_allowed_answer_shows_status_reason_and_citations(client):
    status, html = _page(client, freq="14.074", mode="data", **{"class": "general"})
    assert status == 200
    assert "ALLOWED" in html
    assert "data is allowed here" in html
    assert "§97.301(d)" in html and "§97.305(c)(3)(ix)" in html


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"freq": "14.200", "mode": "phone", "class": "general"}, "DENIED"),
        ({"freq": "146.52", "mode": "phone", "class": "general"}, "NOT COVERED"),
    ],
)
def test_denied_and_not_covered_answers(client, query, expected):
    status, html = _page(client, **query)
    assert status == 200
    assert expected in html


def test_note_and_warning_are_shown(client):
    _, html = _page(client, freq="28.300", mode="phone", **{"class": "technician"})
    assert "SSB only (J3E/R3E), §97.307(f)(10)" in html
    assert "within 3 kHz of 28.300 MHz" in html


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"freq": "abc", "mode": "data", "class": "general"}, "frequency must be a number"),
        ({"freq": "14074", "mode": "data", "class": "general"}, "did you mean 14.074 MHz?"),
        ({"freq": "1e10000000", "mode": "cw", "class": "extra"}, "frequency must be a number"),
        ({"freq": "14.074", "mode": "ssb", "class": "general"}, "mode must be one of: cw, phone"),
        ({"freq": "14.074", "mode": "data", "class": "advanced"}, "class must be one of:"),
        ({"freq": "14.074"}, "mode must be one of:"),  # hand-edited URL, fields missing
    ],
)
def test_bad_input_is_400_with_the_message_and_no_answer(client, query, message):
    status, html = _page(client, **query)
    assert status == 400
    assert message in html
    for label in ("ALLOWED", "DENIED", "NOT COVERED"):
        assert label not in html  # never an answer alongside an error


def test_typed_frequency_is_kept_in_the_box_after_an_error(client):
    _, html = _page(client, freq="14074", mode="data", **{"class": "general"})
    assert 'value="14074"' in html


def test_script_in_input_comes_back_escaped_not_as_a_tag(client):
    # T2, A05:2025 Injection (XSS): echoed input must never become markup.
    attack = '"><script>alert(1)</script>'
    _, html = _page(client, freq=attack, mode="data", **{"class": "general"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8073", "192.0.2.10"])
def test_foreign_host_header_is_rejected(client, host):
    # T1, A01:2025: DNS rebinding makes a hostile site's requests arrive at
    # 127.0.0.1 with the attacker's hostname in the Host header.
    assert client.get("/", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8073", "localhost:8073", "127.0.0.1"])
def test_local_host_header_is_accepted(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 200


def test_security_headers_are_set(client):
    # T2/T3, A05/A02:2025: no scripts at all, no framing, no MIME sniffing.
    headers = client.get("/").headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_internal_error_is_a_generic_500_without_a_traceback(client, monkeypatch):
    # T4, A10:2025: an unexpected failure must not leak internals.
    def broken(*args):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("band_privileges.web.check", broken)
    status, html = _page(client, freq="14.074", mode="data", **{"class": "general"})
    assert status == 500
    assert "secret internal detail" not in html
    assert "Traceback" not in html


def test_main_serves_on_loopback_only_with_debug_off(monkeypatch):
    # Binding to 0.0.0.0 would expose the page to the whole network, and
    # debug mode exposes an interactive console. Capture run() instead of
    # starting a server.
    from flask import Flask

    from band_privileges import web

    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: calls.append(kwargs))
    web.main()
    assert calls == [{"host": "127.0.0.1", "port": 8073, "debug": False}]


@pytest.mark.parametrize(
    "query",
    [{}, {"freq": "14.074", "mode": "data", "class": "general"}, {"freq": "abc"}],
    ids=["empty form", "answer", "error"],
)
def test_disclaimer_is_on_every_page(client, query):
    _, html = _page(client, **query)
    assert "Disclaimer:" in html
    assert "solely responsible for every transmission" in html
    assert "no warranty" in html
