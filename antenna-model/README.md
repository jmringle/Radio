# antenna-model

Models your HF antennas with NEC2 so you can see what they do before changing anything in the yard: radiation pattern, takeoff angle, gain, feedpoint impedance and SWR across a band. Antennas: the 40 m dipole, the 40 m EFHW (with the tuner on 40/20/15/10 m), the 30 m dipole and the 20 m vertical. It runs entirely on your computer: no network, no radio connection, nothing transmits.

**Status:** scaffold. NEC2 runs through PyNEC and is checked against textbook dipole values, and the SWR math is tested. No antenna files, plots or command yet (see Next).

## Setup

Python 3.12 to 3.14 (PyNEC 2.3.4 has no wheel for 3.15 yet; pip would try to compile NEC2 from source).

```
cd ~/git/Radio/antenna-model
python3 -m venv .venv
.venv/bin/python -m pip install pip==26.2.2   # venv starts with the pip Python shipped with; pip-audit flags old ones
.venv/bin/pip install -r requirements-dev.txt
```

## Running tests

```
.venv/bin/pytest
```

The same command runs in GitHub Actions on every push that touches this folder (`.github/workflows/antenna-model-tests.yml`, Python 3.12 and 3.14), followed by `pip-audit` (known-vulnerable dependencies). Gitleaks scans the whole repo for committed secrets.

| File | What it guards |
|---|---|
| `tests/test_swr.py` | SWR against hand-worked values; shorts and pure reactances are infinite; negative resistance and non-numbers refused |
| `tests/test_nec.py` | NEC2 against textbook dipoles: a half wave is about 73 + j42 ohms, about 0.485 wavelength is nearly resonant near 70 ohms, too short is capacitive; impossible dimensions refused |

The textbook tests are the foundation: a model of your real antenna is only worth trusting if the same setup gets the known answers right.

## Design notes

**Language** (decided 2026-11-14): Python with PyNEC. NEC2 itself is 1981 Fortran from Lawrence Livermore (public domain); PyNEC wraps necpp, a maintained C++ port, so the solver is the standard one rather than something written here. Python is what the other Radio tools use and the language you know best, and the results feed pytest and, later, ft8-forecast. Alternatives: 4nec2 (free point-and-click NEC2, but Windows-only and hard to test automatically) and calling a `nec2c` binary (not in Homebrew, checked 2026-11-14; would mean building it and parsing text output).

**Versions** (checked on PyPI 2026-11-14, 2-week rule): PyNEC 2.3.4 (2026-08-02; 2.3.5 and 2.4.0 are from 2026-11-09, too new), pytest 9.2.0, pip-audit 2.10.1. numpy comes in through PyNEC.

**License and ft8-forecast** (decided 2026-11-14): PyNEC and necpp are GPL (necpp: "version 2 or any later version", per its source headers); this repo is MIT. The GPL's obligations start when GPL code is distributed, and ft8-forecast's app is a public download, so PyNEC is never bundled into it. Instead:

- **Now: two tools, one results file.** antenna-model (with PyNEC) runs on your machine and writes a JSON results file; ft8-forecast reads that file and shows it on its page. Results are data, not code, so the app's license doesn't change, and it doesn't take on numpy or PyNEC's compiled code either.
- **Goal: our own solver, MIT.** A thin-wire method-of-moments solver in numpy, small enough to bundle in ft8-forecast so anyone can model their antennas in the app. PyNEC stays as a test-only reference: the solver must match NEC2 within a tolerance on the same antennas. Tests aren't distributed, so that's no license concern. Real ground is the hard part (NEC2 uses the Sommerfeld method); expect a simpler approximation and document how far it is from NEC2.
- **What keeps that switch cheap:** the results file is the contract. ft8-forecast depends only on it, never on PyNEC, so swapping the solver changes nothing on its side. All PyNEC calls stay in `nec.py`, and the antenna file format, validation and SVG drawing don't depend on which solver ran.

**Units:** meters and MHz inside the code. Open question: whether antenna files take feet too.

### Acceptance criteria (v1, to build)

- **One antenna file per antenna** (TOML, read with Python's standard library): wires as end points and wire size, the feedpoint, height, ground type, and the bands to model.
- **`antenna-model FILE`** prints, for each band: feedpoint impedance and SWR (50 ohms) at band edges and center, the frequency of lowest SWR, maximum gain (dBi) and the takeoff angle of the main lobe. It saves SVG plots to `output/` (drawn by this tool, no plotting library; the same drawing code serves ft8-forecast's page): elevation pattern, azimuth pattern at the takeoff angle, SWR across the band.
- **Results file:** `--json` writes the same results as JSON with a format version: the contract ft8-forecast reads. It records which solver and version produced it.
- **Ground:** free space for the textbook checks, and real ground (conductivity and permittivity) for your antennas, with named presets whose values cite their source.
- **Checked against reality:** each of your antennas' predicted lowest-SWR frequency is compared with what you measure on the G90; the README records both.
- **Bad input:** a missing file, bad TOML, a missing field, a non-positive or non-numeric dimension, a wire too thick for its segments, a wire below ground, or more segments than the cap: a one-line error naming the field, exit code 2. Model problems NEC2 accepts but gives wrong answers for (segments too long for the frequency, wires touching at odd points) are warnings, so a bad model never looks trustworthy.
- **Later:** the web page is ft8-forecast's: it reads the results file and shows the plots (your choice of "CLI plus a page"), with no second web server.

### Threat model

Personal tool, local files, no network, no radio connection. Antenna files are your own, but they could also come from a forum or club.

| ID | Threat | OWASP 2025 | Mitigation | Test |
|---|---|---|---|---|
| T1 | A malformed or crafted antenna file crashes the run or gives a believable but wrong answer | A10 Mishandling of Exceptional Conditions | Every field validated (finite, positive, thin-wire limits) before NEC2 sees it; clear one-line errors | `test_impossible_inputs_are_refused`, `test_impossible_dimensions_are_refused`; more with the file reader |
| T2 | A huge segment count uses up memory or CPU (NEC2's memory grows with the square of the segment count) | A06 Insecure Design | A cap on total segments, checked before running | with the file reader |
| T3 | An output name in a file writes outside `output/` | A01 Broken Access Control | Plot names are made by the tool, never taken from the file | with the plots |
| T4 | A compromised dependency; PyNEC is compiled C++, so a bad wheel runs native code | A03 Software Supply Chain Failures | Exact pins, 2-week rule, `pip-audit`, Dependabot | CI |
| T5 | ft8-forecast reads a results file that's damaged or crafted (a shared file) and crashes or injects markup into its page | A05 Injection, A10 Mishandling of Exceptional Conditions | ft8-forecast validates the file (format version, size cap, numbers in range) and escapes all text; no markup taken from the file | in ft8-forecast, with the page |

No secrets: nothing here needs a key or password, so there's no `.env`.

## Next

1. The antenna file format and reader, with its validation tests.
2. Real ground and the takeoff angle and gain from a pattern; test against textbook dipoles over ground (a horizontal dipole a half wavelength up has its main lobe near 30 degrees).
3. The command, the SVG plots and the JSON results file.
4. Your four antennas, from your measurements: wire lengths, feedpoint and end heights, flat or inverted V, the vertical's radials.
5. ft8-forecast reads the results file and shows it on its page.
6. Later: compare with where ft8-forecast says you're heard.
7. Goal: our own MIT solver, tested against PyNEC, bundled in ft8-forecast.
