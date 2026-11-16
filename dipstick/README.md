# dipstick

Reads your NanoVNA over USB and tells you, in plain words, what it measured: where your antenna is resonant, how good the match is across a band, how long a coax run is and where a fault in it might be. The goal is to teach you to read the NanoVNA's own screen too, so every number comes with a line saying what it means.

The name: an antenna's resonance shows up as a dip in the SWR curve, and the classic tool for finding it was the grid-dip meter. Like a car's dipstick, it's the quick check you pull out and read.

**Status:** talks to the NanoVNA: finds it, sends allowed commands and reads the replies, with timeouts and checks on every reply. The math that turns its measurement into SWR, impedance and return loss is built and tested, as are the rules for what may be sent and where antenna sweeps may go. `dipstick 40m` sweeps a band and explains the result: best match, SWR across the band, 2:1 bandwidth, where X = 0, and how much to trim. It also saves an SWR plot and a Smith chart as SVG. `dipstick cable` measures a coax cable's length (or velocity factor), what's at its far end, and its loss. Your NanoVNA's own sweep settings are put back afterward. The app adds a guided calibration (open, short, load) for the band you'll measure.

**Download:** the app for macOS, Windows and Linux is on the [Releases page](https://github.com/jmringle/Radio/releases): pick the newest release named **dipstick** (this repository also holds other radio tools' releases) and download only the `dipstick-` file for your computer. On Windows, unblock the zip before extracting it (see [Installing a download](#building-the-app)). The Source code links there are GitHub's automatic snapshot of the whole Radio repository; you don't need them. See [Building the app](#building-the-app) for installing it, the first-launch warning and checking the checksum.

**Tested with:** NanoVNA-H, firmware 1.2.43 (DiSlord-based; `info` says "Version: 1.2.43 [p:101, IF:12k, ADC:192k, Lcd:320x240]", built Feb 19 2025), on macOS as `/dev/cu.usbmodem4001`, USB ID 0483:5740.

## Setup

Python 3.12 or newer.

```
cd ~/git/Radio/dipstick
python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.2   # venv starts with the pip Python shipped with; pip-audit flags old ones
.venv/bin/pip install -r requirements-dev.txt
```

## Usage

Connect the antenna's coax to the NanoVNA's CH0 port, then:

```
.venv/bin/dipstick 40m                  # trims for the middle of the band
.venv/bin/dipstick 40m --target 7.074   # trims for the FT8 frequency
.venv/bin/dipstick 915                  # a frequency instead: sweeps its band (33 cm) and trims for 915 MHz
.venv/bin/dipstick 2m --points 51       # 2 to 101 points (default 101)
.venv/bin/dipstick 40m --port /dev/cu.usbmodem4001   # if it can't find the NanoVNA
```

Bands: 160m, 80m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 2m, 1.25m, 70cm, 33cm, 23cm. Or give a frequency in MHz and dipstick sweeps the band it's in and trims for it: `dipstick 915` for your MeshCore and Meshtastic antennas, `dipstick 146.52`. A frequency outside the bands (FM broadcast's 100, a 60 m channel) is refused before anything is sent. 915 MHz LoRa runs under Part 15 (unlicensed), but the sweep itself stays inside the 33 cm amateur band, 902-928 MHz (47 CFR 97.301(a)), like every antenna sweep. Example (a made-up antenna that's a little long):

```
40m: best match SWR 1.00 at 7.051 MHz (excellent)
Shorten the antenna about 1.4% to move the best match to 7.150 MHz.
  This assumes an antenna you can trim (a wire dipole or end-fed, or an adjustable whip): ...

What the NanoVNA measured: 101 frequencies from 7.000 to 7.300 MHz
  At each one it sent a tiny test signal into the coax and measured how much came back: the
  antenna as your radio sees it, through this coax and any adapter.

Across the band: 7.000 MHz SWR 1.81 | 7.150 MHz SWR 3.03 | 7.300 MHz SWR 10.52
  SWR (standing wave ratio) says how well the antenna matches your 50-ohm coax: ...

2:1 bandwidth: 7.000-7.111 MHz (111 kHz, and it may go lower)
  ...

For the curious, impedance:
X = 0 at 7.051 MHz (at the best match: 50.0 + j0.0 ohms)
  ...
```

The answer comes first: the best match, then what to do. Lines starting with two spaces explain the line above them (the app shows them dimmer). "No trim needed" skips the how-to-trim explanation, and the reminder to recalibrate is left out in the app once you've calibrated there.

Each run also saves two SVG plots (open them in a browser) and lists them at the end: `output/40m-20261115-100621-swr.svg` (SWR across the band, log scale 1 to 10, with the 2:1 line, the best match and your target marked) and `...-smith.svg` (the Smith chart, with a key). Use `--out FOLDER` to save them elsewhere. File names come from the band and the time, never from anything typed. `output/` is gitignored.

Exit codes: `0` measured (whatever the SWR), `2` no NanoVNA, a device problem, or bad arguments (one line on stderr starting `dipstick:`). With nothing on the port it says so ("SWR is infinite everywhere: all of the signal comes back") instead of giving advice.

### Checking a cable

**Disconnect any antenna first.** This sweep runs from 1 MHz to as high as 200 MHz, far outside the ham bands, so dipstick refuses to run without `--no-antenna`. Connect the cable to CH0 and leave its far end **open** (nothing connected) or **shorted**. A dummy load at the far end absorbs the signal, so nothing comes back to measure.

```
.venv/bin/dipstick cable --no-antenna --vf 0.66          # length, from the velocity factor
.venv/bin/dipstick cable --no-antenna --length 50ft      # velocity factor, from a known length
.venv/bin/dipstick cable --no-antenna --vf 0.66 --max-length 100   # cables over 50 m
```

The report starts with the answer ("Cable: 12.00 m (39.4 ft) long, far end open") and what the NanoVNA measured, then the details. It reports whether the far end is open or shorted (it can tell by itself: an open reflects in phase, a short inverted; if you left it open and it reads short, look for a fault), the length (or the distance to a break or short), and the one-way loss at 7, 14, 28 and 50 MHz. Velocity factor (the signal's speed in the cable as a fraction of light's) is on the cable's data sheet: solid polyethylene (RG-58, RG-213) is about 0.66, foam is higher.

**How:** with the far end open or shorted, the whole signal bounces back from it. The echo's phase turns faster with frequency the longer the trip, so a straight line fitted to phase against frequency gives the delay (length = delay x velocity factor x c). The echo comes back weaker by the loss out and back, so one-way loss is half the return loss. The sweep is planned so the phase turns less than half a turn per step for the longest cable you plan for (`--max-length`, default 50 m); a longer cable would alias and look short. If the phase doesn't follow a straight line (an antenna, a load, a fault partway along), the report warns that the numbers are rough.

**Why trim advice comes from SWR, not X:** on low-loss coax, SWR is the same at both ends of the cable, so the lowest-SWR frequency is the antenna's own best match however long the coax is. The impedance R + jX changes along the coax, so X = 0 at the radio's end usually isn't where the antenna itself is resonant. dipstick shows X and explains this, but trims by SWR. The trim percent assumes an antenna you can trim (a wire dipole or end-fed, or an adjustable whip), whose best-match frequency moves opposite to its length (length is roughly proportional to 1 / frequency); the report says so, and that a fixed antenna like a rubber duck can't be trimmed.

**No clear dip:** if SWR stays above 2 and the highest SWR in the band is less than 1.25 times the lowest, there's no dip to move, so the report says so and gives no trim advice. Like your 2m HT antenna's first run (about 5 everywhere): an antenna resonant well outside the band, or something missing or wrong, such as the counterpoise or ground it needs, a bad connector or a lossy cable. A dipole even 10% off frequency rises much more than that across a band. A low, flat SWR across a whole band isn't flagged.

## The app

A window for the same band sweep: pick a band, or just type a target frequency (146.520 sweeps 2 m), press Sweep, and see the report, the SWR plot and the Smith chart together. The band list starts on "Choose a band"; after a sweep it shows the band that was swept. From source:

```
.venv/bin/pip install -r requirements-app.txt   # pywebview (and PyInstaller, for builds)
.venv/bin/dipstick-app
```

**Live** sweeps the band again and again (about 1.5 s a pass on a NanoVNA-H, 101 points) until you press Stop, so you can watch the dip move while you trim an antenna. Stop lets the pass in progress finish, because each pass puts the NanoVNA's own sweep settings back at its end. An error (such as the cable coming out) stops Live and says why.

The header shows whether a NanoVNA is plugged in, checked every 2 seconds. It reads only the computer's list of USB serial ports and never opens the port, so it can't disturb a sweep.

If the NanoVNA is unplugged in the middle of a sweep, the app (and the command) say so, and say what to set its sweep back to by hand: it runs on its battery, so it stays on with the scan's settings.

**Cable** (the second tab) is the same check as `dipstick cable`. Take the antenna off, tick **No antenna connected**, give the velocity factor (to measure the length) or the length (to measure the velocity factor, e.g. `15.2` meters, `50ft` or `6in`; `.6` is 0.6 m), and press **Check cable**. It shows the report and the Smith chart; a cable has no SWR plot. The box clears after every check, so you confirm again each time: the antenna might be back on by then. For a short jumper, set Longest cable low (say `1 m`) so the sweep reaches 200 MHz: a 6-inch cable turns the phase only about 33° in a sweep planned for 50 m (about 110° with `1 m`), and its connectors add about as much delay as the cable itself, so expect a rough answer (an estimate from the math, not yet tried on a real jumper). Python refuses the sweep unless the box's own `true` arrives, never a look-alike such as `"true"` or `1`. While any sweep runs, the other tab can't be opened, and switching tabs clears the old results.

**Calibrate** (the third tab) walks you through calibrating the NanoVNA for one band with the kit that came with it. Calibrating shows it what its own connector, and any adapter or jumper you measure through, look like, so it can take them out of every measurement. Choose the band, then press **Measure open**, **Measure short** and **Measure load**, swapping the standard on the port each time; each step says what that standard does (an open reflects everything in step, a short reflects everything inverted, a 50-ohm load reflects nothing). After the load, the new calibration is applied and the NanoVNA is left sweeping that band. It isn't saved: switch the NanoVNA off and on to go back to its saved calibration. It covers only that band, so a cable check or another band afterward is measured against it less accurately. Choosing another band starts over, a failed step can be tried again, and nothing else can start while a standard is measured. Partway through (after open, before load) the NanoVNA's calibration is reset, so a sweep would be uncorrected but look normal: the Antenna and Cable tabs stay shut until the load step finishes. To stop partway, set the band back to Choose a band and switch the NanoVNA off and on. A step that fails after the reset says so, with the same way back. A sweep of another band than the one you calibrated starts with a note saying the reading isn't calibrated for that band.

Built so far: band sweep with plots, live mode, the connection line, calibration, the cable check (run on a real 6-inch jumper 2026-11-15: open end found, 0.25 m at VF 0.66 from two different sweeps; given `6in` it reported VF 0.41, because the connectors count as cable), builds for Mac, Windows and Linux.

### Building the app

PyInstaller only builds for the system it runs on. GitHub Actions builds all three on every push that touches the app (`.github/workflows/dipstick-app.yml`) and keeps them for 14 days as downloads on the run's page, each with a `.sha256` checksum.

**Releases:** pushing a tag like `dipstick-v0.1.0` (or `dipstick-v0.1.0-beta.1` for a pre-release) runs `.github/workflows/dipstick-release.yml`. It refuses a tag whose version doesn't match `pyproject.toml` and the Mac app's version in `packaging/dipstick.spec`, builds all three through the same workflow (self-tests included), checks every download against its checksum, and makes a **draft** release with the three downloads and one `SHA256SUMS.txt`. Nothing is public until you look the draft over and press Publish. To check a download: `shasum -a 256 -c --ignore-missing SHA256SUMS.txt` (macOS), `sha256sum -c --ignore-missing SHA256SUMS.txt` (Linux) or `Get-FileHash <file>` (Windows PowerShell, prints capitals). Only the release job may write to the repo, and only to create the release. Each build must pass its own `--self-test` first: it opens the window, checks the page reached Python, and closes, with no NanoVNA connection, so nothing is swept. To build on your own computer:

```
.venv/bin/pip install -r requirements-app.txt
.venv/bin/pyinstaller --noconfirm packaging/dipstick.spec   # dist/Dipstick.app (Mac) or dist/Dipstick/ (Windows, Linux)
dist/Dipstick.app/Contents/MacOS/Dipstick --self-test        # prints what it saw, exits 0 if the window reached Python
```

On Linux, install GTK and WebKit first (Ubuntu 24.04 names): `sudo apt install pkg-config libcairo2-dev libgirepository1.0-dev gir1.2-webkit2-4.1`. The built Linux app needs WebKitGTK on the computer it runs on (most desktops have it).

**Installing a download.** First check it wasn't altered (see Releases above for the commands). Releases whose notes mention `gh attestation verify` also have a build attestation for each file: GitHub's signed record that this workflow built it from that release's tag. With the GitHub CLI, `gh attestation verify dipstick-macOS.dmg -R jmringle/Radio` checks it; unlike the checksums, it can't be faked by someone who swaps both files on the release page. The builds aren't code-signed, so your computer can't confirm who made them and warns once:

- **Windows:** before unzipping, right-click `dipstick-Windows.zip` → **Properties** → tick **Unblock** → **OK**. Then **Extract All…**, open the **Dipstick** folder and run **Dipstick.exe** there, leaving the `_internal` folder beside it (for a Desktop icon, use Send to → Desktop (create shortcut) rather than moving the exe). SmartScreen may say "Windows protected your PC": **More info → Run anyway**. Without Unblock, the window can't start ("Failed to resolve Python.Runtime.Loader.Initialize"): Windows marks a downloaded zip as from the internet, Explorer copies that mark onto every file it extracts, and .NET refuses to load the window's marked library. Already extracted? In PowerShell, inside the Dipstick folder: `Get-ChildItem -Recurse | Unblock-File`. Running Dipstick.exe from inside the zip, or without `_internal` beside it, gives "Failed to load Python DLL" instead. Confirmed 2026-11-15 by `.github/workflows/windows-download-check.yml`, which installs a release the way a person does: with the mark it never starts, after Unblock it passes its self-test.
- **macOS:** open the `.dmg` and drag **Dipstick** onto the **Applications** shortcut beside it. Apple Silicon Macs only (M1 or newer): GitHub builds it on an Apple Silicon machine, and the app is arm64 only (checked on beta.2 with `codesign -dv`, 2026-11-16). On an Intel Mac, run it from source instead (`dipstick-app`, under Usage). The first open is blocked: go to System Settings → Privacy & Security, scroll down, click **Open Anyway** next to Dipstick and confirm.
- **Linux:** `tar -xzf dipstick-Linux.tar.gz` and run `Dipstick/Dipstick`. It needs WebKitGTK (most desktops have it).

Only the page's three files are bundled, named one by one in the spec, so your saved sweeps in `output/` can't come along.

**How it's put together:** pywebview shows `src/dipstick/ui/index.html` from a `file://` address, and the page calls Python through pywebview's bridge (`window.pywebview.api`). No web server runs: pywebview only starts its own local HTTP server for plain paths, not `file://` addresses (checked in its source, 2026-11-15). So no other web page in your browser can reach the NanoVNA. The window itself can be sent to another page, though (on macOS a dropped file or a link dragged in from a browser does it), and pywebview gives that page the bridge too, so every call that reaches the NanoVNA first checks the window is still on dipstick's own page (found and fixed 2026-11-16; threat model T7). The page allows only its own script and stylesheet, plus `'unsafe-eval'` (Content Security Policy `script-src 'self' 'unsafe-eval'; style-src 'self'`). pywebview needs eval: it builds its bridge functions with `new Function` and wraps everything it runs in the page in `eval`, so without it the window can't reach Python (found in the real window, 2026-11-15). Inline and remote scripts stay blocked, and nothing typed or measured is ever inserted as markup, so there's no way to get a string to eval. The plots it shows are the same SVG as the saved files, minus their built-in colors, which the page's stylesheet supplies (and switches for dark mode).

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

The page tests (`tests/test_page.py`) run in Chromium and WebKit through Playwright; install those browsers once with `.venv/bin/playwright install chromium webkit`.

These use no hardware: replies recorded byte for byte from your NanoVNA (`tests/fixtures/`) are played back by a fake serial port. To also test the real thing, plug the NanoVNA in and run:

```
DIPSTICK_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py
```

All but one only read (version, board, sweep settings). One sweeps 40 m once (inside the band) and checks your settings come back. CI skips them.

The same command runs in GitHub Actions on every push that touches this folder (`.github/workflows/dipstick-tests.yml`, Python 3.12 and 3.15), followed by `pip-audit` (known-vulnerable dependencies). The app builds (`.github/workflows/dipstick-app.yml`) run `pip-audit` too, on each OS after installing requirements-app.txt, so the Windows- and Linux-only packages are checked and a release can't ship a known-vulnerable one. Gitleaks scans the whole repo for committed secrets.

| File | What it guards |
|---|---|
| `tests/test_s11.py` | S11 to impedance, SWR and return loss against hand-worked values; opens and shorts; noise just above 1 on an open; impossible readings refused |
| `tests/test_commands.py` | Only read-and-sweep commands can be sent, plus `cal` with exactly one of reset, open, short, load or done; `save`, `recall`, other `cal` steps and anything that could erase saved calibration or change settings are refused; arguments must be whole numbers (apart from those step names), so no second command can be smuggled in |
| `tests/test_device.py` | Finding the NanoVNA: only a port with its USB ID and name, never a look-alike or a radio's CAT cable; none or two found. Asking: recorded replies, one byte or many per read; leftovers from an interrupted session cleared; silence and half replies time out on time, and one command can wait longer (a calibration step); endless replies cut off; a wrong echo (out of step), garbled bytes and the "unknown command" reply are errors; unplugged mid-conversation (pyserial's error on a read or a write) says the NanoVNA disconnected; a NanoVNA that never goes quiet (flood or trickle) or a reply that never finishes gives up on time and says to switch it off and on. Opening: the port is locked (`exclusive`), and a port another program holds says so (pyserial's macOS/Linux and Windows messages) instead of "disconnected" |
| `tests/test_scan.py` | A recorded 40 m scan becomes readings; settings read first and always put back, even when the scan fails; a failed restore, or the NanoVNA unplugged mid-scan, says what to set by hand; antenna scans refused outside one band before anything is sent; 2-101 points; every reply line checked (count, numbers, order, range, impossible S11), naming the bad line |
| `tests/test_analysis.py` | The numbers, from a made-up antenna with exact answers (R = 50, X rising steadily; SWR 2 where X = 35.36 ohms): best match, edges, 2:1 bandwidth (interpolated, open-ended, none), X = 0 crossings, trim percent and direction, best match beyond either edge, nothing connected (threshold SWR 10) |
| `tests/test_report.py` | The order (the best match and what to do first, what the NanoVNA measured next, impedance last); "no trim needed" without the how-to-trim text; no reminder to recalibrate just after calibrating. The wording: ratings, shorten or lengthen with the percent, "at least" when the best match is beyond an edge, 2:1 cases, the coax explanation for X, nothing connected gives no advice, the calibration reminder; a flat curve says no clear dip and gives no trim advice (also when its lowest SWR is at an edge), checked just either side of the 1.25 ratio; a real dip with high SWR still gets advice; a low flat curve isn't flagged; trim advice says it's for antennas you can trim |
| `tests/test_cli.py` | The command end to end with a fake NanoVNA: your recorded open-port scan, a good antenna, `--target`, a frequency instead of a band (`915`, `146.52`; outside the bands or with `--target` too, refused before connecting), `--port`, plots saved and listed (`--out`, default `output/`); bad arguments refused before connecting; device and file errors are one line and exit 2; the port is closed and settings put back |
| `tests/test_plots.py` | Positions read back from the SVG against known answers: edge to edge, SWR 1 on the bottom, SWR 2 on the 2:1 line at log10(2) of the height, off-scale and infinite SWR at the top; Smith chart S11 = 0 at the center, 1 at the open edge, -1 at the short edge, +j at the top, noise kept on the edge, the SWR-2 circle at a third of the radius, the R = 50 circle through the center, the best match marked; the target line where the target is (none without one); the Smith key fits inside the chart; a cable's Smith chart has no best-match dot and a key about its laps (one per half wavelength), which fits too |
| `tests/test_cable.py` | Made-up ideal cables with known length, velocity factor, open or short end and sqrt(f) loss: length from VF and VF from length, open vs short, loss at 7/14/28/50 MHz, matched end, a bent phase flagged; the sweep plan keeps under half a turn per step (aliasing), caps at 200 MHz, assumes VF 0.5 when unknown |
| `tests/test_cable_cli.py` | `dipstick cable` (its checks live in `measure.py`, shared with the app) refuses without `--no-antenna` before connecting; length and VF (feet and meters), short end, loss line, `--max-length`, matched end, messy phase warning; the first line is the answer (length, velocity factor, or no echo) and the report says what the NanoVNA measured and why the antenna must be off; bad arguments never connect |
| `tests/test_app_api.py` | The app's Python side (what the page may call): sweep returns the report and both plots (with no inline styles) or a message, never raises; bad requests never connect; long pasted input comes back cut short in the error; length units in any case (`6 IN`, `2001FT`); one sweep at a time across threads; unplugged mid-sweep is explained, not "unexpected"; the NanoVNA line (connected with its port, none, more than one) from the port list without ever connecting; the cable check refused unless No antenna connected is exactly `true`, length or VF with the Smith chart, errors in the app's own words (no `--` options), unplugged mid-sweep, takes turns with band sweeps; two NanoVNAs plugged in say to unplug one, and none found never mentions `--port`; calibrating sends exactly `sweep` (the band, 101 points), `cal reset`, `cal open`, `cal short`, `cal load`, `cal done` and never `save`; open always starts over (a failed open too), steps out of order or a band change partway are refused before connecting, bad bands and steps never connect, a failed step can be retried, a step failing after `cal reset` says switching the NanoVNA off and on brings the saved calibration back (and a failure before it, or after a finished calibration, doesn't), steps wait longer than a normal reply, calibrating takes turns with sweeps; only `bands`, `cable`, `calibrate`, `nanovna` and `sweep` are reachable; the SWR plot marks the target; the reminder to recalibrate is left out after a finished calibration and comes back once a new one starts; calls that reach the NanoVNA are refused unless the window is on dipstick's own page (`is_app_page`: real paths, spaces as `%20`, `localhost`; web pages, other files and another machine's files refused) |
| `tests/test_page.py` | The app's page in Chromium and WebKit with a fake bridge: bands from Python with 40m chosen, Sweep shows report and plots, errors as an alert that clears old results, one sweep at a time (button and Enter), report shown as text not markup, explanation lines (two-space indent) dimmer and still text; Target says MHz and optional; Live says it repeats; a cable's Smith chart stays chart-sized; the cable hint says up to 200 MHz; the Length example is short enough to fit; the calibration step stays apart from the smaller stop-partway note (shown only during short and load), the port is named CH0, and switching off and on is said once; the NanoVNA line follows the connection; Live repeats until Stop, Stop lets the pass in progress finish, an error stops Live, band, target and Sweep locked during Live, Live disabled until Python is reachable; Antenna and Cable tabs switch by click and arrow keys; Check cable needs the No antenna connected box and Python, shows the report and Smith chart (no SWR plot), shows errors, and clears the box after every check; nothing else can start during a cable check, the Cable tab can't open during Sweep or Live, switching tabs clears the box and old results; Calibrate needs a band and Python, walks open, short, load with each step's explanation, stays on a failed step, starts over on another band, locks the tabs while a standard is measured, keeps the Antenna and Cable tabs shut from open until load (not even the arrow keys open them; Choose a band cancels; a failed open leaves them open), and is reached by the arrow keys; a sweep of another band than the calibrated one starts with a note, the calibrated band or no calibration says nothing; no console or Content Security Policy errors (one harmless WebKit `<select>` quirk ignored, WebKit only) |
| `tests/test_window.py` | Runs the app's `--self-test` (the same check CI runs on each build): the real pywebview window opens, reaches Python (band list filled, Sweep and Live enabled, the NanoVNA line filled in, Check cable enabled once the Cable tab's box is ticked, it's never clicked; the Calibrate tab's band list filled; its own address passes the only-our-page check, which is switched on) and closes, about half a second; only with `DIPSTICK_WINDOW=1`. It also sends the real window to another local page (as a dropped file does) and checks that page's call to the NanoVNA is refused with nothing connected (`tests/window_nav_probe.py`, about 5 s). It's the only test that sees the page's security policy as pywebview does: Playwright's own evaluate skips the policy |
| `tests/test_hardware.py` | The real NanoVNA answers, is a NanoVNA, reports its sweep settings, stays in step, and a 40 m scan puts its settings back (only with `DIPSTICK_HARDWARE=1`) |
| `tests/test_bands.py` | Band edges (47 CFR 97.301); antenna sweeps must stay inside one band, checked 1 Hz past each edge |

## Design notes

**Language** (decided 2026-11-15): Python with pyserial. The NanoVNA's USB port is a serial port with a text shell, which pyserial handles on Mac and Windows; the math is a few formulas. Python matches the other Radio tools and is your strongest language. Alternatives: NanoVNA-Saver (an existing app; it shows plots but doesn't explain them and isn't built to be tested), or TypeScript with the browser's Web Serial API (it would put the page first, but you chose the command line first). Later the command grows into a standalone app (Mac, Windows, Linux), built on the same tested pieces.

**Versions** (checked on PyPI 2026-11-15, 2-week rule): pyserial 3.5 (2020-11-23; old, but the standard and stable), pytest 9.2.0, pip-audit 2.10.1.

**Sweeping into an antenna** (decided 2026-11-15): when the NanoVNA sweeps, it puts a very small signal out its port. Into an antenna, that's on the air at every frequency in the sweep. So antenna sweeps stay inside one amateur band: whole bands, your choice, since you control the sweep and the signal is tiny. Feed line checks need a wide sweep, so they go into a cable with no antenna on it, and you have to say so.

### Acceptance criteria (v1, to build)

- **Find the NanoVNA:** only a USB serial port with the NanoVNA's ID (0483:5740) is opened. Writing text to the wrong port, such as a radio's CAT port, could change the radio's settings or worse. None found: say so and list what is connected. More than one: ask for `--port`. The app has no `--port`, so it says to unplug one, and its not-found message doesn't mention it.
- **`dipstick 40m`** (antenna; built 2026-11-15 except the plots): sweeps the band, then prints the lowest-SWR frequency and its SWR, SWR at the band edges and middle, the 2:1 bandwidth, the resonant frequency (X = 0) if there is one in the band, and R + jX there, each with a line saying what it means and what to do (e.g. "resonant below the band: shorten the wire"). Saves an SWR plot and a Smith chart as SVG in `output/`.
- **`dipstick cable --no-antenna --vf 0.66 | --length 50ft`** (feed line; built 2026-11-15): you confirm there's no antenna on the cable. A wide sweep finds the length to the far end or a fault from the echo's delay (the idea behind time-domain reflectometry, done here by fitting the phase), detects whether the end is open or shorted, and estimates the cable's loss. There's no `--far-end` option: it detects the end itself.
- **Leaves the NanoVNA as it found it:** `scan` replaces the NanoVNA's own frequency list and point count, and afterward `sweep` still reports the old start and stop (found on firmware 1.2.43, 2026-11-15). So dipstick reads the settings before each scan and always puts them back, even if the scan fails; if that fails too, it tells you what to set by hand. It never sends save, power or reset commands, and calibration commands only from the Calibrate tab.
- **Calibration** (guided calibration added 2026-11-15): sweeps use the NanoVNA's current calibration, and the report says when to recalibrate (a different frequency range, cable or adapter). The app's Calibrate tab measures open, short and load over one band and applies the result, in the NanoVNA's memory only. From the firmware source (hugen79/NanoVNA-H `main.c`, read 2026-11-15): `sweep START STOP POINTS` and `cal reset|open|short|load|done` change only memory; only `save N` writes flash, and dipstick never sends it; at power-on the saved calibration loads again. `cal done` with only open, short and load fills in the rest (no thru, so S21 isn't corrected; dipstick measures only S11). Each standard is one sweep at 100 Hz bandwidth or narrower, so a step gets 20 s to answer instead of 5. Not yet tried on the real NanoVNA.
- **Failure:** NanoVNA unplugged mid-sweep, no answer within a timeout, a garbled or too-long reply, or a reading that can't be real: one clear line, exit code 2, and never a believable but wrong result.

### Threat model

Personal tool on your own machine; no network. It controls a device that puts RF on its port.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | dipstick erases or overwrites your NanoVNA's saved calibration or settings (a bug, or a bad future change) | A06 Insecure Design | Only read-and-sweep commands are on the allowlist, plus `cal` with five fixed steps that change only memory (never `save`), sent only when you press the Calibrate tab's buttons; switching the NanoVNA off and on brings the saved calibration back | `test_anything_off_the_allowlist_is_refused`, `test_other_cal_arguments_are_refused`, `test_saving_or_recalling_calibration_is_still_refused`, `test_calibrating_open_short_load_over_the_band` |
| T2 | A value with a carriage return in it ends one command and starts another (`7000000\rclearconfig`): command injection | A05 Injection | Command arguments must be whole numbers; names must be on the allowlist | `test_arguments_must_be_whole_numbers`, `test_a_command_name_cant_carry_a_second_command`, `test_other_cal_arguments_are_refused` (`open\rsave 0`) |
| T3 | dipstick opens the wrong serial port, such as a radio's CAT port, and sends it text | A06 Insecure Design | Only a port with the NanoVNA's USB ID (0483:5740) whose name also says NanoVNA (that ID is ST's generic one, shared by other STM32 gadgets); otherwise you name the port | `test_never_picks_something_that_isnt_a_nanovna`, `test_two_nanovnas_ask_which` |
| T4 | A garbled, endless or hostile reply from the device crashes the tool or shows wrong numbers | A10 Mishandling of Exceptional Conditions | 5 s timeout, for a silence and for the whole reply (so a trickle that never reaches a prompt gives up too); replies capped at 64 KB; the leftovers drained when connecting are capped the same way (a NanoVNA whose shell got stuck restarting streamed its banner nonstop, 2026-11-16, and hung the app); plain printable ASCII only; the echo must match the command sent; impossible readings refused | `test_silence_times_out`, `test_it_gives_up_after_the_timeout_not_later`, `test_an_endless_reply_is_cut_off`, `test_a_reply_that_trickles_on_without_a_prompt_gives_up_on_time`, `test_sync_gives_up_on_a_nanovna_that_never_goes_quiet`, `test_garbled_bytes_are_refused`, `test_a_wrong_echo_means_out_of_step`, `test_impossible_measurements_are_refused` |
| T5 | A wide sweep goes out through an antenna, onto non-amateur frequencies | none (radio rules) | Antenna sweeps locked inside one amateur band; wide sweeps only after you confirm no antenna | `test_sweeps_that_leave_a_band_are_refused`, `test_antenna_scans_stay_inside_one_band`, `test_refused_without_no_antenna_and_nothing_is_sent`; in the app, `test_cable_refused_unless_no_antenna_is_exactly_true`, `test_check_cable_needs_the_no_antenna_box`, and the box clearing after every check |
| T6 | A compromised dependency | A03 Software Supply Chain Failures | Pinned versions (2-week rule); `pip-audit`, Dependabot. The app adds pywebview and PyInstaller (requirements-app.txt; PyGObject and pycairo on Linux), the tests Playwright; each OS's build runs `pip-audit` on what it ships | CI |
| T9 | A tampered download reaches you, or your own sweeps end up in a build | A03 Software Supply Chain Failures | Builds only from GitHub Actions on a clean checkout; a SHA-256 checksum with each, checked with the standard tools before upload and again before a release; releases start as drafts, and only the release job may write; the spec bundles only the page's three files by name. Unsigned builds can't prove who made them to your operating system (accepted: Apple's program is $99 a year); instead each release file has a build attestation (`actions/attest`, from beta.4), which `gh attestation verify` checks against this repository's release workflow | the app workflow's checksum step, `--self-test`; `gh attestation verify` on beta.4's downloads passed, and failed on a copy with one byte added (2026-11-16) |
| T7 | Another web page in your browser triggers a sweep through the app (a local server would be reachable from any page); or the app's window is sent to another page (a dropped file, a link dragged in from a browser) and that page calls the NanoVNA: pywebview gives it the bridge too (found in the real window, 2026-11-16), so it could send `cal reset` or a wide cable sweep with an antenna on | A01 Broken Access Control | No server: the page loads from `file://` and calls Python through pywebview's bridge; only `bands`, `cable`, `calibrate`, `nanovna` and `sweep` are exposed. Every call that reaches the NanoVNA first checks the window is still on dipstick's own `index.html` (`is_app_page`, comparing real file paths), wired by the one function that opens windows. `bands` and `nanovna` (the port's name) stay open to such a page: nothing that touches the device | `test_the_page_can_only_reach_public_methods`, `test_another_page_is_refused_and_never_connects`, `test_a_page_the_window_is_sent_to_cant_use_the_nanovna` (real window), the self-test's `app_page` on every CI build |
| T8 | Markup in the report or an error runs as code in the app's window (XSS) | A05 Injection | Report and errors set as text, never HTML; the SVG comes only from dipstick's own plot code; Content Security Policy allows only the page's own script and stylesheet. Accepted: `'unsafe-eval'`, which pywebview's bridge requires; it matters only if a script could be injected, which the rest prevents | `test_report_text_is_shown_as_text_not_markup`, `test_the_pages_security_policy`, the page tests' no-CSP-errors check, `test_window.py` |

No secrets: nothing needs a key or password, so there's no `.env`.

## Next

1. ~~Talk to the NanoVNA~~ (done 2026-11-15). On Windows the port may not be named NanoVNA, so you may need `--port COM3` (untested there).
2. ~~`scan` a range into readings, putting the settings back~~ (done 2026-11-15). The 33cm entry also covers 915 MHz MeshCore antennas (902-928 MHz is both the 33 cm amateur band and the Part 15 ISM band); `dipstick 915` (any frequency in a band) added 2026-11-15.
3. ~~`dipstick 40m`: the summary and the explanations~~ (done 2026-11-15). First real-antenna check, 2026-11-15: the 2m HT antenna read SWR about 5, flat across the band ("No clear dip"), before and after calibrating. Still to do: an antenna with a real dip (an HF antenna on its own band).
4. ~~SVG plots: SWR across the band and the Smith chart~~ (done 2026-11-15).
5. ~~`dipstick cable`: length, far end and loss~~ (done 2026-11-15; run on a real 6-inch jumper the same day: open end, 0.25 m at VF 0.66). Still to do: a cable of known length, to check the accuracy. Later: a true distance-to-fault plot (an inverse FFT of the sweep), to find a fault partway along a cable that's still connected at the far end.
6. ~~A standalone app for Mac, Windows and Linux~~ (built 2026-11-15: pywebview + PyInstaller like ft8-forecast; GTK on Linux, chosen over Qt because it's the WebKit engine the page tests run in and a much smaller build). Band sweep, Live, cable check, calibration. Later: saving sweeps for antenna-model to compare with its predictions.
7. ~~Explain flat curves; trim advice only for antennas you can trim~~ (done 2026-11-15).
8. ~~Guided calibration~~ (built 2026-11-15; run on the real NanoVNA for 2m the same day). ~~Draft GitHub Releases with checksums~~ (workflow added 2026-11-15; beta.1 published that day, beta.4 on 2026-11-16 with build attestations).
9. ~~QA pass on beta.2~~ (2026-11-16): fixed in beta.3/beta.4: two programs sharing the port, a sweep allowed partway through a calibration, no warning when sweeping another band than the calibrated one, a failed calibration step not saying how to get the saved one back, long input echoed whole, case-sensitive units, no Applications link in the dmg, the shipped packages not audited, no build attestations, and (after beta.4) the window-navigation hole in T7. Still to do by hand: the calibration lock with the standards, the USB pulled out mid-sweep, Gatekeeper on the dmg, and the busy-port message on Windows.
