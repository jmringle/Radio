# Band Privileges

Answers "can I operate here?" for US amateur HF: given a frequency, a mode and a license class (Technician, General, Extra), it says whether that's allowed and cites the 47 CFR Part 97 section. It only reads rules; it never talks to a radio or transmits.

Status: v1 complete, plus a local web page. Every v1 HF band (160-10 m; 60 m is deferred), the `bandcheck` command, the `bandcheck-web` page and near-edge warnings work. A WARNING means your signal's width may cross an edge (an LSB voice signal at 7.177 MHz reaches down to about 7.174, below General's 7.175 edge); the tool doesn't model sidebands, so it warns on both sides.

## Disclaimer

This tool is provided as is, with no warranty. Its answers can be wrong, incomplete or out of date. You, as the control operator, are solely responsible for every transmission and for checking your privileges against the current FCC rules ([47 CFR Part 97](https://www.ecfr.gov/current/title-47/part-97)); see §97.103(a). The author accepts no liability for any transmission made, or any consequence resulting, from using this tool. The same disclaimer appears on the web page and in `bandcheck --help`.

## Setup

Requires Python 3.12 or newer (CI uses 3.15).

1. `cd band-privileges`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt`
4. `pip install -e .` (installs the `bandcheck` and `bandcheck-web` commands into the venv)
5. `playwright install chromium` (only for the browser tests; downloads a headless Chromium of about 150 MB)

No configuration or secrets are needed.

## Usage

`bandcheck <MHz> <mode> <class>`. Modes: `cw`, `phone`, `data`, `image`. Classes: `technician`, `general`, `extra`. Case doesn't matter.

```
$ bandcheck 14.074 data general
ALLOWED: data is allowed here (§97.301(d), §97.305(c)(3)(ix))
$ bandcheck 28.4 phone technician
ALLOWED: phone is allowed here (§97.301(e), §97.305(c)(3)(xviii))
NOTE: SSB only (J3E/R3E), §97.307(f)(10)
$ bandcheck 7.177 phone general
ALLOWED: phone is allowed here (§97.301(d), §97.305(c)(3)(vii))
WARNING: within 3 kHz of 7.175 MHz, where phone stops being allowed for general
$ bandcheck 14074 data general
usage: bandcheck [-h] freq mode class
bandcheck: error: argument freq: 14074 MHz is 1 GHz or more; did you mean 14.074 MHz?
```

Exit codes: `0` allowed, `1` denied, `2` bad input, `3` not covered, so scripts can check `$?`.

### Web page

`bandcheck-web`, then open http://127.0.0.1:8073. It's the same rule engine behind a single form; answers, notes and warnings match the command. It listens on this computer only (127.0.0.1), so other devices on your network can't reach it. Stop it with Ctrl+C.

From Python: `check(mhz("14.074"), Mode.DATA, LicenseClass.GENERAL)` returns a `Result` with `status`, `reason`, `citations` and `notes`.

## Running tests

`pytest` from `band-privileges/` runs everything (about 2 s once the browser is installed). The rule and CLI tests are pure logic, with no hardware or network. `tests/test_cli_installed.py` runs the real `bandcheck` command, so it needs step 4 of Setup. CI runs the same command on every push that touches this folder.

Web tests come in two layers:
- `tests/test_web.py` uses Flask's test client: fast, no browser, no real network. It covers answers, bad input (HTTP 400), escaping, security headers and the Host check.
- `tests/test_web_e2e.py` uses [Playwright](https://playwright.dev/python/) (pytest-playwright) to drive a real headless Chromium against the app on a random 127.0.0.1 port. It checks what only a browser can show: the stylesheet really loads under the CSP, Enter submits the form, and the page fits a 360 px phone screen. It needs step 5 of Setup. `pytest --headed` shows the browser window.

## Design notes

**Scope (v1):** HF 160–10 m, ITU Region 2, station in the continental US. Classes: Technician, General, Extra. Modes: CW, phone, data (includes RTTY), image, the groups §97.305 uses.

**Acceptance criteria** (settled 2026-10-25):
- **Command:** `bandcheck <MHz> <mode> <class>`. All three are required (no default class), case-insensitive. Modes: `cw`, `phone`, `data`, `image`. Classes: `technician`, `general`, `extra`.
- **Result:** allowed/denied, a plain reason, and the §97.301 / §97.305 / §97.307 sections that decided it. Plain text, for example:
  ```
  ALLOWED: data is allowed here (§97.301(d), §97.305(c)(3)(ix))
  WARNING: within 3 kHz of 14.150 MHz, where data stops being allowed for general
  ```
- **Exit codes:** `0` allowed, `1` denied, `2` bad input, `3` not covered.
- CW is allowed anywhere the class has privileges (§97.305(a)).
- Technician HF limits follow §97.307(f)(9) (CW only on 80/40/15 m) and (f)(10). Tech phone on 28.3–28.5 MHz is allowed with a note: "SSB only (J3E/R3E), §97.307(f)(10)". On an edge shared with a CW-only segment (e.g. 7.125 MHz, also the start of phone segment (vii)), a Technician's non-CW mode is denied. That's the safe reading of inclusive edges. The 28.300 MHz edge isn't CW-only, so Technician data there stays allowed (row (xvii)), like every other shared edge; the near-edge warning covers the spill into 28.3–28.5.
- **Shared edges:** edges are inclusive at both ends, so a frequency on a shared edge (e.g. 14.150) is inside both segments. Each shared edge gets a test. But where a class's privilege and a mode's segment meet at only one frequency (General phone/image at 3.600, 7.125, 14.150 and 21.200), the mode is denied: no signal fits in a single point.
- **Near-edge warning:** an allowed result warns when the frequency is within 1 kHz (CW) or 3 kHz (phone, data, image), on either side, of an edge that limits this class and mode (band, class segment, or mode segment). An edge limits only if the point 1 Hz beyond it isn't allowed, so 7.100 doesn't warn for Extra data (row (vi) continues). Warnings never change the answer or the exit code.
- Frequencies inside HF but outside every amateur band are denied, not errors.
- **Not covered (exit 3):** 60 m (5.3305–5.4065 MHz) and anything outside 1.8–29.7 MHz. Never "allowed" or "denied". The engine answers this itself (`Status.NOT_COVERED`), so every front end gets it.
- **Bad input (exit 2), with a clear message:** anything but a plain decimal in ASCII digits (so `nan`, `inf`, `1e3`, `1_4.074` and full-width digits are rejected), more than 32 characters, zero or negative, more than 6 decimal places, unknown mode or class, missing arguments. The frequency checks live in `mhz()`, which raises only `ValueError`; mode, class and argument checks belong to the CLI. A number of 1000 or more gets the hint "did you mean <n/1000> MHz?" (people often type kHz). Never silently "allowed".

**Why Python:** your strongest language; pytest makes the table-heavy, boundary-heavy tests easy to write (parametrize); no runtime dependencies. The rule engine knows nothing about the CLI, so a TypeScript or Python web front end can reuse it later (possible phase 2).

**Why integer Hz:** floats can't represent values like 14.150 exactly, so band-edge comparisons could go the wrong way. `mhz("14.150")` parses through `Decimal`.

**Threat model (personal, offline tool):** the only input is command-line arguments. Main risk: a wrong "allowed" answer could lead to an out-of-privilege transmission. Mitigations: values come from eCFR with citations in code and tests; anything unknown or out of scope is refused, not allowed; bad input is rejected. Supply chain: no runtime dependencies; dev deps pinned, audited by pip-audit and updated by Dependabot.

**Deferred:** 60 m (channels, §97.303(h), amended 2026-01-14 by 91 FR 1430); named modes (FT8, SSB, FM) mapped to the four groups; JSON output; a web front end.

**Why warnings instead of modeling sidebands:** Part 97 limits apply to the whole signal, not the dial frequency, so data "at" 14.150 USB actually occupies the phone segment. Modeling USB/LSB and each mode's bandwidth is complex. A both-sides margin is simple, and when it's wrong it over-warns, which is the safe direction.

## Security notes

- No secrets. `.env` files are gitignored at the repo root anyway, and gitleaks scans every push.
- Input validation: arguments and form fields are untrusted. Frequencies must be plain decimals of at most 32 characters, and modes and classes must be one of the listed words; anything else is rejected with a message.

Threat model for the web page (OWASP Top 10:2025, checked 2026-10-24). What's protected: your computer and browser, and the correctness of the answers. There is no login, no stored data and no radio control.

| ID | Threat | OWASP | Mitigation | Test |
|----|--------|-------|------------|------|
| T1 | A typed value is echoed back as HTML and runs as script (XSS) | A05 Injection | Jinja autoescaping; CSP allows no scripts | `test_web.py` escaping test |
| T2 | Another device, or a hostile website using DNS rebinding (pointing its own name at 127.0.0.1), reaches the page | A01 Broken Access Control | Binds to 127.0.0.1 only; `TRUSTED_HOSTS` rejects any other Host header with 400 | `test_web.py` Host and bind tests |
| T3 | The Werkzeug debugger runs code sent from the browser | A02 Security Misconfiguration | `debug=False`, enforced by a test | `test_web.py` main test |
| T4 | An error page leaks a stack trace | A10 Mishandling of Exceptional Conditions | Bad input returns a plain 400 message; unexpected errors return a generic 500 | `test_web.py` 400 and 500 tests |
| T5 | A huge or odd frequency hangs the server | A10 | 32-character cap; plain decimal digits only; exact integer math | `test_rules.py` abuse cases |
| T6 | Another site frames the page (clickjacking) or reads where you came from | A02 | CSP `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, `nosniff` | `test_web.py` header test |

Accepted risk: plain HTTP, no HTTPS. Traffic never leaves this computer (loopback), and nothing secret is sent. Revisit this before ever exposing the page beyond 127.0.0.1.
- Accepted risk: the tables are hand-entered. A Part 97 change won't update them; re-check eCFR and update the "checked" date in `rules.py`.

## Regulatory

- Part 97 (amateur service). This tool is advisory and does not transmit; the control operator is still responsible for staying within privileges.
- Rules used: §97.301 (frequency privileges by class), §97.305 (authorized emission types), §97.307(f)(9)–(11) (Technician limits; 40 m phone on 7.075–7.100 MHz is only for Region 2 stations west of 130° W or south of 20° N, e.g. Hawaii, so v1 denies it).
- Not checked by this tool (it doesn't model power or sharing): 30 m is limited to 200 W PEP (§97.313(c)(1)), and amateurs there must not cause harmful interference to, and must accept interference from, other nations' fixed-service stations (§97.303(j)).
- Source: [eCFR 47 CFR Part 97](https://www.ecfr.gov/current/title-47/part-97), checked 2026-10-25.
