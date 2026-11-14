# codeplug-check

Checks a radio's channel list before you load it, and catches the mistakes a typo makes: a channel that would transmit outside the amateur bands, a repeater offset that doesn't match the band plan, a repeater channel with no tone, and duplicate channels. It reads a CHIRP CSV export (CHIRP supports both the BTECH UV-PRO and the Baofeng DM-32UV; checked on CHIRP's supported-radios list 2026-11-13). It only reads the file: it never talks to or programs a radio, and it makes no network calls.

**Status:** v1 works: the command, the reader and the checks are built and tested. It reads CHIRP's own sample export (`tests/images/Generic_CSV.csv` in CHIRP's repo, 95 channels; GPL-3.0, so not copied here) with no read problems, and finds 67 channels that would transmit outside the amateur bands (weather, airband, public safety; Duplex left blank instead of `off`), 7 repeater channels with no tone, 5 repeater outputs outside the band-plan segments and 3 duplicates. Not yet run on a real UV-PRO or DM-32UV export.

## Setup

Python 3.12 or newer.

```
cd ~/git/Radio/codeplug-check
python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.2   # venv starts with the pip Python shipped with; pip-audit flags old ones
.venv/bin/pip install -r requirements-dev.txt
```

## Usage

```
.venv/bin/codeplug-check data/channels.csv
```

```
channels.csv: 3 channels checked

Errors (1)
  line 3, location 2 "GMRS 1": This channel transmits on 462.562 MHz, outside the amateur bands (47 CFR 97.301); set Duplex to off for receive-only

Warnings (1)
  line 2, location 1 "RPT": Offset +0.600 MHz; the band plan has -0.600 MHz for outputs 146.610-146.970

Notes (1)
  line 4, location 3 "RPT": Same frequencies, tones and mode as location 1 (line 2)
```

"line" is the line in the CSV file (open it in a text editor or spreadsheet to find it); "location" is CHIRP's memory number. Exit codes: `0` no errors (warnings and notes don't fail), `1` at least one error, `2` the file can't be checked (missing, over 5 MB, not UTF-8, not a CHIRP export) or a usage error.

## Your data

Export your channels from CHIRP (File → Export → CSV) into `data/`. Everything in `data/` except `.gitkeep` is gitignored, so your frequency list and repeater names stay on your machine. Tests use made-up channels only.

## Running tests

```
.venv/bin/pytest
```

The same command runs in GitHub Actions on every push that touches this folder (`.github/workflows/codeplug-check-tests.yml`, Python 3.12 and 3.15), followed by `pip-audit` (known-vulnerable dependencies). Gitleaks scans the whole repo for committed secrets.

## Design notes

**Language** (decided 2026-11-13): Python, standard library only. CHIRP's CSV is plain text that `csv` reads; the checks are arithmetic on frequencies. Python is what the other Radio tools use, and it's the language you know best. Alternatives: a CHIRP plugin (Python too, but tied to CHIRP's GUI and release cycle) or TypeScript for a web page (you chose a command line; a page can come later). Not reused: `band-privileges`: above 50 MHz every license class has the whole band (47 CFR 97.301(a)), so there is no class difference to check, and band edges are six constants.

**Sources**
- Band edges: 47 CFR 97.301(a), ITU Region 2 (eCFR, up to date as of 2026-11-12): 6 m 50-54, 2 m 144-148, 1.25 m 222-225, 70 cm 420-450, 33 cm 902-928, 23 cm 1240-1300 MHz. 1.25 m's 219-220 MHz is left out: fixed digital message forwarding only (97.303(l)). Parts of 70 cm have location limits (97.303(m)) a file can't show, so they aren't checked.
- Repeater offsets: ARRL band plan (arrl.org/band-plan, checked 2026-11-13). 2 m: outputs 145.20-145.50 and 146.61-146.97 have inputs 600 kHz lower; outputs 147.00-147.39 have inputs 600 kHz higher. 70 cm: 442-445 and 447-450 MHz are "repeater inputs and outputs (local option)", 5 MHz apart, so the split is 5 MHz but the direction is local.
- CHIRP CSV: CHIRP's source (`chirp_common.py`, `drivers/generic_csv.py`, commit d99bb22709, 2026-11-13). Columns `Location, Name, Frequency, Duplex, Offset, Tone, rToneFreq, cToneFreq, DtcsCode, DtcsPolarity, RxDtcsCode, CrossMode, Mode, TStep, Skip, Power, Comment` (plus D-STAR fields). Frequencies in MHz, up to 6 decimals. Duplex `""`, `+`, `-`, `split` (Offset holds the transmit frequency) or `off` (no transmit). Tone modes `""`, `Tone`, `TSQL`, `DTCS`, `DTCS-R`, `TSQL-R`, `Cross` (with CrossMode such as `Tone->DTCS`). Lines starting with `#` are comments; the file may start with a UTF-8 byte-order mark.

### Acceptance criteria

`codeplug-check FILE.csv` prints problems grouped as Errors, Warnings and Notes, each naming the CSV line, the channel's Location and Name.

- **Error: transmits outside the amateur bands.** The transmit frequency (Frequency, adjusted by Duplex/Offset) is outside every band above; the message says to set Duplex to `off`. Channels with Duplex `off` never transmit, so weather, scanner and GMRS-listening channels are fine as receive-only. Such a channel gets only this error, no offset advice on top.
- **Warning: repeater offset doesn't match the band plan.** 2 m: offset other than 600 kHz, or the wrong direction for the output's segment. 70 cm: split other than 5 MHz (either direction). A repeater channel whose output isn't in a band-plan output segment is a Note ("check with the local coordinator"), since plans vary locally. Other bands: no offset check.
- **Warning: repeater channel with no transmit tone.** Duplex `+`, `-` or `split` and no tone sent on transmit: Tone blank, `TSQL-R` or `DTCS-R` (tone on receive only), or a CrossMode that sends nothing (`->Tone`, `->DTCS`, `->`). Most repeaters need a tone to open. Only for FM modes (`FM`, `NFM`, `WFM`); DMR and other digital modes don't use CTCSS/DCS.
- **Note: duplicates.** Two or more channels with the same receive and transmit frequency, tones and mode (names may differ); or one Name used for different settings. Blank names are ignored.
- **Bad input:** a missing or unreadable file, a file over 5 MB, or one without CHIRP's `Location` and `Frequency` columns: a one-line error, exit code 2. A bad row (unreadable frequency or offset, unknown Duplex or Tone value, wrong column count): reported with its line number as an Error, and the rest of the file is still checked. A row is never skipped silently. Rows with a blank or zero Frequency are empty memories, as in CHIRP.
- **Exit codes:** 0 no Errors (Warnings and Notes don't fail), 1 at least one Error, 2 bad input or usage.

### Threat model

Personal tool, local files, no network, no radio connection. Channel lists are often downloaded (RepeaterBook exports, club files), so the file is untrusted input.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | A crafted or damaged CSV crashes the check or makes it skip rows, so a bad channel passes as fine | A10 Mishandling of Exceptional Conditions | Strict field parsing (ASCII digits only, at most 6 decimals, known Duplex values); bad rows reported, never skipped silently; 5 MB cap | `test_parse_mhz_refuses_anything_else`, `test_unknown_duplex_is_refused`, `test_a_bad_row_is_reported_with_its_line_and_the_rest_still_read`, `test_a_file_over_5_mb`, `test_broken_quoting_names_its_line` |
| T2 | A channel name with terminal control codes (ANSI escapes), a right-to-left override (U+202E) or a Unicode line separator rewrites, reorders or fakes lines in your terminal when printed | A05 Injection | Every control, format and line/paragraph-separator character printed from the file becomes U+FFFD (visible); names cut to 40 characters; rows end only at CR/LF, as CHIRP reads them | `test_control_characters_in_names_never_reach_the_terminal`, `test_only_carriage_return_and_line_feed_end_a_row` |
| T3 | Your real channel list gets committed | none (privacy mistake) | `data/` gitignored | `git check-ignore` |
| T4 | A compromised dependency | A03 Software Supply Chain Failures | No runtime dependencies; dev tools pinned (2-week rule); `pip-audit` and Dependabot | CI |

## Next

1. ~~Read a whole CHIRP CSV~~ (done 2026-11-13). Tone fields are read only when the row's Tone mode uses them: CHIRP fills unused ones with defaults (CrossMode is `Tone->Tone` on every row of its sample). Offset counts only for Duplex `+`, `-`, `split`: CHIRP keeps a simplex channel's old offset.
2. ~~The checks~~ (done 2026-11-13, `checks.py`). ~~The command~~ (done 2026-11-13, `cli.py`).
3. Run it on your real UV-PRO export; adjust anything a real file shows.
4. Later: the DM-32UV's own CPS export for DMR channels (color code, timeslot, talkgroup), once there's a sample file to read.

## Security notes

No secrets, network or radio access. Run gitleaks before pushing if it's installed; CI runs it on every push.
