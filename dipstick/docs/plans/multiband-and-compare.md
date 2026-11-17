# Plan: multi-band sweep and before/after compare

Status: acceptance criteria drafted 2026-11-17, not built. Decisions marked **(approved)** were approved 2026-11-17; **(undecided)** is still open.

## Why

- **Multi-band:** the EFHW with its 49:1 covers 40, 20, 15 and 10 m. Today that takes four runs and four reports. One run with one summary shows the whole antenna at once, and helps track down the flat SWR of about 4.1 seen on 40 m.
- **Compare:** trimming is a loop: sweep, cut, sweep again. Seeing "best match moved 7.051 → 7.150 MHz after you shortened it" teaches cause and effect better than two separate reports.

## Rules that still apply

- **Each band's sweep stays inside that band** (T5, 47 CFR 97.301). A multi-band run is several one-band scans, never one wide sweep across the gaps between bands.
- **The NanoVNA's sweep settings are put back** after every scan, as today.
- **Nothing new is sent to the NanoVNA:** same allowlist (T1); no new commands.

---

## A. Multi-band sweep

### Interface (approved)

- Command: `dipstick 40m 20m 15m 10m`. Several bands are given where one is today, and existing options keep working (`--points`, `--port`, `--out`).
- App, Antenna tab: a **More than one band** checkbox that turns the band list into checkboxes. Sweep runs them in the order listed.

### Acceptance criteria

**Happy path**
1. Each band is swept on its own, in the order given, with the same points as a single-band run.
2. The report starts with a summary table, one line per band: the band, the best match frequency, best SWR, 2:1 bandwidth and **tuner need** (see "Tuner need" below). Then each band's full report follows, as today.
3. The summary's first line says the answer in words, e.g. "No tuner needed on 40 m and 20 m; 15 m is within most built-in tuners; 10 m needs a wide-range external tuner."
4. One SWR plot and one Smith chart per band, named from band and time as today (never from typed text). Optionally a combined SWR plot with one panel per band **(undecided)**.
5. `--target` is refused with more than one band, since a single target can't apply to several bands. Trim advice in each band's report aims at that band's middle.
6. Calibration note: the NanoVNA holds one calibration range. Every band outside the calibrated range gets the existing "not calibrated for this band" note, and the summary says how many bands were uncalibrated.

**Tuner need (approved 2026-11-17: based on typical tuners, not one radio)**

Judged from each band's best SWR, with the same words everywhere a band is rated:

| Best SWR | Words | Basis |
|---|---|---|
| 2.0 or less | no tuner needed | Many radios cut power above about 2:1 (the report already says to check your radio's manual) |
| over 2.0, up to 3.0 | within most built-in tuners | Icom IC-7300 and Yaesu FT-991A manuals: 16.7–150 Ω, stated as SWR 3:1 or less (read 2026-11-17) |
| over 3.0, up to 8.0 | needs a wide-range external tuner | LDG Z-100Plus manual: 6–800 Ω on HF; 50 / 6 ≈ 8.3:1 is its tighter side (read 2026-11-17). One example, so 8:1 is a cautious judgement, not a standard |
| over 8.0 | beyond most tuners: check the antenna, coax and connectors | — |

- **6 m is stricter:** the same LDG tuner covers only 16–150 Ω on 6 m (about 3:1), so on 6 m anything over 3.0 reads "beyond most tuners".
- **Caveats in the report, once:** a tuner's range is really an impedance range, so the SWR limit is approximate (reactance matters too). A tuner at the radio protects the radio but doesn't fix the antenna, and the coax still loses more at high SWR. Check your own tuner's manual.
- **Single-band runs use the same words.** This replaces today's "high: you'll need a tuner" for anything up to SWR 5 **(approved 2026-11-17)**. Build it first, as its own small change, since it fixes wording in the released app.

**Negative and boundary**
7. A duplicate band (`40m 40m`) is refused before connecting.
8. Unknown bands, or a frequency outside the bands, are refused before connecting. Nothing is sent if any band in the list is bad.
9. Mixing a band and a frequency (`40m 14.074`) is refused before connecting **(approved: keep it simple)**.
10. One band behaves exactly as today: same output, same exit code. Existing tests pass unchanged.
11. Up to all 15 bands are allowed. The run warns up front that it takes about 1.5 s per band.

**Failure**
12. NanoVNA unplugged or timing out partway through: the bands already measured are still reported, followed by one clear line naming the band that failed. Exit code 2 **(approved: partial results rather than nothing)**.
13. Settings are put back after each band's scan, so a failure on band 3 leaves the NanoVNA as it was. If that restore fails, the message says what to set by hand (existing behaviour).
14. A band with nothing connected (SWR > 10 everywhere) says so in its line. It's not an error for the run.

**App**
15. Live mode is off while more than one band is chosen **(approved)**: four bands at 1.5 s each is too slow to watch a dip move.
16. The other tabs are locked during the run, as for any sweep, and Stop finishes the current band and then reports what it has.

---

## B. Before/after compare

### Interface (approved)

- Every band sweep also saves its readings as a **Touchstone `.s1p` file** next to the SVGs (e.g. `output/40m-20261117-140102.s1p`). Touchstone is the standard VNA data format, so the files also open in NanoVNA-Saver and can later feed antenna-model.
- Command: `dipstick 40m --compare output/40m-20261117-140102.s1p` sweeps now and compares with the saved file.
- App: **Keep as reference** after a sweep. Later sweeps of that band, Live included, overlay the reference curve and add a "Since the reference" section. **Clear reference** removes it. It's held in memory only, not saved.

### Acceptance criteria

**Happy path**
1. The report adds a **Since the reference** section at the top: how far the best match moved (MHz and kHz, up or down), the best SWR before and after, and the 2:1 bandwidth before and after.
2. It explains the move in trim terms: "moved up 99 kHz (1.4%): consistent with shortening it about 1.4%". It never claims you did trim; it says what the change is consistent with.
3. The SWR plot draws the reference as a second, dashed line with a key ("before", "now"). The Smith chart shows both traces.
4. A change smaller than one frequency step reads "no measurable change", not a tiny number.
5. Saved `.s1p` files hold exactly what was measured: frequency in Hz and S11 as real/imaginary, with a `!` comment line giving the band, time and dipstick version.

**Reading a saved file: it's input, so validate it** (T4, the same as a NanoVNA reply)
6. Accepted: Touchstone v1 with the option line `# Hz S RI R 50` (case-insensitive, MHz/kHz/GHz units converted), `!` comments, 2 to 1001 points, frequencies strictly increasing.
7. Refused, each with one clear line and nothing swept: a missing or different option line (MA or dB formats, a reference other than 50 ohms), a non-number, NaN or infinity, |S11| above 1 beyond the small noise allowance already used, frequencies out of order or repeated, more than 1001 points, a file over 256 KB, a non-UTF-8 or binary file, a file that doesn't exist, or a folder.
8. The reference must overlap the band swept now. A 20 m file compared with a 40 m sweep is refused before connecting. A partial overlap is compared only over the shared range, and the report says so.
9. Different point counts are fine: the reference is compared at its own points. The best-match movement is reported only to the coarser of the two steps.
10. The file is only read, never written or moved, and its name or contents never appear as markup in the app (T8). Long file names are cut short in errors, as for other input.

**Failure**
11. A failed sweep with `--compare`: the existing error, plus no comparison. The reference file is untouched.
12. Calibration can't be known from a file, so the section always ends with: "Both sweeps should use the same calibration and cable for a fair comparison."

---

## Tests to write first

- **Tuner need:** each boundary and just past it (2.00 / 2.01, 3.00 / 3.01, 8.00 / 8.01); 6 m at 3.00 / 3.01; infinite SWR; the caveat appears once per report, not once per band.
- **Multi-band:** order of scans and restores (fake NanoVNA log); a refused list sends nothing; unplug on band 2 of 3 gives a partial report and exit 2; single-band output byte-identical to today; summary wording; plot file names.
- **Compare:** `.s1p` round trip (save, then read back, equals the readings); every refusal in criterion 7 as its own case; overlap and partial overlap; movement maths against a made-up antenna with known resonance shift; "no measurable change" at exactly one step and just above.
- **App:** reference kept in memory only; cleared on band change; overlay drawn; Live with reference; multi-band locks tabs; Stop mid-run reports bands done; Python refuses a list containing anything but known band names.
- **Hardware (opt-in):** EFHW on 40/20/15/10 m in one run, with the settings put back.
