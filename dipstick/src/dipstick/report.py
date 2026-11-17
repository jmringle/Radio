"""A band report in plain words: every number comes with what it means."""

from dipstick.analysis import Summary
from dipstick.balun import (DEEPEST_DB, GOOD_OHMS, MATCHED, PLENTY_OHMS, POINTS, SHALLOWEST_DB, START_HZ, STOP_HZ,
                            WEAK_OHMS, ChokeResult, TransformerResult)
from dipstick.cable import CableResult
from dipstick.s11 import Reading

NO_TRIM_PERCENT = 0.5  # closer than this to the target: leave it alone


def report(s: Summary, band: str, calibrated: bool = False) -> str:
    """`calibrated`: calibrated in this app session, so the reminder to calibrate is left out.
    The answer comes first; lines that explain start with two spaces (the app shows them dimmer)."""
    if s.nothing_connected:
        worst = ("SWR is infinite everywhere: all of the signal comes back." if s.best.swr == float("inf")
                 else f"SWR is over 10 everywhere (lowest {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz).")
        lines = [
            f"{band}: {worst}",
            "Check the connection and measure again.",
            "  That looks like nothing connected (an open or a short), or a broken cable or connector.",
            "",
            *_measured(s),
        ]
        return "\n".join(lines) + "\n"

    lines = [f"{band}: best match SWR {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz ({_rating(s.best.swr)})"]
    lines += _trim(s) + [""] + _measured(s) + [""]
    lines += [
        "Across the band: " + " | ".join(f"{_mhz(r.hz)} MHz SWR {_swr(r.swr)}" for r in (s.low, s.middle, s.high)),
        "  SWR (standing wave ratio) says how well the antenna matches your 50-ohm coax:",
        "  1.0 is a perfect match, and the higher it is, the more power bounces back toward the radio.",
        "  On low-loss coax it reads the same at both ends of the cable, so this is the antenna's own match.",
        "",
    ]
    lines += _two_to_one(s) + [""]
    lines += [] if calibrated else [
        "Measured with the NanoVNA's current calibration. If it was made over a different range, or you",
        "added a cable or adapter since, recalibrate for this band (the app's Calibrate tab) for the most",
        "accurate numbers.",
        "",
    ]
    lines += _reactance(s)
    return "\n".join(lines) + "\n"


def _measured(s: Summary) -> list[str]:
    """What the NanoVNA did, in plain words: the reading is the antenna as the radio sees it."""
    return [f"What the NanoVNA measured: {s.points} frequencies from {_mhz(s.low.hz)} to {_mhz(s.high.hz)} MHz",
            "  At each one it sent a tiny test signal into the coax and measured how much came back: the",
            "  antenna as your radio sees it, through this coax and any adapter."]


def _two_to_one(s: Summary) -> list[str]:
    explain = ("  The range where SWR stays at or under 2. A rule of thumb: many radios start cutting power"
               "\n  above about 2:1, so this is roughly what works without a tuner (check your radio's manual).")
    if s.two_to_one is None:
        return [f"2:1 bandwidth: none; SWR never gets down to 2:1 in this band (lowest {_swr(s.best.swr)}).", explain]
    low, high = s.two_to_one
    if s.two_to_one_reaches_low and s.two_to_one_reaches_high:
        return [f"2:1 bandwidth: the whole band ({_mhz(low)}-{_mhz(high)} MHz, and maybe beyond)", explain]
    more = ", and it may go lower" if s.two_to_one_reaches_low else ", and it may go higher" if s.two_to_one_reaches_high else ""
    return [f"2:1 bandwidth: {_mhz(low)}-{_mhz(high)} MHz ({(high - low) / 1000:.0f} kHz{more})", explain]


def _reactance(s: Summary) -> list[str]:
    explain = ["  Impedance is R + jX: R is resistance (power that's radiated, or lost as heat), X is reactance",
               "  (energy stored and handed back each cycle). This is at the radio's end of the coax: the coax",
               "  changes R and X along its length (but not SWR), so X = 0 here is usually not where the",
               "  antenna itself is resonant. Trim by SWR, not by this."]
    if not s.zero_reactance:
        return ["For the curious, impedance:", f"No point in the band has X = 0 (at {_mhz(s.middle.hz)} MHz: {_impedance(s.middle)})."] + explain
    return ["For the curious, impedance:", f"X = 0 at {', '.join(_mhz(hz) for hz in s.zero_reactance)} MHz "
            f"(at the best match: {_impedance(s.best)})"] + explain


def _trim(s: Summary) -> list[str]:
    target = _mhz(s.target_hz)
    if s.flat:
        return [f"No clear dip: SWR stays between {_swr(s.best.swr)} and {_swr(s.worst.swr)} across the band, so there's",
                "  no best match to move, and trimming won't fix it. The antenna is probably resonant well outside",
                "  this band (made for another band, or a multiband antenna that needs a tuner here), or something",
                "  is missing or wrong: a counterpoise or ground an antenna needs, a bad connector, or a lossy cable."]
    explain = ("  This assumes an antenna you can trim (a wire dipole or end-fed, or an adjustable whip): its\n"
               "  best-match frequency moves the opposite way to its length, so longer goes lower. Trim a little at\n"
               "  a time and measure again; the percent is of the whole antenna's length.\n"
               "  A fixed antenna (a rubber duck or a bought whip) can't be trimmed: a best match away from your\n"
               "  target means it was made for somewhat different frequencies.")
    if s.best_at_edge:
        where, fix = ("below", "too long") if s.best_at_edge == "low" else ("above", "too short")
        verb = "Shorten" if s.best_at_edge == "low" else "Lengthen"
        return [f"The best match is at the {s.best_at_edge} edge, so the real best is {where} the band: the antenna is {fix}.",
                f"{verb} the antenna at least {abs(s.trim_percent):.1f}% to move the best match to {target} MHz, then measure again.",
                "  (dipstick doesn't sweep outside the band with an antenna connected, so it can't see how far.)",
                explain]
    if abs(s.trim_percent) < NO_TRIM_PERCENT:
        return [f"No trim needed: the best match is within {NO_TRIM_PERCENT}% of {target} MHz."]
    verb = "Lengthen" if s.trim_percent > 0 else "Shorten"
    return [f"{verb} the antenna about {abs(s.trim_percent):.1f}% to move the best match to {target} MHz.", explain]


def _rating(swr: float) -> str:
    if swr <= 1.5:
        return "excellent"
    if swr <= 2.0:
        return "good"
    if swr <= 5.0:
        return "high: you'll need a tuner"
    return "poor: check the antenna, coax and connectors"


def _impedance(r: Reading) -> str:
    z = r.impedance
    if z.real == float("inf"):
        return "open (infinite impedance)"
    return f"{z.real:.1f} {'+' if z.imag >= 0 else '-'} j{abs(z.imag):.1f} ohms"


def _mhz(hz: float) -> str:
    return f"{hz / 1e6:.3f}"


def _swr(swr: float) -> str:
    return "infinite" if swr == float("inf") else f"{swr:.2f}"


FOOT = 0.3048


def cable_report(r: CableResult, start_hz: int, stop_hz: int, points: int, max_length_m: float,
                 longer: str = "--max-length") -> str:
    """`longer` names the setting for a longer cable: the command's option or the app's field."""
    measured = [f"What the NanoVNA measured: {points} frequencies from {_mhz(start_hz)} to {_mhz(stop_hz)} MHz",
                "  At each one it sent a tiny test signal into the cable and measured the echo from the far end.",
                "  This sweep goes outside the ham bands, which is why the antenna must be off.", ""]
    if r.end == "matched":
        lines = ["Cable: no echo from the far end", "", *measured,
                 "Nothing comes back from the far end (a dummy load, an antenna, or a cable with a lot of loss),",
                 "so the length can't be measured. Leave the far end open or short it, and run again."]
        return "\n".join(lines) + "\n"
    if r.length_m is None:
        answer = f"far end {r.end}; the length couldn't be measured"
    elif r.vf_given:
        answer = f"{r.length_m:.2f} m ({r.length_m / FOOT:.1f} ft) long, far end {r.end}"
    else:
        answer = f"velocity factor {r.vf:.2f}, far end {r.end}"
    lines = [f"Cable: {answer}" + ("" if r.clean else " (rough: see the warning)"), "", *measured]
    lines += [f"Far end: {r.end}",
              "  An open end reflects the signal in phase; a short reflects it inverted. If you left the end open",
              "  and it reads short (or the other way round), look for a fault in the cable or connector.", ""]
    if not r.clean:
        lines += ["Warning: the echo doesn't look like a plain cable with an open or short at the end (an antenna,",
                  "  a load, a fault partway along, or a cable longer than this sweep can measure?). Treat these",
                  "  numbers as rough.", ""]
    if r.length_m is None:
        lines += ["Couldn't measure: the echo's phase went the wrong way. The cable may be longer than "
                  f"{max_length_m:g} m; raise {longer}.", ""]
    elif r.vf is not None and r.length_m is not None:
        lines += _length_lines(r, max_length_m)
    if r.loss_db:
        lines += ["Loss, one way: " + " | ".join(f"{hz // 1_000_000} MHz {db:.2f} dB" for hz, db in sorted(r.loss_db.items())),
                  "  The echo comes back weaker by the cable's loss out and back, so one-way loss is half the",
                  "  return loss. Measured with the end open or shorted; it's close to the loss into a matched load.", ""]
    lines += [f"Measurable up to {max_length_m:g} m with this sweep; for a longer cable raise {longer}."]
    return "\n".join(lines) + "\n"


def _length_lines(r: CableResult, max_length_m: float) -> list[str]:
    speed = ("  The velocity factor is the signal's speed in the cable as a fraction of light's. Solid polyethylene",
             "  coax (RG-58, RG-213) is about 0.66, foam is higher (about 0.78-0.85); check your cable's data sheet.")
    how = ("  From how fast the echo's phase turns as the frequency rises: the longer the round trip, the faster",
           "  it turns. If you expected the cable to be longer, a break or short may be at this distance.")
    feet = r.length_m / FOOT
    return [f"Length: {r.length_m:.2f} m ({feet:.1f} ft) at velocity factor {r.vf:.2f}", *how, *speed, ""] \
        if r.vf_given else \
        [f"Velocity factor: {r.vf:.2f} (for a {r.length_m:.2f} m / {feet:.1f} ft cable)", *speed, ""]


def transformer_report(r: TransformerResult, calibrated: bool = False) -> str:
    """The transformer test in plain words: which bands it matches on, then band by band."""
    every = f"every band from {r.bands[0].band} to {r.bands[-1].band}"
    if not r.unmatched:
        answer = f"SWR 2 or under on {every}."
    elif not r.matched:
        answer = f"SWR above 2 on {every}."
    else:
        answer = f"SWR 2 or under on {', '.join(r.matched)}; above 2 on {', '.join(r.unmatched)}."
    ohms = f"{r.resistor_ohms:g}"
    lines = [
        f"{r.ratio} transformer, {ohms}-ohm resistor: {answer}",
        "  The resistor stands in for the antenna at its best, so this is the transformer's own match:",
        "  with a real antenna on it, the SWR can only be the same or worse.",
        "",
        "Band by band (the sweep point nearest each band's middle):",
        *(f"  {b.band:<5}{_mhz(b.hz):>8} MHz  SWR {_swr(b.swr)}  {_transformer_rating(b.swr)}" for b in r.bands),
        "  SWR 2 is the usual rule of thumb: many radios start cutting power above about 2:1 (check your",
        "  radio's manual).",
    ]
    if r.ideal_swr >= 1.005:  # shows as 1.01 or more
        lines.append(f"  With a {ohms}-ohm resistor, even a perfect {r.ratio} reads SWR {_swr(r.ideal_swr)}, so "
                     "readings near that are as good as it gets.")
    if r.resistor_ohms >= 1000:
        # 2 pF at 28 MHz: 1 / (2 pi x 28e6 x 2e-12) = 2.8 kilohms, about the resistor itself.
        lines += ["  At this many ohms, a couple of picofarads of stray capacitance (the resistor's leads, a clip)",
                  "  matters as much as the resistor on 10 m, so keep the leads short: the high bands may read worse",
                  "  than the transformer really is."]
    lines += ["", f"What the NanoVNA measured: {POINTS} frequencies from {_mhz(START_HZ)} to {_mhz(STOP_HZ)} MHz,",
              "  into the transformer, with the resistor on its output."]
    if not calibrated:
        lines += ["", f"Measured with the NanoVNA's current calibration. For accurate numbers, calibrate over "
                      f"{START_HZ / 1e6:g} to {STOP_HZ / 1e6:g} MHz",
                  "  first (the app's Calibrate tab: HF wide), at the end of any cable or adapter you use to reach",
                  "  the transformer."]
    return "\n".join(lines) + "\n"


_CHOKE_WORDS = {"beyond": "more than this setup measures", "plenty": "plenty", "good": "good", "fair": "fair",
                "weak": "weak", "beneath": "almost no choking"}
# The impedance at each limit: S21 = 100 / (100 + Z), so Z = 100 x (1 / S21 - 1) for a resistive Z.
_DEEPEST_OHMS = 100 * (10 ** (DEEPEST_DB / 20) - 1)        # 9,900: "about 10,000"
_SHALLOWEST_OHMS = 100 * (10 ** (SHALLOWEST_DB / 20) - 1)  # 12.2: "about 12"


def choke_report(r: ChokeResult, calibrated: bool = False, thru: bool = True) -> str:
    """The choke test in plain words. `calibrated`: calibrated here over HF wide with Both ports.
    `thru`: the NanoVNA says its calibration includes a thru and is switched on."""
    groups = [(words, [b.band for b in r.bands if b.rating == rating]) for rating, words in _CHOKE_WORDS.items()]
    lines = ["Choke: " + "; ".join(f"{words} on {', '.join(bands)}" for words, bands in groups if bands) + ".",
             "", "Band by band (the sweep point nearest each band's middle):"]
    for b in r.bands:
        if b.rating == "beyond":
            reading = f"over about {round(_DEEPEST_OHMS, -3):,.0f} ohms: more than this setup measures"
        elif b.rating == "beneath":
            reading = f"under about {_SHALLOWEST_OHMS:.0f} ohms: too little to measure precisely"
        else:
            reading = f"R {b.z.real:,.0f} ohms  |Z| {abs(b.z):,.0f} ohms  {b.rating}"
        lines.append(f"  {b.band:<5}{_mhz(b.hz):>8} MHz  {reading}")
    lines += [
        "  R, the resistive part, is what does the choking: it turns current on the outside of the coax",
        "  into a little heat. The rest of |Z| is reactance, which the feed line's own reactance can cancel.",
        f"  Rules of thumb: |Z| of {WEAK_OHMS:,} ohms is Palomar's minimum (10 times the coax's 50 ohms);",
        f"  R of {GOOD_OHMS:,} ohms is G3TXQ's guideline at a dipole's feed point; {PLENTY_OHMS:,} ohms is what",
        "  K9YC calls plenty for a well matched, balanced antenna. They're rules of thumb, not limits.",
        "  The wires to the choke add stray capacitance, which makes the high bands read lower than the",
        "  choke really is: keep them short.",
        "", f"What the NanoVNA measured: {POINTS} frequencies from {_mhz(START_HZ)} to {_mhz(STOP_HZ)} MHz,",
        "  through the choke from CH0 to CH1.",
    ]
    if not thru:
        lines += ["", "The NanoVNA's calibration has no thru step (or isn't switched on), so these numbers",
                  "  aren't corrected and could be far off. Calibrate first: the Calibrate tab, HF wide, Both ports."]
    elif not calibrated:
        lines += ["", f"Measured with the NanoVNA's current calibration. For accurate numbers, calibrate over "
                      f"{START_HZ / 1e6:g} to {STOP_HZ / 1e6:g} MHz",
                  "  first with the wires you'll use (the Calibrate tab: HF wide, Both ports)."]
    return "\n".join(lines) + "\n"


def _transformer_rating(swr: float) -> str:
    if swr <= 1.5:
        return "excellent"
    if swr <= MATCHED:
        return "good"
    return "high"
