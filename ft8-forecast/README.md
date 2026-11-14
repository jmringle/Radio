# FT8 Forecast

Answers "which band should I try for FT8 right now?" from your own WSJT-X/JTDX data: what you've decoded (`ALL.TXT`) and who you've worked (ADIF log), hour by hour. It only reads files; it never talks to a radio or transmits.

Status: v1 complete, plus a local web page (`ft8cast serve`). All three commands work on the author's real data (2026-10-28). Fully offline: nothing uses the network, and the web page is reachable only from this machine.

## Setup

Requires Python 3.12 or newer (CI uses 3.15). Lives next to `band-privileges` in this repo and imports it.

1. `cd ft8-forecast`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt` (also installs `../band-privileges` in editable mode), then `playwright install chromium` (the browser tests' Chromium, about 150 MB; only needed to run the tests)
4. `pip install -e .` (installs the `ft8cast` command into the venv)

### On Windows

The tests run on Windows in CI (since 2026-10-30), but nobody has used the app on Windows by hand yet; the author uses macOS. The commands are PowerShell.

1. Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/windows/) and tick "Add python.exe to PATH". `py --version` checks it.
2. Get the whole `Radio` repo, not just this folder: `band-privileges` must sit next to `ft8-forecast`.
3. `cd Radio\ft8-forecast`
4. `py -m venv .venv`
5. `.venv\Scripts\Activate.ps1`. If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activating and put `.venv\Scripts\` in front of `pip` and `ft8cast` below.
6. `pip install -r requirements-dev.txt`, then `pip install -e .` (and `playwright install chromium` to run the tests)
7. `copy .env.example .env`, then `notepad .env` and set `MY_GRID`.
8. `ft8cast serve` and open http://127.0.0.1:8074. It listens on `127.0.0.1` only, so Windows Firewall shouldn't ask; if it does, you can decline.

If this is the radio computer, you can import straight from WSJT-X's folder instead of copying (import only reads the file): `ft8cast import "$env:LOCALAPPDATA\WSJT-X\ALL.TXT"`, and the same for `wsjtx_log.adi`. JTDX uses `$env:LOCALAPPDATA\JTDX`. The page uses macOS fonts, so Windows shows its default fonts instead.

## Configuration

`cp .env.example .env` and set `MY_GRID` to your grid square (4, 6 or 8 characters; only the first 4 are used). `.env` is gitignored. Without it the forecast works but can't show distances; an invalid value is an error.

Optional: `LOG_DIR` is the folder holding your `ALL.TXT` and `wsjtx_log.adi`, so you don't have to copy them (see [Importing from a folder](#importing-from-a-folder)). `~` works, and a relative path is relative to `.env`.

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

### Importing from a folder

Instead of copying files into `data/`, point at the folder WSJT-X writes to:

```
$ ft8cast import --dir "/Volumes/WSJT-X"      # or set LOG_DIR in .env and run: ft8cast import
ALL.TXT (ALL.TXT): 422,114 FT8 lines, 1,203 new, 420,911 already stored
...
wsjtx_log.adi (ADIF): 827 FT8 contacts, 2 new, 825 already stored
...
$ ft8cast watch                               # LOG_DIR, or --dir PATH
Watching /Volumes/WSJT-X every 60 s; Ctrl+C stops.
16:42 UTC  ALL.TXT: 37 new
16:43 UTC  ALL.TXT: 41 new
^C
Stopped.
```

- `import` with a folder reads `ALL.TXT` and every `.adi`/`.adif` directly in it (not subfolders), one summary each. Symlinks are skipped, and the folder is never written to. One bad file is reported and the rest still import (exit code 2).
- `watch` imports everything once, then checks every 60 seconds (`--every 10` to `3600`) and imports only what changed: the new complete lines of `ALL.TXT` (a line WSJT-X is still writing waits for the next check), or a changed `.adi` whole. It prints only when something new arrives. It runs only while you leave it running: no background service, nothing at login. If the folder goes away (a share coming unmounted), it says so once and keeps checking. It checks by polling rather than waiting for macOS change alerts, because those often don't arrive for network shares.
- On the web page, **Import from folder** (shown when `LOG_DIR` is set) does what `ft8cast import` with no file does. The page never takes a folder from the browser, only `LOG_DIR`.

**WSJT-X on another computer:** in WSJT-X, File > Open log directory shows the folder. Share it on that computer, read-only if you can (this tool never writes to it), then on the Mac use Finder > Go > Connect to Server to mount it; it appears under `/Volumes/`, and that path goes in `LOG_DIR`. Copying the files over and pointing `LOG_DIR` at the copy works too.

The file type is detected from its content, not its name. Import as often as you like: copying a newer `ALL.TXT` over and importing again adds only the new lines. Problems are listed on stderr with line numbers (the first 10, then a count); the rest of the file still imports. The database is `data/ft8cast.sqlite`; `--db PATH` uses another one.

```
$ ft8cast forecast --hour 16
FT8 forecast for 16:00-16:59 UTC, 12 pm EDT (your last 30 days, through 2026-10-25 19:48 UTC, 4 days ago)

Best bet (busiest): 20m - about 50 stations on a typical day; worked out to 1,739 mi
Next: 15m - about 45 stations on a typical day
20m is busiest at 15 UTC (11 am EDT): about 96 stations on a typical day
Farthest contact at this hour: 5,306 mi on 10m
Busier in the last 15 days: 10m (24 a day, up from 12)

      Stations  Stations  Median   Farthest   Farthest  Contacts
Band   per day   30 days  SNR dB      heard     worked   30 days
20m         50       573     -13   4,884 mi   1,739 mi        11
15m         45       460     -15   5,155 mi   1,629 mi         5
10m         18       234     -14   8,499 mi   5,306 mi         6
40m          5        23     -10     737 mi     125 mi         1

Replies to you            Calling CQ         Answering CQs
20m                   12 of 197 (6%)          3 of 35 (9%)
15m                    2 of 133 (2%)          2 of 22 (9%)
10m                     1 of 42 (2%)         2 of 16 (12%)
40m                    6 of 43 (14%)           0 of 6 (0%)

Too little data at this hour (need 5 days): 160m 80m 12m (0 days), 17m (1 day), 30m (3 days)

Column notes and farthest contacts: add --details
Every hour at a glance: ft8cast overview
```

The **Best bet** line answers "which band now?". `--rank busiest` (the default) picks the band with the most stations on a typical day; `--rank contacts` picks the one where you've completed the most contacts. The table follows the same order, best first; a tie goes to the other measure, then the lower band. When no band qualifies, the line says why instead of guessing. Bands with fewer than 5 days of listening share one line under the table, grouped by days. Distances are miles only here; the web page adds each grid square.

`--details` (added 2026-11-07) adds what each column means, then two parts from your ADIF log (never callsigns). They don't help pick a band, so the default leaves them out; on the page they're the collapsed "Column notes" and "Farthest contacts" sections.

```
Stations per day: the median (middle value) over the days you listened.
Median SNR: middle signal-to-noise ratio of all decodes; higher is stronger.
Farthest heard: same station and grid on 2+ days.
Replies to you: a decode addressed to you within 30 s.
Answering CQs: you calling a station (usually answering its CQ).

Farthest contact ever: 4,321 mi on 20m, 2026-08-14

Farthest contact by day (30 days, any hour):
Date        Band  Farthest
2026-10-25  15m   3,888 mi
2026-10-23  -            -
```

The daily list has a row for each day with contacts in the 30 days, newest first; `-` means none of that day's contacts logged a grid. It ignores `--hour`, since each row is a whole day. The all-time line counts every imported contact. Without `MY_GRID` in `.env`, the distances are `-` and these two parts are left out.

**Local times** (added 2026-10-29) appear next to UTC: in the forecast heading, the summary's peak line, the overview's Local column and hour lines ("00-09 UTC (8 pm-5 am EDT)"), and the page's hour list ("17:00 (1 pm, now)"). They come from this computer's time zone at today's offset, so after a daylight-saving change the same UTC hour shows the new local time; the data stays in UTC, as WSJT-X logs it. On a computer set to UTC they're left out.

Without `--hour` it uses the current UTC hour; `--hour all` counts the whole day instead of one hour (on the page: "All hours" in the hour list). The 30 days end at your newest imported decode or contact, whichever is later, not today: an older copy of `ALL.TXT` still gives a full window, and a fresher `wsjtx_log.adi` still counts (a contact dated in the future, from a wrong clock on the radio computer, is ignored for this); if that's more than 7 calendar days ago (UTC, the same count as the heading's "13 days ago"), a note says to copy a fresh one over.

```
$ ft8cast overview
24-hour overview (your last 30 days, through 2026-10-25 19:48 UTC, 4 days ago)
Typical-day stations; * = best bet (busiest); . = too little data; Local = EDT

UTC Local   40m    20m    15m    10m
10   6 am    32*     .      .      .
11   7 am   109*     .      .      .
12   8 am   144*    24      3      .
13   9 am    90*    25     18      .
14  10 am    31     53*    37      9
15  11 am    24     96*    30     12
16  12 pm     5     50*    45     18
17   1 pm     5     65*    46     17
18   2 pm     4     70*    43     16
19   3 pm     .     75*     .     18

Too little data on every band: 20-23 UTC (4 pm-7 pm EDT)
Hours with no listening: 00-09 UTC (8 pm-5 am EDT)
Too little data at every hour: 160m 80m 30m 17m 12m
```

`ft8cast overview [--rank busiest|contacts]` puts every UTC hour side by side: each cell is that band's typical-day stations at that hour (exactly what `ft8cast forecast --hour HH` shows), `.` where there are fewer than 5 days of listening, and `*` on the hour's best bet. Rows and columns that would be all dots are left out and summed up underneath instead: hours you listened with too little data on every band, hours with no listening, and bands with too little data at every hour. On the web page the same table comes right after the forecast (before Farthest contacts), the hour on show is outlined, and each hour links to its forecast.

### The web page

```
$ ft8cast serve
FT8 forecast page: http://127.0.0.1:8074  (Ctrl+C stops it)
```

Open that address in your browser. The page shows the same forecast as `ft8cast forecast` (pick the UTC hour from the list) and has an upload form for `ALL.TXT` or ADIF that works like `ft8cast import`: the summary and the first 10 problems show on the page. Uploads go into the same database the commands use; the uploaded file isn't kept. `--port N` (1024-65535) picks another port, `--db PATH` another database. Werkzeug prints a "development server" warning at start; that's expected here, since it only serves you, on this machine (see the threat model).

Exit codes: `0` imported or forecast shown (for `serve`: stopped with Ctrl+C), `2` bad input (missing or unreadable file, no FT8 records in it, a database that isn't ft8cast's, no database or no `ALL.TXT` data yet for a forecast, an invalid `MY_GRID`, usage errors such as `--hour 24` or `--port 80`; for `serve`, the port already in use).

### The standalone app

A double-clickable app for macOS and Windows: the same page in its own window, with no terminal or Python needed. It keeps its database, settings and error log in `~/Library/Application Support/FT8 Forecast` (macOS) or `%APPDATA%\FT8 Forecast` (Windows), separate from `data/` and `.env`, so importing into one doesn't change the other. Set your grid and log folder under **Settings** on the page. Each time it opens with saved data it first asks for your latest log (import a file or press **Import from folder**), or press **Use saved data** to see the forecast from what you imported before.

To build it on the system you want it for:

```sh
pip install -r requirements-app.txt
pyinstaller --noconfirm packaging/ft8forecast.spec
python packaging/check_build.py dist          # fails if a log, database or .env got in
"dist/FT8 Forecast.app/Contents/MacOS/FT8 Forecast" --self-test   # macOS; exit 0 means it works
```

To run it from source without building: `python -m ft8_forecast.desktop`.

**Downloading a build.** Ready-made builds are on the [Releases](https://github.com/jmringle/Radio/releases) page (the first, `ft8-forecast-v0.1.0-beta.1`, is a pre-release). They aren't code-signed yet, so the computer can't confirm who made them and warns once:

- **macOS:** the first open is blocked. Go to System Settings → Privacy & Security, scroll down, click **Open Anyway** next to FT8 Forecast and confirm. (Right-click → Open no longer skips this on macOS 15 and later.)
- **Windows:** SmartScreen says "Windows protected your PC". Click **More info → Run anyway**.

To check a download wasn't altered, compare it with the release's `SHA256SUMS.txt`: `shasum -a 256 -c --ignore-missing SHA256SUMS.txt` in the download folder (macOS; it skips the file you didn't download), or `Get-FileHash <file>` (Windows PowerShell; it prints the hash in capitals). CI writes each build's `.sha256` in this same standard format and checks it reads before uploading.

## Running tests

`pytest` from `ft8-forecast/` runs everything. No network beyond 127.0.0.1, no radio, no real logs. The web page is tested two ways: `test_web.py` checks the HTML through Flask's test client; `test_browser.py` (added 2026-10-29) runs the real server on a free local port and drives headless Chromium with Playwright, for what only a browser can show: the table scrolling in its own box on a phone, the scroll hint appearing whenever the table overflows, dark mode, the hour form, the CSP blocking an injected script, and the Importing… indicator (shown, buttons disabled, a file name with HTML in it shown as text, the import still going through). Either way tests build made-up ADIF records and `ALL.TXT` lines (in the real file's exact layout) with `N0CALL`. CI runs the same command on Linux and Windows (Windows added 2026-10-30) on every push that touches this folder or `band-privileges`, then `pip-audit`. Local times are pinned to US Eastern through `cli._local_zone` (`tests/conftest.py`), so tests read the same in any time zone; `tzdata` supplies the zone on Windows. A few tests skip on Windows, each with its reason: unreadable-file tests (Windows ignores `chmod`'s read bits) and the port-in-use test (needs `SIGALRM`). Unverified: whether a second `ft8cast serve` on Windows is refused a port already in use, as on macOS and Linux.

## Design notes

**Data (decided 2026-10-28):** your own data only. The forecast comes from `ALL.TXT` and ADIF, nothing else.

**No web calls (decided 2026-10-28):** the tool never uses the network (a test fails if anything tries to connect). A NOAA solar-conditions flag (K-index, F10.7) was planned and dropped for this reason; if it's ever wanted, the offline way is typing the values in by hand. PSKReporter (who heard *you*) is out for the same reason, since it can only be fetched. Answered (2026-10-29) is the offline stand-in: replies addressed to you in your own `ALL.TXT`.

**Web page (decided 2026-10-28):** Flask, because it parses uploads, enforces a size limit and escapes HTML, and is mature; Python's built-in server lost because Python 3.13 removed the standard library's upload parser, so that would mean hand-written parsing of outside input. Phase 2, if wanted, is a standalone app; a local Flask app can be wrapped in a native window later (e.g. pywebview), so nothing here needs to change for it.

**Acceptance criteria** (settled 2026-10-28). Every command is manual; nothing runs on a schedule.
- `ft8cast import <file>`: reads an `ALL.TXT` or ADIF file into a local SQLite database (`data/`, gitignored). Re-importing the same file doesn't duplicate. Never modifies the source file. Bad lines are skipped and reported with line numbers; a file with no valid lines is an error.
- `ft8cast forecast [--hour HH|all] [--rank busiest|contacts] [--details]`: per band, for the current UTC hour, the one given, or all hours (added 2026-10-28: the same rules with no hour limit, so a listening day is a day with any line on that band, and Farthest heard's 2 days can be at different hours):
  - **stations per day**, shown as "Stations per day" (replaced "open on X of Y days" 2026-10-28): the median number of distinct stations decoded per listening day at that hour. A listening day is any day `ALL.TXT` shows you on that band at that hour (a decode or your own Tx); a day with only your Tx counts as 0. Window: the last 30 days.
  - distinct stations heard ("Stations 30 days"), median SNR ("Signal dB SNR"), farthest station heard with its grid square ("Farthest heard"; messages often carry the sender's grid). It counts a station only if it was decoded with the same grid on 2+ days at that hour on that band (decided 2026-10-28);
  - confirmed contacts from ADIF, shown separately (proven two-way paths).
  - **Farthest contact** ("Farthest worked", added 2026-10-29): the farthest ADIF contact with a logged grid, on that band at that hour in the window, as miles and the other station's square; `-` without one or without `MY_GRID`. No 2-day rule. Under the table: **Farthest contact ever** (every imported contact, any hour or date, with band and date) and **Farthest contact by day** (one row per day with contacts in the window, any hour, newest first; `-` for a day with no logged grid). Ties go to the earlier contact. Only bands with General data privileges count. No callsigns are shown. Both parts are left out without `MY_GRID`.
  - **Answered** (added 2026-10-29; its own table under the forecast table since 2026-10-30): per band in the table, your opening calls on that band at that hour, titled "Replies to you" and split into **Calling CQ** (a Tx line starting `CQ`) and **Answering CQs** (renamed from "Your CQs"/"Your calls" 2026-10-30; a Tx line carrying your grid, i.e. calling a station, usually in answer to its CQ; reports and sign-offs don't count), and how many of each were followed within 30 s by a decode addressed to you on the same band (`12 of 197 (6%)`; `-` with none). Left out, with its legend line, when you didn't transmit. At 20 W, calling a station often beats calling CQ; the split shows whether it does for you, and since 2026-11-07 a summary line says so outright ("Answering CQs got more replies than calling CQ: 20m (24% vs 9%)", bands in table order; or the other way round) for each band where the gap is unlikely to be chance: Fisher's exact test, p < 0.05 (`REPLY_P`), with both counts above 0. A test rather than a minimum count, because in the author's data 3 of 22 vs 0 of 25 has over 20 tries each yet could easily be luck (p = 0.09). No line when no band qualifies. WSJT-X stamps each line with its 15 s cycle's start, so a reply in the next cycle is 15 s later; in the author's file 1,171 of 11,448 CQs had a reply at exactly 15 s, about 60 a few seconds off, and 573 at 45 s, which belong to the next CQ. "You" is every sender of your own Tx lines (so /P counts). A reply just past the hour still counts. No callsigns are shown.
  - Fewer than 5 listening days on a band at that hour: "not enough data", never a score; these bands share one line ("Too little data"), grouped by days listened.
  - **Best bet** (added 2026-10-29): one line above the table naming the top band by `--rank`: `busiest` (default; stations per day, then contacts) or `contacts` (contacts, then stations per day); a full tie goes to the lower band. The table lists only bands with enough data, in that order. No band with enough data, or none scoring above 0: the line says "none" and why. No listening at all at that hour: one sentence, no table, no legend.
  - **Details** (added 2026-11-07): by default the output stops after the "too little data" line with two hints (`--details`, `ft8cast overview`); the `--details` hint only appears when something was left out. `--details` adds the column notes and both farthest-contact parts. On the page they start collapsed (`<details>`, no JavaScript). The heading and the stale note count the data's age the same way, in UTC calendar days.
  - **Summary** (added 2026-10-29): lines under the best bet, here and on the page. First, when the forecast is for the hour it is now, **Later** (added 2026-11-12): the best bet for each of the next two hours by the same ranking, "Later: 14 UTC (9 am EST) 20m, 15 UTC (10 am EST) none" ("none": under 5 days of data or nothing to rank; wraps past 00 UTC; left out when both are none, and shown even when this hour has no best bet). The next three use only numbers already shown: "Next:" the second-ranked band (if it scores above 0); when the best band peaks by the same ranking ("20m is busiest at 15 UTC: ...", or "This is 20m's busiest hour"; ties go to the earlier hour; left out for all hours); and the farthest contact at this hour (or in the 30 days for all hours; needs `MY_GRID`). Then **trend** lines (added 2026-10-29): "Busier in the last 15 days: 15m (45 a day, up from 30)" and "Quieter …", comparing stations per day in the window's last 15 days with the 15 before, for bands in the table. A band is listed only if each half has 3+ listening days and the change is at least 25% of the earlier figure and at least 2 stations a day. Caveat: stations per day also rises if you listened longer within the hour, and the tool can't tell that from the band opening up. Only the Later line without a best bet.
  - Ends with a pointer to `ft8cast overview` (2026-10-29), so the overview is easy to find.
  - The header says how old the newest data is in calendar days ("today", "yesterday", "4 days ago"; 2026-10-29), here, in `overview` and on the page; the >7-day note stays.
  - Column names (two-line headers, 2026-10-29): Stations per day, Stations 30 days, Median SNR dB (the median of every decode's SNR; renamed from "Signal" 2026-10-30), Farthest heard, Farthest worked, Contacts 30 days. The second line carries the unit or time span, so cells are bare numbers (SNR without "dB"). Two lines let plain words fit 80 columns (the table is 64 wide). The terminal shows miles only; the page puts each grid on a line under its distance, so the widest real table fits a computer screen without scrolling.
  - Terminal lines over 80 characters (2026-10-30) break after a comma or semicolon between items, never inside brackets, with the rest indented 2: "Busier in the last 15 days: 20m (104 a day, up from 70)," then "  15m (…)".
  - Only bands where General may operate data, via `band-privileges`.
- `ft8cast overview [--rank busiest|contacts]` (added 2026-10-29): one row per UTC hour with any listening, one column per band; a cell is the typical-day stations (as `forecast --hour HH` computes them) or `.` below 5 listening days; `*` marks the hour's best bet by the same rule (no star when there's none). Hours with no listening are listed as ranges (`00-09, 22-23`). Changed 2026-10-29: hours with too little data on every band, and bands with too little data at every hour, get no row or column, only a line each under the grid; with no band ready at any hour, one sentence instead of a grid. Same header, stale note and errors as `forecast`.
- `ft8cast import [FILE] [--dir PATH]` from a folder (added 2026-10-29): with `--dir`, or with no file and `LOG_DIR` set in `.env`, imports `ALL.TXT` and `*.adi`/`*.adif` directly in the folder (names in any case; content still decides the type). Symlinks, subfolders and other files are skipped; the folder is never written. A missing folder or one with no logs is an error that stores nothing. One summary per file; a bad file is reported and the rest import; exit 2 if any file failed. A file and `--dir` together, or neither with no `LOG_DIR`, is an error saying what to do.
- `ft8cast watch [--dir PATH] [--every SECONDS]` (added 2026-10-29): user-started, runs until Ctrl+C ("Stopped.", exit 0). Imports the folder, then every `--every` seconds (default 60, allowed 10-3600) re-reads files whose inode, size or modified time changed: for `ALL.TXT` only the complete lines after the last read (a half-written line waits; a smaller or replaced file is read from the start), for ADIF the whole file. New files are picked up, deleted ones forgotten. Prints `HH:MM UTC  name: N new` and problems (with the file's line numbers) only when something happens. Folder missing at start: error. Folder unreachable later: one message, keeps checking, says when it's back. A file it can't read: a message, tried again next check. An ADIF with no FT8 records or over 100 MB: reported once until it changes.
- `ft8cast serve [--port N]` (added 2026-10-28): a web page on `127.0.0.1` only, default port 8074.
  - Shows the forecast for the current UTC hour, or one picked from a list that also has "All hours"; a bad hour is a 400 with the reason. An "Import from folder" button (only with `LOG_DIR` set) imports like `ft8cast import` with no file, one summary per file; the folder comes only from `LOG_DIR`, never the request. No `LOG_DIR` or a missing folder is a 400 that stores nothing; it needs the same Origin as uploads. A "Best bet by" list does what `--rank` does; a bad value is a 400. The hour list marks the current UTC hour "(now)". The browser tab title carries the hour and best bet ("FT8 forecast · 16:00 UTC · best bet 20m"). With no data yet, the hour and "Best bet by" lists are hidden and the page says what to import (ALL.TXT, plus the ADIF log for contacts) and how to import from a folder. Native controls follow dark mode (`color-scheme`). Import results are one block per file: counts, then a muted line with what was skipped and "No problems" or the problem count; "(read as …)" only when the content's type isn't what the name suggests. On screens narrower than the forecast table (44rem), it scrolls in its own box with "Scroll the table sideways for more" under it; the page itself never scrolls sideways. Below it, the 24-hour overview (added 2026-10-29), following "Best bet by", each hour linking to its forecast.
  - Uploading `ALL.TXT` or ADIF imports it exactly like `ft8cast import` (same detection, de-duplication and problem reporting) and shows the summary; the file isn't kept. No file, a file with no FT8 records, or an ADIF over 100 MB is a 400 that stores nothing; an upload over 500 MB is a 413.
  - No database yet: the page says to upload, and creates nothing until you do. A database that isn't ft8cast's, or an invalid `MY_GRID`, shows the reason (500) and changes nothing.
  - Unexpected errors show "Something went wrong; see the terminal" and never a traceback; debug mode can't be switched on (not even by `FLASK_DEBUG`).
  - Refuses requests not addressed to `127.0.0.1` or `localhost` (400) and uploads not sent from its own page (403). Nothing loaded from other sites. One script (added 2026-11-13, the user's choice, since the app's window has no browser spinner): `static/busy.js`, served by this server, shows "Importing ALL.TXT… a big file takes a few seconds." (or the folder / saved-data version) while a form posts and disables the buttons so it can't be sent twice; it sends and fetches nothing, and the forms work the same without it. The CSP allows scripts only from this server (`script-src 'self'`), never inline ones.
  - **Speed** (added 2026-11-13): the 24 hourly results behind the overview, summary and Later line are kept in memory until the data (newest row numbers, so imports from `ft8cast import` and `watch` count too), the UTC hour or the grid changes; switching hour or ranking then takes about 1 ms instead of about 1 s on two months of listening. All hours is worked out only when picked. Reading `ALL.TXT` builds timestamps from their digits and remembers dial conversions (28 MB: 2.9 s to 1.5 s).

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
- Window: the 30 days up to the newest imported decode (option b), exclusive at the far end. Changed 2026-10-29: up to the newest decode or contact, whichever is later, so contacts logged after the newest ALL.TXT line count; contacts dated after now don't move it.
- Distances in **miles** (the author's choice), great-circle between the centers of 4-character squares. A square is about 140 x 70 miles in the US, so distances are good to roughly +/- 70 miles.
- Bands: every v1 band from `band-privileges` (60 m is deferred there), each with General data privileges at its FT8 frequency (tested). A decode counts only if General may use data at its dial frequency (`check(dial, DATA, GENERAL)`); band edges here are cross-checked against `band-privileges` by a test.
- Median SNR rather than the mean, so one loud local station doesn't skew it.
- **Why Farthest heard needs 2 days:** it's a single maximum, so one bad grid sets it. In the author's data (checked 2026-10-28) the old rule's 18 UTC 20 m farthest was an Antarctic square from 2 decodes on one day, one of them an a-priori decode, and 15 UTC 40 m was a square near the North Pole from a station that likely has its grid set wrong. Requiring the same station *and* grid on 2+ days drops one-day flukes and garbled grids; showing the square lets you spot a wrong one that repeats.
- **Why Farthest contact has no 2-day rule:** the rule guards against false decodes, but a logged contact is a completed two-way exchange, and its grid came from that exchange. A grid you mistyped while logging would still show; the square is shown so you can spot it.
- **Why stations per day, not "open X of Y days":** `ALL.TXT` only records something when a line is decoded or you transmit, so a day on a dead band without transmitting leaves no trace and can't count as closed. In the author's data only 1 of 30 scored band-hours showed fewer open days than listening days, so that column nearly always read "X of X". The median day tells how busy the band typically is, and one unusually good day can't lift it. The same blind spot remains: silent, Rx-only days on a dead band are invisible, so the number leans optimistic.

**Why Python:** your strongest language; it can import the `band-privileges` engine directly; pytest's parametrize suits the many malformed-input cases. TypeScript lost because it would mean reimplementing the privileges engine.

**Standalone app: acceptance criteria** (settled 2026-11-01). A double-clickable Mac and Windows app for people without Python or a terminal. It's the existing page in a native window (pywebview), bundled with PyInstaller; `ft8cast` keeps working as it does now.
- **Starting:** opens one window showing the same page as `ft8cast serve`. Needs no Python, no terminal and no network. The server listens on `127.0.0.1` only, on a free port chosen at start, so a second app or `serve` on 8074 can't block it. Closing the window stops the server. A startup failure shows a readable message, not a silent exit.
- **Where data lives:** the app keeps its database and settings in the user's own folder (macOS `~/Library/Application Support/FT8 Forecast`, Windows `%APPDATA%\FT8 Forecast`), created on first use. It never writes beside the app. Run from source, `ft8cast` keeps using `data/` and `.env`.
- **Start screen** (added 2026-11-13, the user's choice over clearing data every launch): saved data is kept, but each launch with saved data opens on "Import your latest log below to start, or use the data saved from earlier." and a **Use saved data (through 2026-11-01 13:42 UTC, 11 days ago)** button instead of the forecast, hour list and overview. A successful import (file or folder) or the button shows the forecast for the rest of the launch; a failed import or saving settings doesn't. With no saved data, the usual "No data yet" prompt, without the button. The button is a POST with the same Origin check as uploads. `ft8cast serve` has no start screen. Nothing is deleted.
- **Settings:** a Settings section on the page sets the grid square and log folder, for the app and `serve` alike. They're saved in the same `.env` format, changing only those lines. A bad grid or a folder value containing a line break is a 400 that saves nothing and says why. Empty clears the value. Saving needs the same `Origin` as uploads. "Set MY_GRID in .env" messages point to Settings.
- **License class:** removed 2026-11-07. Every HF FT8 frequency is inside General's data segments (47 CFR 97.301(d), 97.305(c)), so General and Extra gave the same answers. Technician only hid bands you had listened to but can't transmit FT8 on; the forecast now shows what you heard there, since listening needs no license. Decodes still count only inside General's data segments, which keeps out other bands and mistyped dial frequencies. An old `LICENSE_CLASS` line in `.env` is ignored.
- **Errors:** unexpected errors say where the log file is, not "see the terminal", and the log holds no callsigns or grids. Still no traceback on the page.
- **Offline:** no update checks, analytics or web calls; a test fails on any connection except to the app's own local server.
- **Builds:** GitHub Actions builds on macOS and Windows, because PyInstaller only builds for the system it runs on. Each build must start and answer a local request before it counts. Builds are unsigned for now, and the README explains the macOS and Windows warnings. Nothing from `data/` or `.env` may be in a build; a test checks.

**Next:**
- Possible later: solar values typed in by hand (`--k`, `--flux`; no network).

### Threat model

Personal tool, local files only, no network. `serve` adds a local web server, so T5-T9 cover it; reading a folder (`LOG_DIR`, `--dir`, `watch`) adds T10-T12; the standalone app (2026-11-01) adds T13-T17.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | A damaged or crafted log crashes the import or corrupts data (huge lengths, truncation, odd bytes) | A10 Mishandling of Exceptional Conditions | Strict parsers; problems reported, bad records skipped; nothing raises | `test_adif.py`, `test_alltxt.py` |
| T2 | Other operators' callsigns and grids get committed | none (privacy mistake, not a code flaw) | `data/`, logs and `*.sqlite` gitignored | `git check-ignore` |
| T3 | A package published on PyPI as `band-privileges` gets installed instead of the local one (dependency confusion) | A03 Software Supply Chain Failures | Installed from `../band-privileges` only; not listed in `pyproject.toml` | — |
| T4 | Text in a log (free-text messages come from anyone on the air) runs as SQL | A05 Injection | Parameterized queries only | `test_store.py` |
| T5 | Another computer on your Wi-Fi opens the page or uploads to it | A01 Broken Access Control | Binds to `127.0.0.1` only (`lsof` on the running server shows `127.0.0.1:8074`) | `test_serve_listens_only_on_this_machine_with_debug_off` |
| T6 | A website open in your browser posts a file to the server (CSRF, cross-site request forgery) to plant fake data | A01 Broken Access Control | Uploads must carry this page's exact `Origin`; browsers always send it on a POST and pages can't fake it | `test_upload_from_any_other_origin_is_refused` |
| T7 | DNS rebinding: an attacker's domain is pointed at 127.0.0.1, so their page counts as "same site" and can read yours | A01 Broken Access Control | Only `Host: 127.0.0.1` or `localhost` is answered | `test_other_host_names_are_refused` |
| T8 | A crafted `ALL.TXT` line or file name, echoed in the problem list, runs as script in the page (XSS, cross-site scripting) | A05 Injection | Jinja auto-escaping; CSP `script-src 'self'` without `unsafe-inline`, so injected inline script wouldn't run (since 2026-11-13; before, no scripts at all); `busy.js` puts the chosen file's name in as text, never HTML; names cut to 80 characters | `test_on_air_text_and_file_names_are_escaped`, `test_security_headers_on_every_response` |
| T9 | Werkzeug's debugger gets switched on: its in-browser console runs any Python typed into it | A02 Security Misconfiguration | `debug=False` and no `.env` loading, so `FLASK_DEBUG` is ignored; errors show no traceback | `test_serve_listens_only_on_this_machine_with_debug_off`, `test_errors_show_no_traceback` |
| T10 | A website open in your browser makes the page import from some other folder on your disk | A01 Broken Access Control | The folder comes only from `LOG_DIR` in `.env`; the page has no folder field and ignores any sent | `test_page_never_takes_a_folder_path` |
| T11 | A symlink in the log folder (on a share, someone else may control it) points at a private file, which then gets parsed and bits of it echoed in problem messages | A01 Broken Access Control | Symlinks and subfolders are skipped; only `ALL.TXT` and `.adi`/`.adif` names are read | `test_skips_symlinks_and_subfolders` |
| T12 | A website open in your browser presses "Import from folder" (CSRF) | A01 Broken Access Control | Same exact-`Origin` check as uploads | `test_import_folder_from_any_other_origin_is_refused` |
| T13 | A website open in your browser changes the log folder through Settings (CSRF), then triggers an import. This replaces T10's "no folder field" safeguard for the Settings form | A01 Broken Access Control | Same exact-`Origin` check on saving settings; imports still read only the saved folder | `test_settings_from_any_other_origin_are_refused` |
| T14 | A value with a line break writes extra settings into `.env` | A05 Injection | Every value validated before saving; line breaks refused | `test_a_bad_setting_saves_nothing_and_says_why` |
| T15 | Someone's real logs or `.env` get bundled into a public build | none (privacy mistake, not a code flaw) | Builds run from a clean CI checkout; a test inspects the build | `packaging/check_build.py`, `test_private_files_are_found_at_any_depth` |
| T16 | A tampered download or a changed dependency reaches users | A03 Software Supply Chain Failures | Exact version pins, `pip-audit` in CI, builds only from GitHub Actions, SHA-256 checksums published with each release. Unsigned builds can't prove who made them (accepted for now) | CI checks each build's `.sha256` with `sha256sum -c`/`shasum -c` |
| T17 | The error log leaks other operators' callsigns or the user's grid into bug reports | A09 Security Logging and Alerting Failures | Logs record the error type and location, never log contents | `test_unexpected_errors_name_the_log_and_keep_log_contents_out_of_it` |

**Accepted risks:** a huge garbage file passed to `import` would collect one problem per line in memory. It's a personal tool reading your own files, so there's no cap beyond ADIF's 100 MB (and 500 MB for uploads). Werkzeug's development server is used rather than a production server (one more dependency): it serves one person on one machine, and T5-T9 cover what a production server wouldn't add. Mutation-checked 2026-10-28: removing each control above makes a test fail.

## Security notes

No secrets. `.env` holds only your grid square, kept out of git because it's your location. No transmit path exists.
