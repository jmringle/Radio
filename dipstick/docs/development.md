# Developing Dipstick

## Run from source

Needs Python 3.12 or newer.

```
cd ~/git/Radio/dipstick
python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.2    # the venv's bundled pip is old; pip-audit flags it
.venv/bin/pip install -r requirements-dev.txt  # the command and the tests
.venv/bin/pip install -r requirements-app.txt  # the app (pywebview, and PyInstaller for builds)

.venv/bin/dipstick 40m       # the command
.venv/bin/dipstick-app       # the app
```

On Linux, install GTK and WebKit first (Ubuntu 24.04 package names): `sudo apt install pkg-config libcairo2-dev libgirepository1.0-dev gir1.2-webkit2-4.1`.

## Tests

```
.venv/bin/playwright install chromium webkit   # once, for the page tests
.venv/bin/pytest                               # everything that needs no hardware
```

The tests use no hardware. Replies recorded byte for byte from a real NanoVNA-H (`tests/fixtures/`) are played back through a fake serial port. `tests/fixtures/original_fw/` holds replies built from the original firmware's source, since there's no such device here. Two opt-in suites need the real thing:

```
DIPSTICK_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py   # NanoVNA plugged in: reads, plus one 40 m scan
DIPSTICK_WINDOW=1 .venv/bin/pytest tests/test_window.py       # the real pywebview window (~5 s)
```

`test_window.py` is the only test that sees the page's Content Security Policy as pywebview applies it, because Playwright's `page.evaluate` bypasses the policy. Run it before calling an app change done.

| Test file | What it guards |
|---|---|
| `test_s11.py`, `test_s21.py` | The maths: S11 to impedance, SWR and return loss; S21 to loss in dB; impossible readings refused |
| `test_commands.py` | The command allowlist and whole-number arguments (T1, T2) |
| `test_device.py` | Finding the NanoVNA (never a look-alike or a CAT cable, the Windows device name, the original-firmware hint), timeouts, garbled and endless replies, unplugging, the port lock (T3, T4) |
| `test_scan.py` | Scans become readings; settings always put back; one-band rule; every reply line checked; S21 scans; calibration status; original-firmware replies |
| `test_bands.py` | Band edges (47 CFR 97.301), checked 1 Hz past each edge (T5) |
| `test_analysis.py`, `test_report.py` | Best match, bandwidth, trim advice, flat curves, and the report's order and wording |
| `test_cable.py`, `test_cable_cli.py` | Length, velocity factor, open/short, loss, the aliasing-safe sweep plan, and the `--no-antenna` gate |
| `test_balun.py`, `test_choke.py`, `test_loss.py` and their `_cli` files | The three balun tests' maths, rating boundaries, error cases and gates |
| `test_plots.py` | SVG positions checked against known answers |
| `test_quiz.py` | Check yourself questions against hand-worked answers (mutation-checked) |
| `test_cli.py` | The command end to end with a fake NanoVNA |
| `test_app_api.py` | Everything the page can call: input checks, one sweep at a time, the gates, calibration order, the port picker, the only-our-page check (T5, T7) |
| `test_page.py` | The page in Chromium and WebKit with a fake bridge: every tab, Live, locks, errors, text-not-markup, no CSP errors (T8) |
| `test_window.py` | The real window's self-test, the navigation guard and quitting (T7, T8) |
| `test_hardware.py` | The real NanoVNA (opt-in) |

GitHub Actions runs the tests on every push that touches this folder (`.github/workflows/dipstick-tests.yml`, Python 3.12 and 3.15), then `pip-audit`. Gitleaks scans the whole repository for committed secrets.

**Lessons learned:**
- Test doubles must mirror the real library's behavior. pywebview fills `window.pywebview.api` *after* creating it.
- `Api(connect=None)` is the only safe double for input-only tests. `Api(ports=lambda: [])` can still reach a real device.
- Page tests that call `requestSubmit()` must wait for the fake bridge to be ready first.
- `pyproject.toml` already selects both browsers, so don't pass `--browser` on the command line. That doubles the runs; use `-o addopts="--browser chromium"` instead.

## Building and releasing

PyInstaller builds only for the system it runs on, so GitHub Actions builds all three on every push that touches the app (`.github/workflows/dipstick-app.yml`). Each build must pass `--self-test` (open the window, confirm it reached Python, close) and `pip-audit` on what it ships.

To build locally:

```
.venv/bin/pyinstaller --noconfirm packaging/dipstick.spec   # dist/Dipstick.app (Mac) or dist/Dipstick/
dist/Dipstick.app/Contents/MacOS/Dipstick --self-test       # exits 0 if the window reached Python
```

On Windows, `ISCC.exe /DAppVersion=0.1.0 packaging\dipstick.iss` wraps the build in the installer (needs [Inno Setup](https://jrsoftware.org/isinfo.php) 6).

**Releases.** Push a tag like `dipstick-v0.1.0` (or `dipstick-v0.1.0-beta.1` for a prerelease). `.github/workflows/dipstick-release.yml` then:
1. refuses the tag if its version doesn't match `pyproject.toml` and `packaging/dipstick.spec`;
2. builds all three platforms and runs their self-tests;
3. runs the Windows download check;
4. attests the builds;
5. creates a **draft** release with `SHA256SUMS.txt`.

Nothing is public until you publish the draft.

**Why Windows uses an installer, not a zip.** Windows marks a downloaded zip as coming from the internet, and Explorer copies that mark onto every extracted file. .NET then refuses to load the window's library ("Failed to resolve Python.Runtime.Loader.Initialize"). Files written by an installer don't get the mark. `.github/workflows/windows-download-check.yml` proves this on every release.

**The icon** is drawn once in `packaging/icon.svg`. After changing it, run `.venv/bin/python packaging/make_icons.py` on a Mac and commit the regenerated `Dipstick.icns` and `Dipstick.ico`.

## How the app is put together

pywebview shows `src/dipstick/ui/index.html` from a `file://` address, and the page calls Python through pywebview's bridge (`window.pywebview.api`). The command (`cli.py`) and the app (`app.py`) share the same measurement code (`measure.py`).

There's no web server, so no web page in your browser can reach the NanoVNA. The Content Security Policy is `script-src 'self' 'unsafe-eval'; style-src 'self'`. pywebview needs the eval: it builds its bridge with `new Function`. See [security.md](security.md) for the threat model.

| Module | Job |
|---|---|
| `device.py` | Find the port, open it, talk to the `ch>` shell with timeouts and checks |
| `commands.py` | The allowlist and command framing |
| `scan.py` | Sweep a range, read it into readings, put the settings back |
| `s11.py`, `s21.py` | Reflection and transmission maths |
| `analysis.py`, `report.py`, `plots.py`, `quiz.py` | Antenna analysis, report wording, SVG plots, Check yourself |
| `cable.py`, `balun.py` | The cable and balun tests |
| `bands.py` | Amateur band edges (47 CFR 97.301(a), (b)) |
| `measure.py` | Shared input checks and measurements for the command and the app |
| `app.py`, `ui/` | The app's Python side and its page |
| `settings.py` | The app's one file, `settings.json` (Check yourself on/off, approved USB IDs) |

## NanoVNA compatibility

Checked against the firmware sources on 2026-11-17 ([DiSlord/NanoVNA-D](https://github.com/DiSlord/NanoVNA-D), [hugen79/NanoVNA-H](https://github.com/hugen79/NanoVNA-H), [ttrftech/NanoVNA](https://github.com/ttrftech/NanoVNA)):

- **hugen79 and DiSlord firmware** report USB ID 0483:5740 with the product name "NanoVNA-H" (or "NanoVNA-H4" on H4 builds), so Dipstick finds them by name.
- **Original firmware (ttrftech)** uses the same ID but keeps ChibiOS's default name, "ChibiOS/RT Virtual COM Port". Its shell matches what Dipstick needs: the `ch> ` prompt, echo, `sweep` alone printing `start stop points`, `scan START STOP POINTS MASK`, and 101 points. So Dipstick names such a port in the not-found message, but never opens it unasked (T3).
- **NanoVNA V2 / V2 Plus4 / LiteVNA** speak a binary register protocol instead of a text shell ([scopehal VNA drivers](https://hansemro.github.io/scopehal-docs/section-vna-drivers.html), [LiteVNA user guide](https://www.rcscomponents.kiev.ua/datasheets/LiteVNA_User-Guide.pdf)). Supporting them would need a second driver.
- **NanoVNA-F series:** not checked. A forum report says `scan` was disabled in at least one build. The output of `version`, `info` and `help` from an owner would settle it.

## Design decisions

- **Python with pyserial** (2026-11-15). The NanoVNA's USB port is a serial port with a text shell, and the maths is a few formulas. Python matches the other Radio tools. Alternatives considered: NanoVNA-Saver (shows plots but doesn't explain them) and TypeScript with Web Serial (browser-first).
- **pywebview + PyInstaller** for the app, like ft8-forecast. GTK on Linux: it's the WebKit engine the page tests run in, and the build is much smaller than with Qt.
- **Antenna sweeps cover whole amateur bands**, never beyond. The signal is tiny, but into an antenna it's on the air. Wide sweeps only go into a cable or test setup with no antenna, and you must say so.
- **Versions** are pinned and checked on PyPI, each at least two weeks old (pyserial 3.5, pytest 9.2.0, pip-audit 2.10.1 as of 2026-11-15).

## Next

- **Hardware checks still to do:** the balun tests (needs resistors and a second identical transformer), the two-port calibration with the kit's thru connector, a cable of known length for accuracy, and the EFHW's flat SWR on 40 m. (beta.14 checked by hand on Windows 2026-11-17: found the NanoVNA and swept. The Linux build is checked only in CI.)
- **Later:** a distance-to-fault plot (an inverse FFT of the sweep), and saving sweeps for antenna-model to compare with its predictions.
