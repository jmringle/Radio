# dipstick

Reads your NanoVNA over USB and tells you, in plain words, what it measured: where your antenna is resonant, how good the match is across a band, how long a coax run is and where a fault in it might be. The goal is to teach you to read the NanoVNA's own screen too, so every number comes with a line saying what it means.

The name: an antenna's resonance shows up as a dip in the SWR curve, and the classic tool for finding it was the grid-dip meter. Like a car's dipstick, it's the quick check you pull out and read.

**Status:** talks to the NanoVNA: finds it, sends allowed commands and reads the replies, with timeouts and checks on every reply. The math that turns its measurement into SWR, impedance and return loss is built and tested, as are the rules for what may be sent and where antenna sweeps may go. No sweeps or command yet (see Next).

**Tested with:** NanoVNA-H, firmware 1.2.43 (DiSlord-based; `info` says "Version: 1.2.43 [p:101, IF:12k, ADC:192k, Lcd:320x240]", built Feb 19 2025), on macOS as `/dev/cu.usbmodem4001`, USB ID 0483:5740.

## Setup

Python 3.12 or newer.

```
cd ~/git/Radio/dipstick
python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.2   # venv starts with the pip Python shipped with; pip-audit flags old ones
.venv/bin/pip install -r requirements-dev.txt
```

## Reading a NanoVNA: the short version

The NanoVNA measures one thing on its CH0 port: **S11**, the reflection coefficient. It sends a signal out, and S11 is how much comes back, with its timing (phase). Everything on the screen is S11 redrawn:

| On the screen | What it is | Good antenna |
|---|---|---|
| **SWR** | How badly the antenna and coax are matched; 1.0 is perfect | Under 1.5 in the part of the band you use; 2.0 is usable |
| **Return loss** (dB) | How far below what was sent the echo is | Higher is better: 14 dB is SWR 1.5, 9.5 dB is SWR 2.0 |
| **R + jX** (impedance) | R: resistance, the part that radiates (or heats). X: reactance, stored energy bouncing back and forth. +jX means too long (inductive), -jX too short (capacitive) | R near 50, X near 0 |
| **Smith chart** | S11 itself, plotted: the center is a perfect match, the outer edge is everything coming back | The trace passes close to the center |

**Resonance** is where X crosses 0. It's often near, but not exactly at, the lowest SWR. Trim a dipole longer to move resonance down, shorter to move it up.

dipstick will print each of these with an explanation for your antenna, so you can compare with the screen.

## Running tests

```
.venv/bin/pytest
```

These use no hardware: replies recorded byte for byte from your NanoVNA (`tests/fixtures/`) are played back by a fake serial port. To also test the real thing, plug the NanoVNA in and run:

```
DIPSTICK_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py
```

Those are read-only (version, board, current sweep settings): they change nothing on the NanoVNA and start no sweep. CI skips them.

The same command runs in GitHub Actions on every push that touches this folder (`.github/workflows/dipstick-tests.yml`, Python 3.12 and 3.15), followed by `pip-audit` (known-vulnerable dependencies). Gitleaks scans the whole repo for committed secrets.

| File | What it guards |
|---|---|
| `tests/test_s11.py` | S11 to impedance, SWR and return loss against hand-worked values; opens and shorts; noise just above 1 on an open; impossible readings refused |
| `tests/test_commands.py` | Only read-and-sweep commands can be sent; anything that could erase calibration or change settings is refused; arguments must be whole numbers, so no second command can be smuggled in |
| `tests/test_device.py` | Finding the NanoVNA: only a port with its USB ID and name, never a look-alike or a radio's CAT cable; none or two found. Asking: recorded replies, one byte or many per read; leftovers from an interrupted session cleared; silence and half replies time out on time; endless replies cut off; a wrong echo (out of step), garbled bytes and the "unknown command" reply are errors |
| `tests/test_hardware.py` | The real NanoVNA answers, is a NanoVNA, reports its sweep settings and stays in step (only with `DIPSTICK_HARDWARE=1`) |
| `tests/test_bands.py` | Band edges (47 CFR 97.301); antenna sweeps must stay inside one band, checked 1 Hz past each edge |

## Design notes

**Language** (decided 2026-11-15): Python with pyserial. The NanoVNA's USB port is a serial port with a text shell, which pyserial handles on Mac and Windows; the math is a few formulas. Python matches the other Radio tools and is your strongest language. Alternatives: NanoVNA-Saver (an existing app; it shows plots but doesn't explain them and isn't built to be tested), or TypeScript with the browser's Web Serial API (it would put the page first, but you chose the command line first).

**Versions** (checked on PyPI 2026-11-15, 2-week rule): pyserial 3.5 (2020-11-23; old, but the standard and stable), pytest 9.2.0, pip-audit 2.10.1.

**Sweeping into an antenna** (decided 2026-11-15): when the NanoVNA sweeps, it puts a very small signal out its port. Into an antenna, that's on the air at every frequency in the sweep. So antenna sweeps stay inside one amateur band: whole bands, your choice, since you control the sweep and the signal is tiny. Feed line checks need a wide sweep, so they go into a cable with no antenna on it, and you have to say so.

### Acceptance criteria (v1, to build)

- **Find the NanoVNA:** only a USB serial port with the NanoVNA's ID (0483:5740) is opened. Writing text to the wrong port, such as a radio's CAT port, could change the radio's settings or worse. None found: say so and list what is connected. More than one: ask for `--port`.
- **`dipstick 40m`** (antenna): sweeps the band, then prints the lowest-SWR frequency and its SWR, SWR at the band edges and middle, the 2:1 bandwidth, the resonant frequency (X = 0) if there is one in the band, and R + jX there, each with a line saying what it means and what to do (e.g. "resonant below the band: shorten the wire"). Saves an SWR plot and a Smith chart as SVG in `output/`.
- **`dipstick cable --far-end open|short`** (feed line): you confirm there's no antenna on the cable. A wide sweep finds the distance to the far end or a fault (time-domain reflectometry, TDR: the time an echo takes to come back, times the speed of the signal in that coax, its velocity factor) and estimates the cable's loss.
- **Leaves the NanoVNA as it found it:** its sweep settings are put back after each scan; it never sends calibration, save, power or reset commands.
- **Calibration:** dipstick uses the NanoVNA's own saved calibration. The README explains when to recalibrate (a different frequency range, cable or adapter).
- **Failure:** NanoVNA unplugged mid-sweep, no answer within a timeout, a garbled or too-long reply, or a reading that can't be real: one clear line, exit code 2, and never a believable but wrong result.

### Threat model

Personal tool on your own machine; no network. It controls a device that puts RF on its port.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | dipstick erases or overwrites your NanoVNA's calibration or settings (a bug, or a bad future change) | A06 Insecure Design | Only read-and-sweep commands are on the allowlist | `test_anything_off_the_allowlist_is_refused` |
| T2 | A value with a carriage return in it ends one command and starts another (`7000000\rclearconfig`): command injection | A05 Injection | Command arguments must be whole numbers; names must be on the allowlist | `test_arguments_must_be_whole_numbers`, `test_a_command_name_cant_carry_a_second_command` |
| T3 | dipstick opens the wrong serial port, such as a radio's CAT port, and sends it text | A06 Insecure Design | Only a port with the NanoVNA's USB ID (0483:5740) whose name also says NanoVNA (that ID is ST's generic one, shared by other STM32 gadgets); otherwise you name the port | `test_never_picks_something_that_isnt_a_nanovna`, `test_two_nanovnas_ask_which` |
| T4 | A garbled, endless or hostile reply from the device crashes the tool or shows wrong numbers | A10 Mishandling of Exceptional Conditions | 5 s timeout; replies capped at 64 KB; plain printable ASCII only; the echo must match the command sent; impossible readings refused | `test_silence_times_out`, `test_it_gives_up_after_the_timeout_not_later`, `test_an_endless_reply_is_cut_off`, `test_garbled_bytes_are_refused`, `test_a_wrong_echo_means_out_of_step`, `test_impossible_measurements_are_refused` |
| T5 | A wide sweep goes out through an antenna, onto non-amateur frequencies | none (radio rules) | Antenna sweeps locked inside one amateur band; wide sweeps only after you confirm no antenna | `test_sweeps_that_leave_a_band_are_refused`; the confirmation with `cable` |
| T6 | A compromised dependency | A03 Software Supply Chain Failures | One dependency, pinned; `pip-audit`, Dependabot | CI |

No secrets: nothing needs a key or password, so there's no `.env`.

## Next

1. ~~Talk to the NanoVNA~~ (done 2026-11-15). On Windows the port may not be named NanoVNA, so you may need `--port COM3` (untested there).
2. `scan` a band and turn it into readings; put the NanoVNA's sweep settings back afterward. Check on the device what `scan` changes first.
3. `dipstick 40m`: the summary and the explanations.
4. SVG plots: SWR across the band and the Smith chart.
5. `dipstick cable`: TDR distance and loss, with velocity factors for your coax (from the manufacturer's data sheet).
6. Later: a local web page with a live SWR curve, for trimming an antenna in the yard; and saving sweeps for antenna-model to compare with its predictions.
