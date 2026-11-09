# foxhunt

Tools for radio fox hunting (finding a hidden transmitter). A **live signal meter** for hunting with a yagi and an attenuator: an RTL-SDR measures how strong the fox is, and a page in your browser shows it as a number, a bar, a 60-second graph and a tone that rises as you get closer. On top of that: it learns the fox's on/off schedule, coaches the attenuator, fits each spot's bearing from a sweep, and maps where the fox probably is from bearings taken at several spots.

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
foxhunt --freq 146.565 --sim-burst 30/90   # simulator fox that transmits 30 s, then is quiet 90 s
```

Open http://127.0.0.1:8075. Options: `--gain DB` (fixed tuner gain, default 20), `--att DB` (what your attenuator is set to, default 0), `--port N`. Gain and attenuator can also be changed on the page.

- **dB over noise** (the big number): how far the fox is above the noise right now. This is the hot/cold reading.
- **Level**: the signal's strength with the gain and attenuator taken back out, so it stays comparable when you change them. It's relative dB, not a calibrated dBm.
- **Peak**: the highest level since you last pressed Reset (or changed frequency).
- **Overload**: the dongle's input is clipping. Readings are wrong until you add attenuation or lower the gain.
- **Record** saves every reading to `data/sessions/<UTC time>.jsonl`, one JSON object per line.
- **Schedule** (under the bar): most foxes transmit in bursts. After 3 transmissions it shows the pattern and counts down: "Next transmission in about 40 s (every 120 s, on for 30 s)". It says when the timing is irregular (or there's more than one fox) and when the fox is overdue.
- **Advice** (the box above the reading): what to change on the attenuator: add 10 dB when overloaded, add 20 dB when the signal is so strong the meter has no room to rise, remove 10 dB when attenuation is hiding a weak fox, and a body-shielding tip when it's strong even with 60+ dB of attenuation. Nothing while the fox is between transmissions.
- **Spots and bearings**: at each place you stop, press **New spot** (latitude and longitude are optional, but the map needs them; long-press in your phone's map app shows them). Then either point the yagi where the signal peaks and **Mark bearing** once, or **sweep**: mark the level at several headings (every 30-45°, including some weaker ones on both sides of the peak). From 4+ marks it fits the bearing with a ± range; from fewer, it uses the strongest mark with an assumed ±15°. Bearings can't be marked while the fox is between transmissions (the reading would be noise). While recording, spots and bearings are written to the session file as lines with `"kind": "spot"` and `"kind": "bearing"`. Everything starts over when you change frequency.
- **Map**: with bearings from 2+ spots with positions, a north-up plot (no street map, so it works offline) shades where the fox probably is, gives the most likely latitude/longitude (to paste into a phone map) and the size of the area holding 90% of the probability. With 4+ spots, a bearing that disagrees with the rest is flagged as a likely reflection and left out.

**True or magnetic north?** A compass points to magnetic north, which differs from true (map) north by the *magnetic declination*: several degrees in much of the US, and it differs by location. Bearings will be drawn on maps later, and maps use true north, so set your compass app to true north if it has that option (most phone compass apps do). If it doesn't, note that the bearings are magnetic. NOAA's declination calculator gives the value for your area.

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

**Acceptance criteria (phase 2b: schedule, coaching, sweep fit, map).** Thresholds are starting values, to be tuned after real hunts.
- Schedule: on at 6+ dB over noise or overloaded, off under 3 dB (two thresholds so a signal near one doesn't flicker); a change must last 3 readings (0.3 s), so a noise spike isn't a transmission. A pattern needs 3 starts whose 2+ intervals agree within 20% (or 2 s); otherwise "learning" or "irregular". Uses the last 6 transmissions, so a changed pattern is relearned. Late by more than half a period (at least 5 s): "overdue". A fox never heard is not "off" (it may just be weak). New frequency: forgotten.
- Advice: from the last second (10 readings) so one odd reading doesn't flip it; any overload in that second: add 10 dB (and lower the gain, unless it's 0). Median over 45 dB (an 8-bit dongle has about 48 dB of range): add 20 dB, or the body-shielding tip at 60+ dB of attenuation. Median under 6 dB with attenuation in: remove 10 dB. Exactly at a threshold: no advice. Nothing while the fox is between transmissions; starts over when settings change.
- Sweep fit: a cardioid beam pattern (sharpness fitted, back floored at -20 dB) fitted over every heading in 0.5° steps; the ± is the range where the fit is worse by less than one reading's variance (about 68%), at least 3°. Refuses to fit (falls back to the strongest mark, ±15° assumed) with fewer than 4 marks, no weaker mark on each side of the strongest, less than 3 dB from strongest to weakest, or a ± over 90°.
- Map: each bearing is a wedge whose width is its ±, with a 10% allowance for any one bearing being wrong so a reflection can't veto the rest. Needs 2+ spots with positions and bearings, else says so. Reflection: with 4+ spots, a bearing off the best location by more than 3× its ± (and 20°), only when 3+ spots agree. Grid 160×160 across at least 2 km and at most 50 km (flat-earth math is fine at that size); an estimate at the edge says the fox may be farther.
- Positions: latitude -90 to 90 and longitude -180 to 180, both or neither; anything else refused with the reason, nothing saved.

**Acceptance criteria (phase 2a: typed-in bearings).**
- Heading: 0-360 degrees; 360 is saved as 0. Blank, text, negative, over 360 or not a number: refused with the reason, nothing saved.
- A bearing saves time, frequency, heading, peak level, current level and dB over noise, plus empty `lat`, `lon` (filled in a later phase) and `node_id`.
- No reading yet, or the latest reading is overloaded: refused with the reason (clipping flattens the peak, so the heading of the peak can't be trusted).
- While recording, each bearing is its own line with `"kind": "bearing"`; reading lines don't change.
- A new frequency clears the bearings (a different fox); a new attenuator or gain doesn't.
- Marking a bearing is a POST with the same Origin check as the other controls (T1); the page shows bearings as text, never HTML (T2).

**Next (later phases):** automatic bearing capture (yagi heading from an ESP32 compass on the boom, filling the same `heading` field typed-in bearings use), map and triangulation, a network of receiver nodes uploading readings to a server, the phone app, and a fox transmitter controller. Bearing capture will use a Seeed XIAO ESP32-C6 on the yagi boom (3.3 V logic; USB serial now, Bluetooth LE for the phone app later) plus a compass module, not chosen yet: a BNO085 (does its own sensor fusion and gives a tilt-compensated heading; about $20-25) or a bare QMC5883L-type magnetometer (a few dollars, but the firmware must do tilt compensation and calibration).

### Threat model

Local, receive-only tool on one laptop. The risks are a web page on the internet reaching the local server, and bad input.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | Another website in your browser opens a WebSocket or posts settings, spots or bearings to the meter (browsers don't apply the same-origin policy to WebSockets) | A01 Broken Access Control | Listens on 127.0.0.1 only; WebSocket and POSTs need the meter's own `Origin`; `Host` must be 127.0.0.1 or localhost (blocks DNS rebinding) | `test_server.py` |
| T2 | Script injection into the page | A05 Injection | No user text is put into HTML; strict Content-Security-Policy (`script-src 'self'`) | `test_server.py`, `test_browser.py` |
| T3 | A crafted request writes outside `data/` | A01 Broken Access Control | Session file names are generated from the time; nothing from the request reaches a path | `test_meter.py` |
| T4 | Bad settings or dongle errors crash it or leave it stuck | A10 Mishandling of Exceptional Conditions | Settings validated before use (refused whole, nothing half-applied); source errors shown and retried | `test_meter.py`, `test_server.py` |
| T5 | A compromised or brand-new dependency | A03 Software Supply Chain Failures | Exact pins, 2-week rule, `pip-audit` in CI, Dependabot | CI |

| T6 | Spot positions reveal where you were (personal location data) | A01 Broken Access Control | Positions stay in memory and in `data/` (gitignored); nothing is sent off the laptop; the map draws no tiles, so no map service learns your location | `.gitignore`, no network code |

Later phases change this: the node server will take uploads over the network (logins, rate limits, OWASP API Top 10).

## Security notes

No secrets and no network access beyond 127.0.0.1. `data/` is gitignored; session files can hold the positions you typed, so don't share them casually.
