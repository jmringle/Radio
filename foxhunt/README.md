# foxhunt

Tools for radio fox hunting (finding a hidden transmitter). Phase 1 is a **live signal meter** for hunting with a yagi and an attenuator: an RTL-SDR measures how strong the fox is, and a page in your browser shows it as a number, a bar, a 60-second graph and a tone that rises as you get closer.

Receive only. Nothing here transmits, and it measures signal strength only: it doesn't demodulate or play anyone's audio.

## Setup (macOS)

1. Python 3.12 or newer, and the RTL-SDR driver: `brew install librtlsdr`. Homebrew's librtlsdr 2.0.3 recognizes the RTL-SDR Blog V4 (checked in its source, 2026-11-08). `rtl_test` should then find the dongle.
2. From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pip==26.2.2  # Python 3.12's bundled pip 24.0 has known vulnerabilities
pip install -r requirements-dev.txt -r requirements-rtl.txt
playwright install chromium      # only for the browser tests
```

`requirements-rtl.txt` (pyrtlsdr) is only needed for a real dongle; without it, the simulator still works.

## Using it

```sh
foxhunt --freq 146.565                 # simulator: a made-up fox that drifts stronger and weaker
foxhunt --freq 146.565 --source rtl    # the RTL-SDR
```

Open http://127.0.0.1:8075. Options: `--gain DB` (fixed tuner gain, default 20), `--att DB` (what your attenuator is set to, default 0), `--port N`. Gain and attenuator can also be changed on the page.

- **dB over noise** (the big number): how far the fox is above the noise right now. This is the hot/cold reading.
- **Level**: the signal's strength with the gain and attenuator taken back out, so it stays comparable when you change them. It's relative dB, not a calibrated dBm.
- **Peak**: the highest level since you last pressed Reset (or changed frequency).
- **Overload**: the dongle's input is clipping. Readings are wrong until you add attenuation or lower the gain.
- **Record** saves every reading to `data/sessions/<UTC time>.jsonl`, one JSON object per line.

## Running tests

```sh
pytest
```

Runs everything: signal math, meter rules, the web server, and the page in headless Chromium. No dongle or network needed. CI runs the same on every push that touches this folder.

## Design notes

**Language and framework** (decided 2026-11-08). Python: the RTL-SDR and signal-processing libraries (pyrtlsdr, numpy) are mature there, and it runs on the laptop now and a Raspberry Pi node later. FastAPI for the local server, because the meter pushes about 10 readings a second over a WebSocket, and the later node server needs many uploads at once, which FastAPI's async model handles; Flask (used by ft8-forecast) would need add-ons for both. The page is plain HTML/CSS/JavaScript with no build step, so it can become the phone app (a PWA) later; TypeScript gets reconsidered then, when the UI grows. Versions follow the 2-week rule (a release must be 2+ weeks old) and are pinned in `requirements-*.txt`.

**How a reading is made.** The dongle is tuned 200 kHz below the fox, so the fox isn't sitting on the dongle's DC spike (a false signal at the exact tuned frequency). Each reading takes 0.1 s of samples (1.024 million samples/s) and averages FFTs over them. Signal = the power in a 12.5 kHz channel around the fox. Noise = the median power per FFT bin, from 20 to 100 kHz either side of the fox, scaled to the same 12.5 kHz; the median ignores other signals in that range. Gain is fixed (no automatic gain control), since AGC would change the reading as you move and make readings incomparable.

**Acceptance criteria (phase 1).**
- Frequency: 0.5–1766 MHz (the RTL-SDR Blog V4's range, per the maker's spec). Outside it: refused with the reason, nothing changes.
- Gain: 0–50 dB; the real dongle uses the nearest gain it supports, and the page shows the gain actually used. Attenuator: 0–120 dB. Bad values are refused with the reason.
- A steady signal 20 dB stronger reads 20 dB stronger (within 1 dB). Noise alone reads about 0 dB over noise. A signal outside the 12.5 kHz channel doesn't count.
- Level = channel power − gain + attenuator, so stepping the attenuator by 10 dB on a steady signal leaves the level unchanged (within 1 dB, while not overloaded).
- More than 0.1% of samples at full scale = overload, shown on the page.
- About 10 readings per second reach the page. The tone's pitch rises with dB over noise; it starts only when you turn it on (browsers require a click before playing sound).
- No dongle, or it's unplugged mid-hunt: the page says so and the server keeps retrying every 2 s; it never crashes. Missing pyrtlsdr or librtlsdr: a clear message saying what to install.
- Recording: one JSON line per reading, written as it happens, so a crash loses at most the line being written. File names come from the time only, never from the request.
- Every reading has `heading`, `lat`, `lon` and `node_id` fields (empty for now), for bearing capture and the receiver network later.

**Next (later phases):** bearing capture (yagi heading from an ESP32 compass on the boom, or typed in), map and triangulation, a network of receiver nodes uploading readings to a server, the phone app, and a fox transmitter controller. Open question for bearing capture: which compass/IMU board to use (the XIAO boards' variant and the ESP32-WROOMs are candidates).

### Threat model

Local, receive-only tool on one laptop. The risks are a web page on the internet reaching the local server, and bad input.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | Another website in your browser opens a WebSocket or posts settings to the meter (browsers don't apply the same-origin policy to WebSockets) | A01 Broken Access Control | Listens on 127.0.0.1 only; WebSocket and POSTs need the meter's own `Origin`; `Host` must be 127.0.0.1 or localhost (blocks DNS rebinding) | `test_server.py` |
| T2 | Script injection into the page | A05 Injection | No user text is put into HTML; strict Content-Security-Policy (`script-src 'self'`) | `test_server.py`, `test_browser.py` |
| T3 | A crafted request writes outside `data/` | A01 Broken Access Control | Session file names are generated from the time; nothing from the request reaches a path | `test_meter.py` |
| T4 | Bad settings or dongle errors crash it or leave it stuck | A10 Mishandling of Exceptional Conditions | Settings validated before use (refused whole, nothing half-applied); source errors shown and retried | `test_meter.py`, `test_server.py` |
| T5 | A compromised or brand-new dependency | A03 Software Supply Chain Failures | Exact pins, 2-week rule, `pip-audit` in CI, Dependabot | CI |

Later phases change this: the node server will take uploads over the network (logins, rate limits, OWASP API Top 10), and session files will hold GPS positions.

## Security notes

No secrets and no network access beyond 127.0.0.1. `data/` is gitignored.
