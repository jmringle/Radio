# FT8 Forecast

Answers "which band should I try for FT8 right now?" from your own WSJT-X/JTDX data: what you've decoded (`ALL.TXT`) and who you've worked (ADIF log), hour by hour. It only reads files; it never talks to a radio or transmits.

Status: v1 complete, plus a local web page (`ft8cast serve`). All three commands work on the author's real data (2026-10-28). Fully offline: nothing uses the network, and the web page is reachable only from this machine.

## Setup

Requires Python 3.12 or newer (CI uses 3.15). Lives next to `band-privileges` in this repo and imports it.

1. `cd ft8-forecast`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt` (also installs `../band-privileges` in editable mode)
4. `pip install -e .` (installs the `ft8cast` command into the venv)

### On Windows

Not tested on Windows yet (written 2026-10-29; CI runs on Linux, the author on macOS). The commands are PowerShell.

1. Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/windows/) and tick "Add python.exe to PATH". `py --version` checks it.
2. Get the whole `Radio` repo, not just this folder: `band-privileges` must sit next to `ft8-forecast`.
3. `cd Radio\ft8-forecast`
4. `py -m venv .venv`
5. `.venv\Scripts\Activate.ps1`. If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activating and put `.venv\Scripts\` in front of `pip` and `ft8cast` below.
6. `pip install -r requirements-dev.txt`, then `pip install -e .`
7. `copy .env.example .env`, then `notepad .env` and set `MY_GRID`.
8. `ft8cast serve` and open http://127.0.0.1:8074. It listens on `127.0.0.1` only, so Windows Firewall shouldn't ask; if it does, you can decline.

If this is the radio computer, you can import straight from WSJT-X's folder instead of copying (import only reads the file): `ft8cast import "$env:LOCALAPPDATA\WSJT-X\ALL.TXT"`, and the same for `wsjtx_log.adi`. JTDX uses `$env:LOCALAPPDATA\JTDX`. The page uses macOS fonts, so Windows shows its default fonts instead.

## Configuration

`cp .env.example .env` and set `MY_GRID` to your grid square (4, 6 or 8 characters; only the first 4 are used). `.env` is gitignored. Without it the forecast works but can't show distances; an invalid value is an error.

## Your data

Copy files from the radio computer into `data/` (gitignored, along with any `*.adi`, `*.adif`, `ALL.TXT` and `*.sqlite` anywhere in this folder: they hold other operators' callsigns and locations):
- the ADIF log (WSJT-X: File > Open log directory, `wsjtx_log.adi`);
- `ALL.TXT` from the same folder.

## Usage

```
$ ft8cast import data/ALL.TXT
ALL.TXT (ALL.TXT): 422,114 FT8 lines, 422,033 new, 81 already stored
Skipped: 514 other modes, 2,348 unknown dial frequency
Problems: 0
$ ft8cast import data/wsjtx_log.adi
wsjtx_log.adi (ADIF): 827 FT8 contacts, 827 new, 0 already stored
Skipped: 3 other modes
Problems: 0
```

The file type is detected from its content, not its name. Import as often as you like: copying a newer `ALL.TXT` over and importing again adds only the new lines. Problems are listed on stderr with line numbers (the first 10, then a count); the rest of the file still imports. The database is `data/ft8cast.sqlite`; `--db PATH` uses another one.

```
$ ft8cast forecast --hour 15
FT8 forecast for 15:00-15:59 UTC (your data: 30 days through 2026-10-25 19:48 UTC)

      ----- Stations heard -----
Band   Typical day  30-day total  Median SNR    Farthest heard  Farthest contact  30-day contacts
160m  not enough data (0 days listening; need 5)
80m   not enough data (0 days listening; need 5)
40m             24           111       -9 dB                 -                 -                1
30m   not enough data (2 days listening; need 5)
20m             96           668      -13 dB                 -                 -                8
17m   not enough data (4 days listening; need 5)
15m             30           318      -14 dB                 -                 -                3
12m   not enough data (1 day listening; need 5)
10m             12           128      -14 dB                 -                 -                1

Typical day: stations heard on the median day you listened at this hour.
30-day total: different stations heard over the whole 30 days.
Farthest heard: a station heard with the same grid square on 2+ days at this hour; the square is theirs.
Farthest contact: your farthest logged contact with a grid square at this hour; the square is theirs.

Farthest heard and contacts need your grid: set MY_GRID in .env (see .env.example).
```

With `MY_GRID` set, two more parts follow the notes, from your ADIF log (grids only, never callsigns):

```
Farthest contact ever: 4,321 mi (JN58) on 20m, 2026-08-14

Farthest contact by day (30 days, any hour):
Date        Band           Farthest
2026-10-25  15m     3,888 mi (JN58)
2026-10-23  -                     -
```

The daily list has a row for each day with contacts in the 30 days, newest first; `-` means none of that day's contacts logged a grid. It ignores `--hour`, since each row is a whole day. The all-time line counts every imported contact.

Without `--hour` it uses the current UTC hour; `--hour all` counts the whole day instead of one hour (on the page: "All hours" in the hour list). The 30 days end at your newest imported decode, not today, so an older copy of `ALL.TXT` still gives a full window; if that's more than 7 days ago, a note says to copy a fresh one over.

### The web page

```
$ ft8cast serve
FT8 forecast page: http://127.0.0.1:8074  (Ctrl+C stops it)
```

Open that address in your browser. The page shows the same forecast as `ft8cast forecast` (pick the UTC hour from the list) and has an upload form for `ALL.TXT` or ADIF that works like `ft8cast import`: the summary and the first 10 problems show on the page. Uploads go into the same database the commands use; the uploaded file isn't kept. `--port N` (1024-65535) picks another port, `--db PATH` another database. Werkzeug prints a "development server" warning at start; that's expected here, since it only serves you, on this machine (see the threat model).

Exit codes: `0` imported or forecast shown (for `serve`: stopped with Ctrl+C), `2` bad input (missing or unreadable file, no FT8 records in it, a database that isn't ft8cast's, no database or no `ALL.TXT` data yet for a forecast, an invalid `MY_GRID`, usage errors such as `--hour 24` or `--port 80`; for `serve`, the port already in use).

## Running tests

`pytest` from `ft8-forecast/` runs everything. No network, no radio, no real logs, no real server (the web page is tested through Flask's test client): tests build made-up ADIF records and `ALL.TXT` lines (in the real file's exact layout) with `N0CALL`. CI runs the same command on every push that touches this folder or `band-privileges`, then `pip-audit`.

## Design notes

**Data (decided 2026-10-28):** your own data only. The forecast comes from `ALL.TXT` and ADIF, nothing else.

**No web calls (decided 2026-10-28):** the tool never uses the network (a test fails if anything tries to connect). A NOAA solar-conditions flag (K-index, F10.7) was planned and dropped for this reason; if it's ever wanted, the offline way is typing the values in by hand. PSKReporter (who heard *you*) is out for the same reason, since it can only be fetched.

**Web page (decided 2026-10-28):** Flask, because it parses uploads, enforces a size limit and escapes HTML, and is mature; Python's built-in server lost because Python 3.13 removed the standard library's upload parser, so that would mean hand-written parsing of outside input. Phase 2, if wanted, is a standalone app; a local Flask app can be wrapped in a native window later (e.g. pywebview), so nothing here needs to change for it.

**Acceptance criteria** (settled 2026-10-28). Every command is manual; nothing runs on a schedule.
- `ft8cast import <file>`: reads an `ALL.TXT` or ADIF file into a local SQLite database (`data/`, gitignored). Re-importing the same file doesn't duplicate. Never modifies the source file. Bad lines are skipped and reported with line numbers; a file with no valid lines is an error.
- `ft8cast forecast [--hour HH|all]`: per band, for the current UTC hour, the one given, or all hours (added 2026-10-28: the same rules with no hour limit, so a listening day is a day with any line on that band, and Farthest heard's 2 days can be at different hours):
  - **stations per day**, shown as "Typical day" under "Stations heard" (renamed 2026-10-28, with "30-day total" for distinct stations, so the two read differently; changed 2026-10-28; replaced "open on X of Y days"): the median number of distinct stations decoded per listening day at that hour. A listening day is any day `ALL.TXT` shows you on that band at that hour (a decode or your own Tx); a day with only your Tx counts as 0. Window: the last 30 days.
  - distinct stations heard, median SNR, farthest station heard with its grid square (messages often carry the sender's grid). Farthest heard counts a station only if it was decoded with the same grid on 2+ days at that hour on that band (decided 2026-10-28);
  - confirmed contacts from ADIF, shown separately (proven two-way paths).
  - **Farthest contact** (added 2026-10-29): the farthest ADIF contact with a logged grid, on that band at that hour in the window, as miles and the other station's square; `-` without one or without `MY_GRID`. No 2-day rule. Under the table: **Farthest contact ever** (every imported contact, any hour or date, with band and date) and **Farthest contact by day** (one row per day with contacts in the window, any hour, newest first; `-` for a day with no logged grid). Ties go to the earlier contact. Only bands with General data privileges count. No callsigns are shown. Both parts are left out without `MY_GRID`.
  - Fewer than 5 listening days on a band at that hour: "not enough data", never a score.
  - Only bands where General may operate data, via `band-privileges`.
- `ft8cast serve [--port N]` (added 2026-10-28): a web page on `127.0.0.1` only, default port 8074.
  - Shows the forecast for the current UTC hour, or one picked from a list that also has "All hours"; a bad hour is a 400 with the reason.
  - Uploading `ALL.TXT` or ADIF imports it exactly like `ft8cast import` (same detection, de-duplication and problem reporting) and shows the summary; the file isn't kept. No file, a file with no FT8 records, or an ADIF over 100 MB is a 400 that stores nothing; an upload over 500 MB is a 413.
  - No database yet: the page says to upload, and creates nothing until you do. A database that isn't ft8cast's, or an invalid `MY_GRID`, shows the reason (500) and changes nothing.
  - Unexpected errors show "Something went wrong; see the terminal" and never a traceback; debug mode can't be switched on (not even by `FLASK_DEBUG`).
  - Refuses requests not addressed to `127.0.0.1` or `localhost` (400) and uploads not sent from its own page (403). No JavaScript; nothing loaded from other sites.

**ADIF parser** (`src/ft8_forecast/adif.py`): follows ADIF 3.1.6 section IV.A ([adif.org](https://adif.org/316/ADIF_316.htm), checked 2026-10-28). Each field's length decides where its data ends, so a comment containing `<EOR>` can't break a record. Only FT8 contacts are kept; other modes are counted, not reported as errors. A bad grid costs the distance, not the contact. Frequencies parse with `band-privileges`' `mhz()`, so both projects accept exactly the same numbers. An empty `<gridsquare:0>` (WSJT-X's "unknown") is the same as no grid.

**`ALL.TXT` parser** (`src/ft8_forecast/alltxt.py`): the format isn't formally documented, so the rules come from surveying the author's real file (424,976 lines, 2025-12 to 2026-10). Every line is `YYMMDD_HHMMSS  dial-MHz  Rx|Tx  mode  SNR  DT  audio-Hz  message`. What the survey found and how it's handled:
- dial `0.000` (WSJT-X didn't know the frequency; 19 days): band unknown, so counted and skipped, never guessed;
- `Tx` lines are your own transmissions: kept, marked `transmit`, as proof you were on the band, never counted as stations heard;
- FT4 and other modes: counted and skipped;
- trailing `a1`-`a9` tags (WSJT-X "a priori" decodes): dropped before reading the message;
- `RR73` has a grid's shape but is the sign-off: never a grid;
- lines aren't strictly in time order (late decode passes, up to 60 s back): nothing assumes order.

The sender comes from the standard shapes `CQ [modifier] FROM [GRID]` and `TO FROM [GRID|report]`; anything else (free text, unresolved `<...>` hashes) gives no sender rather than a guess, and the decode still counts.

**Storage** (`src/ft8_forecast/store.py`): one SQLite file, schema version in `PRAGMA user_version`; a file that isn't an ft8cast database (or has another version) is refused and left untouched. A decode's identity is time + dial + Rx/Tx + SNR + message, so the same line imported twice is stored once. The author's file had 81 repeats: 79 identical lines and 2 that differ only in timing/audio offset (the same signal decoded twice). A contact's identity is time + frequency + call. Each import is one transaction: an error part-way stores nothing. All queries are parameterized, so free text from other stations can't act as SQL.

**Forecast** (`src/ft8_forecast/forecast.py`), decided 2026-10-28:
- Window: the 30 days up to the newest imported decode (option b), exclusive at the far end.
- Distances in **miles** (the author's choice), great-circle between the centers of 4-character squares. A square is about 140 x 70 miles in the US, so distances are good to roughly +/- 70 miles.
- Bands: every v1 band from `band-privileges` (60 m is deferred there), each with General data privileges at its FT8 frequency (tested). A decode counts only if General may use data at its dial frequency (`check(dial, DATA, GENERAL)`); band edges here are cross-checked against `band-privileges` by a test.
- Median SNR rather than the mean, so one loud local station doesn't skew it.
- **Why Farthest heard needs 2 days:** it's a single maximum, so one bad grid sets it. In the author's data (checked 2026-10-28) the old rule's 18 UTC 20 m farthest was an Antarctic square from 2 decodes on one day, one of them an a-priori decode, and 15 UTC 40 m was a square near the North Pole from a station that likely has its grid set wrong. Requiring the same station *and* grid on 2+ days drops one-day flukes and garbled grids; showing the square lets you spot a wrong one that repeats.
- **Why Farthest contact has no 2-day rule:** the rule guards against false decodes, but a logged contact is a completed two-way exchange, and its grid came from that exchange. A grid you mistyped while logging would still show; the square is shown so you can spot it.
- **Why stations per day, not "open X of Y days":** `ALL.TXT` only records something when a line is decoded or you transmit, so a day on a dead band without transmitting leaves no trace and can't count as closed. In the author's data only 1 of 30 scored band-hours showed fewer open days than listening days, so that column nearly always read "X of X". The median day tells how busy the band typically is, and one unusually good day can't lift it. The same blind spot remains: silent, Rx-only days on a dead band are invisible, so the number leans optimistic.

**Why Python:** your strongest language; it can import the `band-privileges` engine directly; pytest's parametrize suits the many malformed-input cases. TypeScript lost because it would mean reimplementing the privileges engine.

**Next:**
- Phase 2, if wanted: a standalone app (a native window around the same page).
- Possible later: a 24-hour overview (band by hour) on the page; solar values typed in by hand (`--k`, `--flux`; no network).

### Threat model

Personal tool, local files only, no network. `serve` adds a local web server, so T5-T9 cover it.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | A damaged or crafted log crashes the import or corrupts data (huge lengths, truncation, odd bytes) | A10 Mishandling of Exceptional Conditions | Strict parsers; problems reported, bad records skipped; nothing raises | `test_adif.py`, `test_alltxt.py` |
| T2 | Other operators' callsigns and grids get committed | none (privacy mistake, not a code flaw) | `data/`, logs and `*.sqlite` gitignored | `git check-ignore` |
| T3 | A package published on PyPI as `band-privileges` gets installed instead of the local one (dependency confusion) | A03 Software Supply Chain Failures | Installed from `../band-privileges` only; not listed in `pyproject.toml` | — |
| T4 | Text in a log (free-text messages come from anyone on the air) runs as SQL | A05 Injection | Parameterized queries only | `test_store.py` |
| T5 | Another computer on your Wi-Fi opens the page or uploads to it | A01 Broken Access Control | Binds to `127.0.0.1` only (`lsof` on the running server shows `127.0.0.1:8074`) | `test_serve_listens_only_on_this_machine_with_debug_off` |
| T6 | A website open in your browser posts a file to the server (CSRF, cross-site request forgery) to plant fake data | A01 Broken Access Control | Uploads must carry this page's exact `Origin`; browsers always send it on a POST and pages can't fake it | `test_upload_from_any_other_origin_is_refused` |
| T7 | DNS rebinding: an attacker's domain is pointed at 127.0.0.1, so their page counts as "same site" and can read yours | A01 Broken Access Control | Only `Host: 127.0.0.1` or `localhost` is answered | `test_other_host_names_are_refused` |
| T8 | A crafted `ALL.TXT` line or file name, echoed in the problem list, runs as script in the page (XSS, cross-site scripting) | A05 Injection | Jinja auto-escaping; CSP with no `script-src`, so even injected script wouldn't run; names cut to 80 characters | `test_on_air_text_and_file_names_are_escaped`, `test_security_headers_on_every_response` |
| T9 | Werkzeug's debugger gets switched on: its in-browser console runs any Python typed into it | A02 Security Misconfiguration | `debug=False` and no `.env` loading, so `FLASK_DEBUG` is ignored; errors show no traceback | `test_serve_listens_only_on_this_machine_with_debug_off`, `test_errors_show_no_traceback` |

**Accepted risks:** a huge garbage file passed to `import` would collect one problem per line in memory. It's a personal tool reading your own files, so there's no cap beyond ADIF's 100 MB (and 500 MB for uploads). Werkzeug's development server is used rather than a production server (one more dependency): it serves one person on one machine, and T5-T9 cover what a production server wouldn't add. Mutation-checked 2026-10-28: removing each control above makes a test fail.

## Security notes

No secrets. `.env` holds only your grid square, kept out of git because it's your location. No transmit path exists.
