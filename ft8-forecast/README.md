# FT8 Forecast

Answers "which band should I try for FT8 right now?" from your own WSJT-X/JTDX data: what you've decoded (`ALL.TXT`) and who you've worked (ADIF log), hour by hour. It only reads files; it never talks to a radio or transmits.

Status: both file parsers (ADIF and `ALL.TXT`) work, are tested, and read the author's real files with no problems (2026-10-28). The `ft8cast` command (import, solar, forecast) isn't built yet; see "Next" in Design notes.

## Setup

Requires Python 3.12 or newer (CI uses 3.15). Lives next to `band-privileges` in this repo and imports it.

1. `cd ft8-forecast`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt` (also installs `../band-privileges` in editable mode)

## Configuration

`cp .env.example .env` and set `MY_GRID` to your 4-character grid square. `.env` is gitignored. Not used until the forecast step exists.

## Your data

Copy files from the radio computer into `data/` (gitignored, along with any `*.adi`, `*.adif`, `ALL.TXT` and `*.sqlite` anywhere in this folder: they hold other operators' callsigns and locations):
- the ADIF log (WSJT-X: File > Open log directory, `wsjtx_log.adi`);
- `ALL.TXT` from the same folder.

## Running tests

`pytest` from `ft8-forecast/` runs everything. No network, no radio, no real logs: tests build made-up ADIF records and `ALL.TXT` lines (in the real file's exact layout) with `N0CALL`. CI runs the same command on every push that touches this folder or `band-privileges`, then `pip-audit`.

## Design notes

**Data, in priority order (decided 2026-10-28):** your own data first. The forecast comes only from `ALL.TXT` and ADIF. NOAA solar data can add a warning flag, never change the score. PSKReporter (who heard *you*) is out of v1; it can be added later as a manual command if forecasts prove too optimistic, since hearing a station doesn't mean it hears your 20 W.

**Acceptance criteria** (settled 2026-10-28). Every command is manual; nothing runs on a schedule.
- `ft8cast import <file>`: reads an `ALL.TXT` or ADIF file into a local SQLite database (`data/`, gitignored). Re-importing the same file doesn't duplicate. Never modifies the source file. Bad lines are skipped and reported with line numbers; a file with no valid lines is an error.
- `ft8cast solar`: fetches the planetary K-index and F10.7 from [NOAA SWPC](https://services.swpc.noaa.gov/json/) once and saves them. Out-of-range values (K outside 0-9, flux 0 or less) are rejected.
- `ft8cast forecast [--hour HH]`: per band, for the current UTC hour or the one given:
  - "open on X of Y days you were listening". Open = at least 1 decode that hour. Y counts only days `ALL.TXT` shows you on that band at that hour, so a band you never use reads "unknown", not "dead". Window: the last 30 days.
  - distinct stations heard, median SNR, farthest station (CQ messages carry a grid);
  - confirmed contacts from ADIF, shown separately (proven two-way paths).
  - Fewer than 5 listening days on a band at that hour: "not enough data", never a score.
  - Only bands where General may operate data, via `band-privileges`.
  - Solar line shows its age; older than 6 hours (the K-index updates every 3) says to run `ft8cast solar`; none saved: "solar data unavailable", and the forecast still shows.

**ADIF parser** (`src/ft8_forecast/adif.py`): follows ADIF 3.1.6 section IV.A ([adif.org](https://adif.org/316/ADIF_316.htm), checked 2026-10-28). Each field's length decides where its data ends, so a comment containing `<EOR>` can't break a record. Only FT8 contacts are kept; other modes are counted, not reported as errors. A bad grid costs the distance, not the contact. Frequencies parse with `band-privileges`' `mhz()`, so both projects accept exactly the same numbers. An empty `<gridsquare:0>` (WSJT-X's "unknown") is the same as no grid.

**`ALL.TXT` parser** (`src/ft8_forecast/alltxt.py`): the format isn't formally documented, so the rules come from surveying the author's real file (424,976 lines, 2025-12 to 2026-10). Every line is `YYMMDD_HHMMSS  dial-MHz  Rx|Tx  mode  SNR  DT  audio-Hz  message`. What the survey found and how it's handled:
- dial `0.000` (WSJT-X didn't know the frequency; 19 days): band unknown, so counted and skipped, never guessed;
- `Tx` lines are your own transmissions: kept, marked `transmit`, as proof you were on the band, never counted as stations heard;
- FT4 and other modes: counted and skipped;
- trailing `a1`-`a9` tags (WSJT-X "a priori" decodes): dropped before reading the message;
- `RR73` has a grid's shape but is the sign-off: never a grid;
- lines aren't strictly in time order (late decode passes, up to 60 s back): nothing assumes order.

The sender comes from the standard shapes `CQ [modifier] FROM [GRID]` and `TO FROM [GRID|report]`; anything else (free text, unresolved `<...>` hashes) gives no sender rather than a guess, and the decode still counts.

**Why Python:** your strongest language; it can import the `band-privileges` engine directly; pytest's parametrize suits the many malformed-input cases. TypeScript lost because it would mean reimplementing the privileges engine.

**Next:**
1. SQLite storage with de-duplication, and `ft8cast import`.
2. `ft8cast forecast`, then `ft8cast solar`.

### Threat model

Personal tool, local files, one optional fetch.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | A damaged or crafted log crashes the import or corrupts data (huge lengths, truncation, odd bytes) | A10 Mishandling of Exceptional Conditions | Strict parsers; problems reported, bad records skipped; nothing raises | `test_adif.py`, `test_alltxt.py` |
| T2 | Other operators' callsigns and grids get committed | none (privacy mistake, not a code flaw) | `data/`, logs and `*.sqlite` gitignored | `git check-ignore` |
| T3 | A package published on PyPI as `band-privileges` gets installed instead of the local one (dependency confusion) | A03 Software Supply Chain Failures | Installed from `../band-privileges` only; not listed in `pyproject.toml` | — |
| T4 | NOAA response is bad or spoofed | A08 Software or Data Integrity Failures | HTTPS only; values range-checked; only a warning flag, never the score | with `ft8cast solar` |

**Accepted risks:** none yet.

## Security notes

No secrets. `.env` holds only your grid square, kept out of git because it's your location. No transmit path exists.
