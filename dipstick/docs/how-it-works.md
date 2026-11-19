# How Dipstick works

What each test measures, how the numbers are worked out, and why the advice is what it is.

## Antenna sweep

Dipstick sweeps the whole band with up to 101 points. The report starts with what you act on:

- **Best match:** the frequency with the lowest SWR, and its rating.
- **What to do:** how much to shorten or lengthen the antenna to move the best match to your target (the middle of the band unless you give `--target`), as a percent and in inches and cm, with half of it for each end of a dipole.
- **At your target now:** the SWR there and what it takes to use it (the tuner words below).
- **2:1 bandwidth** (no tuner needed) and **3:1 bandwidth** (most built-in tuners): the stretches around the best match where SWR is at most 2 or 3.
- A one-line calibration reminder, unless you calibrated in the app this session.

Then **More detail**: what the NanoVNA measured, SWR at the edges and middle, what the bandwidths and a tuner's range really mean, how trimming works, and impedance (R + jX, where X = 0) for the curious. The command prints both parts; the app shows the first and folds More detail away (display review 2026-11-19).

**Tuner words** (from typical gear, not one radio; approved 2026-11-17, see `docs/plans/multiband-and-compare.md`): SWR 2 or under, no tuner needed; up to 3, within most built-in tuners (Icom IC-7300 and Yaesu FT-991A manuals: 16.7–150 ohms); up to 8, needs a wide-range external tuner (LDG Z-100Plus: 6–800 ohms on HF); above that, beyond most tuners. On 6 m anything over 3 is beyond most tuners (the same LDG covers only 16–150 ohms there). Above 6 m, most VHF and UHF radios have no tuner, so over 2 says to trim or fix the antenna (a judgement, 2026-11-19) and there's no 3:1 line. A tuner's range is really an impedance range, so the SWR limits are approximate.

It also saves an SWR plot (log scale 1 to 10, with the 2:1 and 3:1 lines, the stretches under each shaded, and the best match and target marked) and a Smith chart, as SVG files.

**Why trim advice comes from SWR, not X.** On low-loss coax, SWR is the same at both ends of the cable, so the lowest-SWR frequency is the antenna's own best match whatever the coax length. Impedance changes along the coax, so X = 0 at the radio end usually isn't where the antenna itself is resonant. The trim percentage assumes an antenna you can trim (a wire dipole, an end-fed or an adjustable whip): its best-match frequency moves opposite to its length, roughly as 1 / length. A fixed antenna like a rubber duck can't be trimmed.

**Inches from the percent** (2026-11-19). The percent is of the antenna's length as it is now. Given the length (`--antenna-length` or the app's Antenna length, up to 200 m), Dipstick uses it. Otherwise it estimates a half-wave wire at the best-match frequency with the usual rule of thumb, 468 / MHz feet, and says so. That fits a dipole or an end-fed on its main band; for a quarter-wave vertical the estimate is about twice too much, and for an end-fed on a harmonic band about half, so give the length for those.

**"No clear dip."** If SWR stays above 2 everywhere and the highest SWR is less than 1.25 times the lowest, there's no dip to move, so Dipstick gives no trim advice. Usually the antenna is resonant well outside the band, or something is missing or wrong: the counterpoise or ground it needs, a bad connector, or a lossy cable. A dipole even 10% off frequency rises far more than that across a band.

**Nothing connected.** SWR over 10 everywhere reads as "SWR is infinite everywhere: all of the signal comes back", with no advice.

## Cable check

**Remove the antenna first.** This sweep runs from 1 MHz up to 200 MHz, far outside the ham bands. Leave the cable's far end **open** (nothing connected) or **shorted**. A dummy load absorbs the signal, so there would be no echo to measure.

**How.** With the far end open or shorted, the whole signal bounces back. The echo's phase turns faster with frequency the longer the trip, so a straight line fitted to phase against frequency gives the delay. Then:

- **Length** = delay × velocity factor × speed of light (or, given the length, the velocity factor).
- **Far end:** an open reflects in phase and a short inverts, so Dipstick can tell which you have. If you left it open and it reads short, look for a fault.
- **Loss:** the echo comes back weaker by the loss out *and* back, so one-way loss is half the return loss. It's reported at 7, 14, 28 and 50 MHz.

The **velocity factor** (the signal's speed in the cable as a fraction of light's) is on the cable's data sheet: about 0.66 for solid polyethylene (RG-58, RG-213); foam is higher.

**Aliasing.** The sweep is planned so the phase turns less than half a turn per step for the longest cable you plan for (`--max-length`, default 50 m). A longer cable would wrap around and look short. If the phase doesn't follow a straight line (an antenna, a load or a fault partway along), the report warns that the numbers are rough.

**Short jumpers.** Set the longest cable low (say 1 m) so the sweep reaches 200 MHz. Expect a rough answer anyway: the connectors add about as much delay as a 6-inch cable itself. On a real 6-inch jumper, Dipstick found the open end and 0.25 m at VF 0.66; given `6in`, it reported VF 0.41, because the connectors count as cable.

## Balun and unun tests

All three tests sweep 1.8 to 54 MHz (outside the ham bands), so they need **No antenna connected** / `--no-antenna`. For accurate numbers, calibrate over the same range first: Calibrate tab, **HF wide** (with **Both ports** for the choke and through-loss tests).

### Transformer (unun or voltage balun)

Put a resistor of 50 × the ratio across the output with short leads: 2450 ohms for a 49:1 (2.4 k plus 47 ohms in series is close), 50 ohms for a 1:1. Use carbon or metal film, not wirewound. Connect the input to CH0. Ratios: 1:1, 4:1, 9:1, 49:1.

**How.** An ideal n:1 transformer with resistor R on its output looks like R / n at its input, so with R = 50 × n the NanoVNA should see 50 ohms, SWR 1. What it actually reads is the transformer's own match. The resistor stands in for the antenna at its best, so a real antenna can only do worse.

- A resistor that isn't exactly 50 × n is fine: the report says what a perfect transformer would read with it (2.7 k on a 49:1: SWR 1.10). One so far off that a perfect transformer would read over 1.5 is refused, because it would hide the transformer's own behavior.
- At 2450 ohms, 2 pF of stray capacitance (resistor leads, a clip) is about 2.8 k of reactance at 28 MHz, as much as the resistor. So the high bands can read worse than the transformer really is; the report warns for resistors of 1000 ohms and up.
- SWR over 10 everywhere is an error ("Is the resistor connected?"), not a report.

### Choke (current balun)

A current balun works by blocking current on the outside of the coax. With the balun off the antenna: join its two input terminals (an SO-239's center pin and shell) and wire them to CH0's center pin; join its two output terminals and wire them to CH1's center pin; connect the outer shells of CH0 and CH1 with a short wire. Keep every wire short.

**How.** An impedance Z in series between two 50-ohm ports passes S21 = 100 / (100 + Z), so Z = 100 × (1 − S21) / S21 (the series-through method, [K6JCA](https://k6jca.blogspot.com/2020/07/the-y21-method-of-measuring-common-mode.html)). The report gives R (the resistive part, which does the choking) and |Z| per band, rated by rules of thumb (read 2026-11-17):

| Rating | Rule | Source |
|---|---|---|
| **weak** | \|Z\| under 500 ohms (10 × the coax impedance) | [Palomar / AK6R, 2022](https://palomar-engineers.com/wp-content/uploads/Choosing-a-Feedline-Choke-Palomar-Engineers-2022-Update-by-AK6R.pdf) |
| **fair** | between weak and good | — |
| **good** | R of 1,000 ohms or more | G3TXQ, quoted by [K6JCA](https://k6jca.blogspot.com/2018/06/transmit-common-mode-chokes-11-current.html) |
| **plenty** | R of 5,000 ohms or more | K9YC, quoted by K6JCA |

Readings the setup can't resolve are given in words: under 1 dB (about 12 ohms) is mostly calibration error, and over 40 dB (about 10,000 ohms) is near the noise floor. Nothing arriving at CH1 at all is an error, not a perfect choke: an unconnected CH1 looks the same. Wire capacitance makes the high bands read lower than the choke really is.

### Through loss

- **Direct** (`--loss direct`): for a 1:1 balun, a cable or a filter, anything meant for 50 ohms at both ends. Input to CH0, output to CH1.
- **Back to back** (`--loss back-to-back`): for two identical transformers, such as two 49:1s. Join their high-impedance sides terminal to terminal with short wires, then connect one coax side to CH0 and the other to CH1. Each transformer's share is half the total, if they really are identical. A single 49:1 alone reflects most of the signal, so test it with a resistor or as a pair.

**How.** Loss in dB is −20 log₁₀ |S21|. The report gives the most and least loss, then each band in dB and as the share of power that doesn't arrive (3 dB is half; 1 dB about a fifth). Up to 0.1 dB of apparent *gain* is treated as noise and shown as about 0. That threshold is a judgement call, not yet checked on hardware. More gain than that means: recheck the thru calibration.

## Calibration

Calibrating shows the NanoVNA what its own connector, plus any adapter or jumper you measure through, looks like, so it can remove them from every measurement:

- **open** reflects everything in phase,
- **short** reflects everything inverted,
- **load** (50 ohms) reflects nothing.

**Both ports** adds **isolation** (load on CH0; a second load on CH1 if you have one, otherwise leave CH1 open) and **thru** (CH0 joined to CH1 by the cables and connector you'll measure with).

The app's calibration lives in the NanoVNA's memory only. Dipstick never sends `save`, so switching the NanoVNA off and on brings back its saved calibration. A calibration covers only the range it was made over, so a sweep of another band starts with a note saying it isn't calibrated there. Partway through a calibration the old one has already been reset, so the other tabs stay locked until it finishes. To abandon one, set the band back to **Choose a band** and switch the NanoVNA off and on.

After calibrating **HF wide**, the NanoVNA keeps sweeping 1.8 to 54 MHz on its own, so keep antennas off until you calibrate a band or switch it off and on.

## Leaving the NanoVNA as it was

On firmware 1.2.43, `scan` replaces the NanoVNA's own frequency list and point count, but afterward `sweep` still reports the old start and stop. So Dipstick reads the settings before every scan and always puts them back, even if the scan fails. If putting them back fails too (for example, the USB cable was pulled out), it tells you what to set by hand. The NanoVNA runs on its battery, so it stays on with the scan's settings.
