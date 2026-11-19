# Dipstick

Dipstick reads your NanoVNA over USB and tells you, in plain words, what it measured:

- **Antennas:** where the best match is on a band, how much to trim, and whether you need a tuner (and what kind) at your frequency.
- **Coax:** a cable's length (or velocity factor), what's at the far end, and its loss.
- **Baluns and ununs:** a transformer's match on each HF band, a choke's choking impedance, and through loss.

Every number comes with a line explaining it, so over time you learn to read the NanoVNA's own screen too. It's an app for macOS, Windows and Linux, plus a command-line tool.

*The name:* an antenna's resonance shows up as a dip in the SWR curve. Like a car's dipstick, Dipstick is the quick check you pull out and read.

## Works with

| NanoVNA | Works? |
|---|---|
| **NanoVNA-H, NanoVNA-H4** with hugen79 or DiSlord firmware (most sold today) | Yes, found automatically. Tested on a NanoVNA-H, firmware 1.2.43, on macOS and Windows. |
| **Original NanoVNA** firmware (edy555/ttrftech) | Should work, but it's not found automatically: its USB name is generic. Dipstick names the port it might be; choose it in the app's port picker or give `--port`. Not tested on hardware. |
| **Clones with a generic USB chip** (such as the CH340) | Yes: choose it once in the app's port picker, or give `--port`. |
| **NanoVNA V2, V2 Plus4, LiteVNA** | No. They use a different (binary) protocol. Dipstick doesn't detect them and sends them nothing. |
| **NanoVNA-F, F V2, F V3** | Unknown: different firmware, not checked. |

At most 101 points per sweep, the limit on most firmware. Firmware sources checked 2026-11-17; see [docs/development.md](docs/development.md#nanovna-compatibility).

## Install

Download from the [Releases page](https://github.com/jmringle/Radio/releases): choose the newest release named **dipstick** (this repository also holds other radio tools) and download only the `dipstick-` file for your computer. You don't need the "Source code" links.

The builds aren't code-signed, so your computer warns the first time:

- **Windows:** run `dipstick-Windows-Setup.exe`. No administrator rights needed. If SmartScreen says "Windows protected your PC", choose **More info → Run anyway**.
- **macOS** (Apple Silicon, M1 or newer): open the `.dmg` and drag **Dipstick** onto **Applications**. The first open is blocked: go to **System Settings → Privacy & Security** and click **Open Anyway**. On an Intel Mac, [run it from source](docs/development.md#run-from-source).
- **Linux:** `tar -xzf dipstick-Linux.tar.gz`, then run `Dipstick/Dipstick`. It needs WebKitGTK, which most desktops have.

**Check the download (optional).** Compare it against `SHA256SUMS.txt` from the release:

```
shasum -a 256 -c --ignore-missing SHA256SUMS.txt    # macOS
sha256sum -c --ignore-missing SHA256SUMS.txt        # Linux
Get-FileHash dipstick-Windows-Setup.exe             # Windows PowerShell
```

With the GitHub CLI, `gh attestation verify <file> -R jmringle/Radio` also proves GitHub Actions built the file from that release's tag.

## Safety first

- **Never connect a radio to the NanoVNA.** Its ports handle milliwatts; a transmitter's output can destroy it.
- **The NanoVNA transmits a tiny signal while it sweeps.** Into an antenna, that's on the air. So antenna sweeps stay inside one amateur band (47 CFR 97.301). Cable and balun tests sweep far outside the bands, so Dipstick refuses to run them until you confirm no antenna is connected.
- **Your NanoVNA's settings are put back** after every sweep. Dipstick never saves to or erases the NanoVNA's memory. A calibration from the app lasts only until you switch the NanoVNA off.

## Using the app

Plug in the NanoVNA. The header says **NanoVNA connected** when Dipstick has found it.

| Tab | What it does |
|---|---|
| **Antenna** | Choose a band (or type a target frequency, such as `146.52`) and press **Sweep**. Fill in **Antenna length** if you know it, so the trim in inches is from your antenna rather than an estimate. You get a short report of what to do (trim, tuner need, the 2:1 and 3:1 ranges), an SWR plot with those ranges shaded, and a Smith chart. The explanations are under **More detail**, which stays open if you leave it open. **Live (repeat)** sweeps again and again while you trim. |
| **Cable** | Remove the antenna, leave the cable's far end open or shorted, tick **No antenna connected**, and give the velocity factor (to get the length) or the length (to get the velocity factor). |
| **Balun** | Test a transformer with a resistor of 50 × its ratio on the output, a choke's impedance, or through loss. The tab shows the wiring for each test. |
| **Calibrate** | Walks you through open, short and load (and optionally isolation and thru for two-port tests) for the band you'll measure, using the kit that came with the NanoVNA. |

Under each Antenna or Cable result, **Check yourself** asks a few questions about *your* reading, such as which way to trim or how much power comes back. You can turn it off with the checkbox under the controls.

**Not found?** If the header says no NanoVNA was found, it lists your USB serial ports under **Is your NanoVNA one of these?** To see which port is the NanoVNA, unplug it and plug it back in. Choose only the NanoVNA: commands sent to a radio's cable could change the radio's settings. Also check that the USB cable carries data; a charge-only cable leaves the NanoVNA invisible.

## Using the command line

The same measurements without the window. To install it, see [Run from source](docs/development.md#run-from-source).

```
dipstick 40m                                   # sweep 40 m; trim advice for the middle of the band
dipstick 40m --target 7.074                    # trim advice for the FT8 frequency
dipstick 20m --antenna-length 16ft             # trim in inches from your antenna's real length
dipstick 915                                   # a frequency: sweeps its band (33 cm)
dipstick cable --no-antenna --vf 0.66          # cable length from the velocity factor
dipstick cable --no-antenna --length 50ft      # velocity factor from a known length
dipstick balun --no-antenna --ratio 49:1       # 49:1 unun with a 2450-ohm resistor on the output
dipstick balun --no-antenna --choke            # current balun's choking impedance
dipstick balun --no-antenna --loss direct      # through loss of one item (or back-to-back for a pair)
```

Options: `--points 2-101` (default 101), `--port /dev/cu.usbmodem4001` or `--port COM3` if it can't find the NanoVNA, and `--out FOLDER` for the SVG plots (default `output/`). Bands: 160m, 80m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 2m, 1.25m, 70cm, 33cm, 23cm. Exit code `0` means it measured; `2` means an error, explained in one line.

Example report (a made-up antenna that's a little long):

```
40m: best match SWR 1.00 at 7.051 MHz (excellent)
Shorten the antenna about 1.4% to move the best match to 7.150 MHz.
  This assumes an antenna you can trim (a wire dipole or end-fed, or an adjustable whip): ...

Across the band: 7.000 MHz SWR 1.81 | 7.150 MHz SWR 3.03 | 7.300 MHz SWR 10.52
  SWR (standing wave ratio) says how well the antenna matches your 50-ohm coax: ...
```

The answer comes first. Indented lines explain the line above them.

## Reading a NanoVNA: the short version

On CH0, the NanoVNA measures **S11**: how much of its test signal comes back, and with what timing (phase). Everything on its screen is S11 redrawn:

| On the screen | What it means | A good antenna |
|---|---|---|
| **SWR** | How well the antenna and coax are matched; 1.0 is perfect | Under 1.5 where you operate; 2.0 is usable |
| **Return loss** (dB) | How far below the outgoing signal the echo is | Higher is better: 14 dB = SWR 1.5, 9.5 dB = SWR 2.0 |
| **R + jX** (impedance) | R: resistance, the part that radiates (or heats). X: reactance, energy stored and returned. +jX: too long; −jX: too short | R near 50, X near 0 |
| **Smith chart** | S11 itself, plotted: the center is a perfect match, the edge is total reflection | The trace passes near the center |

**Resonance** is where X crosses 0. It's often near the lowest SWR, but not exactly at it. Dipstick gives trim advice from the lowest SWR; [docs/how-it-works.md](docs/how-it-works.md) explains why, and how each test works.

## More

- [How it works](docs/how-it-works.md): the measurements and the reasoning behind the advice.
- [Development](docs/development.md): run from source, tests, building and releasing, design decisions, what's next.
- [Security](docs/security.md): the threat model.
