# Band Privileges

Answers "can I operate here?" for US amateur HF: given a frequency, a mode and a license class (Technician, General, Extra), it says whether that's allowed and cites the 47 CFR Part 97 section. It only reads rules; it never talks to a radio or transmits.

Status: in progress. The rule engine covers 160, 80/75, 40, 30, 20 and 15 m; the other HF bands and the command line come next.

## Setup

Requires Python 3.12 or newer (CI uses 3.15).

1. `cd band-privileges`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt`

No configuration or secrets are needed.

## Usage

The CLI isn't built yet. From Python:

```python
from band_privileges import LicenseClass, Mode, check, mhz

check(mhz("14.074"), Mode.DATA, LicenseClass.GENERAL)
# Result(allowed=True, reason='data is allowed here', citations=('§97.301(d)', '§97.305(c)(3)(ix)'))
```

## Running tests

`pytest` from `band-privileges/`. The tests are pure logic, with no hardware or network. CI runs the same command on every push that touches this folder.

## Design notes

**Scope (v1):** HF 160–10 m, ITU Region 2, station in the continental US. Classes: Technician, General, Extra. Modes: CW, phone, data (includes RTTY), image, the groups §97.305 uses.

**Acceptance criteria** (settled 2026-10-25):
- **Command:** `bandcheck <MHz> <mode> <class>`. All three are required (no default class), case-insensitive. Modes: `cw`, `phone`, `data`, `image`. Classes: `technician`, `general`, `extra`.
- **Result:** allowed/denied, a plain reason, and the §97.301 / §97.305 / §97.307 sections that decided it. Plain text, for example:
  ```
  ALLOWED: data is allowed here (§97.301(d), §97.305(c)(3)(ix))
  WARNING: within 3 kHz of the 14.150 MHz data/phone edge
  ```
- **Exit codes:** `0` allowed, `1` denied, `2` bad input, `3` not covered.
- CW is allowed anywhere the class has privileges (§97.305(a)).
- Technician HF limits follow §97.307(f)(9) (CW only on 80/40/15 m) and (f)(10). Tech phone on 28.3–28.5 MHz is allowed with a note: "SSB only (J3E/R3E), §97.307(f)(10)". On an edge shared with a CW-only segment (e.g. 7.125 MHz, also the start of phone segment (vii)), a Technician's non-CW mode is denied. That's the safe reading of inclusive edges.
- **Shared edges:** edges are inclusive at both ends, so a frequency on a shared edge (e.g. 14.150) is inside both segments. Each shared edge gets a test.
- **Near-edge warning:** an allowed result warns when the frequency is within 1 kHz (CW) or 3 kHz (phone, data, image), on either side, of an edge that limits this class and mode (band, class segment, or mode segment).
- Frequencies inside HF but outside every amateur band are denied, not errors.
- **Not covered (exit 3):** 60 m (5.3305–5.4065 MHz) and anything outside 1.8–29.7 MHz. Never "allowed" or "denied".
- **Bad input (exit 2), with a clear message:** non-numeric, `nan`/`inf`, zero or negative, more than 6 decimal places, unknown mode or class, missing arguments. A number of 1000 or more gets the hint "did you mean <n/1000> MHz?" (people often type kHz). Never silently "allowed".

**Why Python:** your strongest language; pytest makes the table-heavy, boundary-heavy tests easy to write (parametrize); no runtime dependencies. The rule engine knows nothing about the CLI, so a TypeScript or Python web front end can reuse it later (possible phase 2).

**Why integer Hz:** floats can't represent values like 14.150 exactly, so band-edge comparisons could go the wrong way. `mhz("14.150")` parses through `Decimal`.

**Threat model (personal, offline tool):** the only input is command-line arguments. Main risk: a wrong "allowed" answer could lead to an out-of-privilege transmission. Mitigations: values come from eCFR with citations in code and tests; anything unknown or out of scope is refused, not allowed; bad input is rejected. Supply chain: no runtime dependencies; dev deps pinned, audited by pip-audit and updated by Dependabot.

**Deferred:** 60 m (channels, §97.303(h), amended 2026-01-14 by 91 FR 1430); named modes (FT8, SSB, FM) mapped to the four groups; JSON output; a web front end.

**Why warnings instead of modeling sidebands:** Part 97 limits apply to the whole signal, not the dial frequency, so data "at" 14.150 USB actually occupies the phone segment. Modeling USB/LSB and each mode's bandwidth is complex. A both-sides margin is simple, and when it's wrong it over-warns, which is the safe direction.

## Security notes

- No secrets. `.env` files are gitignored at the repo root anyway, and gitleaks scans every push.
- OWASP Top 10 mostly doesn't apply (no web, no network, no stored data). The relevant habit is input validation (A03 Injection family): treat the arguments as untrusted and reject anything malformed.
- Accepted risk: the tables are hand-entered. A Part 97 change won't update them; re-check eCFR and update the "checked" date in `rules.py`.

## Regulatory

- Part 97 (amateur service). This tool is advisory and does not transmit; the control operator is still responsible for staying within privileges.
- Rules used: §97.301 (frequency privileges by class), §97.305 (authorized emission types), §97.307(f)(9)–(11) (Technician limits; 40 m phone on 7.075–7.100 MHz is only for Region 2 stations west of 130° W or south of 20° N, e.g. Hawaii, so v1 denies it).
- Not checked by this tool (it doesn't model power or sharing): 30 m is limited to 200 W PEP (§97.313(c)(1)), and amateurs there must not cause harmful interference to, and must accept interference from, other nations' fixed-service stations (§97.303(j)).
- Source: [eCFR 47 CFR Part 97](https://www.ecfr.gov/current/title-47/part-97), checked 2026-10-25.
