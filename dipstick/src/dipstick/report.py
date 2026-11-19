"""A band report in plain words: every number comes with what it means."""

from dipstick.analysis import TWO_TO_ONE, Summary
from dipstick.bands import BANDS
from dipstick.balun import (DEEPEST_DB, GOOD_OHMS, MATCHED, PLENTY_OHMS, POINTS, SHALLOWEST_DB, START_HZ, STOP_HZ,
                            WEAK_OHMS, ChokeResult, LossResult, TransformerResult)
from dipstick.cable import CableResult
from dipstick.s11 import Reading

NO_TRIM_PERCENT = 0.5  # closer than this to the target: leave it alone


def report(s: Summary, band: str, calibrated: bool = False, length_m: float | None = None) -> str:
    """The whole report, as the command prints it: the Tune section, then More detail."""
    tune, detail = report_parts(s, band, calibrated, length_m)
    return tune + "\n" + detail


def report_parts(s: Summary, band: str, calibrated: bool = False, length_m: float | None = None,
                 length_name: str = "--antenna-length") -> tuple[str, str]:
    """(Tune, More detail). Tune is only what you act on: the result, what to do, what a tuner can
    reach. More detail is everything else, so nothing is lost (display review 2026-11-19).
    `calibrated`: calibrated in this app session, so the reminder to calibrate is left out.
    `length_m`: the antenna's length if given, for the trim in inches (otherwise estimated);
    `length_name`: where to give it (the command's option or the app's field).
    Lines that explain start with two spaces (the app shows them dimmer)."""
    if s.nothing_connected:
        worst = ("SWR is infinite everywhere: all of the signal comes back." if s.best.swr == float("inf")
                 else f"SWR is over 10 everywhere (lowest {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz).")
        tune = [f"{band}: {worst}", "Check the connection and measure again.",
                "  That looks like nothing connected (an open or a short), or a broken cable or connector."]
        return _text(tune), _text(_measured(s))

    trim, trim_why = _trim(s, length_m, length_name)
    at = s.at_target
    tune = [f"{band}: best match SWR {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz ({_rating(s.best.swr, band)})",
            *trim, f"At {_mhz(at.hz)} MHz now: SWR {_swr(at.swr)}, {tuner_need(at.swr, band)}.", *_bandwidths(s, band)]
    if not calibrated:
        tune.append(f"Calibration: the NanoVNA's current one. For the most accurate numbers, recalibrate for {band} "
                    "(the app's Calibrate tab).")
    detail = [*_measured(s), "",
              "Across the band: " + " | ".join(f"{_mhz(r.hz)} MHz SWR {_swr(r.swr)}" for r in (s.low, s.middle, s.high)),
              "  SWR (standing wave ratio) says how well the antenna matches your 50-ohm coax:",
              "  1.0 is a perfect match, and the higher it is, the more power bounces back toward the radio.",
              "  On low-loss coax it reads the same at both ends of the cable, so this is the antenna's own match.", "",
              *_bandwidths_why(band), ""]
    if trim_why:
        detail += ["How trimming works:", *trim_why, ""]
    if not calibrated:
        detail += ["About calibration:",
                   "  The NanoVNA corrects every reading with its calibration. If that was made over a different",
                   "  range, or you added a cable or adapter since, the numbers can be off.", ""]
    detail += _reactance(s)
    return _text(tune), _text(detail)


def _text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _measured(s: Summary) -> list[str]:
    """What the NanoVNA did, in plain words: the reading is the antenna as the radio sees it."""
    return [f"What the NanoVNA measured: {s.points} frequencies from {_mhz(s.low.hz)} to {_mhz(s.high.hz)} MHz",
            "  At each one it sent a tiny test signal into the coax and measured how much came back: the",
            "  antenna as your radio sees it, through this coax and any adapter."]


# Tuner words, from typical gear rather than one radio (approved 2026-11-17, docs/plans/multiband-and-compare.md):
# built-in tuners (Icom IC-7300, Yaesu FT-991A manuals) match 16.7-150 ohms, stated as SWR 3:1; a wide-range
# external tuner (LDG Z-100Plus manual) 6-800 ohms on HF, about 8:1 on its tighter side, but only 16-150 ohms
# (about 3:1) on 6 m.
BUILT_IN = 3.0
WIDE_RANGE = 8.0
_VHF_UP_HZ = 54_000_000  # above 6 m: VHF and UHF radios rarely have a tuner (a judgement, 2026-11-19)


def tuner_need(swr: float, band: str) -> str:
    """What it takes to use this SWR, in the same words everywhere a band is rated."""
    if swr <= TWO_TO_ONE:
        return "no tuner needed"
    if _vhf_up(band):
        return "most VHF and UHF radios have no tuner: trim or fix the antenna"
    if swr <= BUILT_IN:
        return "within most built-in tuners"
    if swr <= WIDE_RANGE and band != "6m":
        return "needs a wide-range external tuner"
    return "beyond most tuners: check the antenna, coax and connectors"


def _vhf_up(band: str) -> bool:
    return band in BANDS and BANDS[band][0] > _VHF_UP_HZ


def _bandwidths(s: Summary, band: str) -> list[str]:
    lines = [_bandwidth("2:1 bandwidth (no tuner needed)", "2:1", s.two_to_one, s.two_to_one_reaches_low,
                        s.two_to_one_reaches_high, s.best.swr)]
    whole = s.two_to_one_reaches_low and s.two_to_one_reaches_high
    if not whole and not _vhf_up(band):
        lines.append(_bandwidth("3:1 bandwidth (most built-in tuners)", "3:1", s.three_to_one,
                                s.three_to_one_reaches_low, s.three_to_one_reaches_high, None))
    return lines


def _bandwidth(label: str, ratio: str, span: tuple[float, float] | None, reaches_low: bool, reaches_high: bool,
               lowest: float | None) -> str:
    """`lowest`: the best SWR, said when the range is empty (once, on the 2:1 line)."""
    if span is None:
        return f"{label}: none" + (f"; SWR never gets down to {ratio} in this band (lowest {_swr(lowest)})"
                                   if lowest is not None else "")
    low, high = span
    if reaches_low and reaches_high:
        return f"{label}: the whole band ({_mhz(low)}-{_mhz(high)} MHz, and maybe beyond)"
    more = ", and it may go lower" if reaches_low else ", and it may go higher" if reaches_high else ""
    return f"{label}: {_mhz(low)}-{_mhz(high)} MHz ({(high - low) / 1000:.0f} kHz{more})"


def _bandwidths_why(band: str) -> list[str]:
    lines = ["What the bandwidths mean:",
             "  The 2:1 bandwidth is where SWR stays at or under 2. A rule of thumb: many radios",
             "  start cutting power above about 2:1, so this is roughly what works without a tuner (check your",
             "  radio's manual)."]
    if _vhf_up(band):
        return lines + ["  Most VHF and UHF radios have no tuner, so on this band the antenna itself has to match."]
    return lines + [
        "  The 3:1 bandwidth is where most radios' built-in tuners can still match (their manuals say about",
        "  3:1); a wide-range external tuner reaches about 8:1 on HF" + (", but only about 3:1 on 6 m." if band == "6m" else "."),
        "  A tuner's range is really an impedance range, so these SWR limits are approximate. A tuner at the",
        "  radio protects the radio but doesn't fix the antenna, and the coax still loses more at high SWR.",
        "  Check your own tuner's manual."]


def _reactance(s: Summary) -> list[str]:
    explain = ["  Impedance is R + jX: R is resistance (power that's radiated, or lost as heat), X is reactance",
               "  (energy stored and handed back each cycle). This is at the radio's end of the coax: the coax",
               "  changes R and X along its length (but not SWR), so X = 0 here is usually not where the",
               "  antenna itself is resonant. Trim by SWR, not by this."]
    if not s.zero_reactance:
        return ["For the curious, impedance:", f"No point in the band has X = 0 (at {_mhz(s.middle.hz)} MHz: {_impedance(s.middle)})."] + explain
    return ["For the curious, impedance:", f"X = 0 at {', '.join(_mhz(hz) for hz in s.zero_reactance)} MHz "
            f"(at the best match: {_impedance(s.best)})"] + explain


HALF_WAVE_FEET_MHZ = 468  # a half-wave wire is about 468 / MHz feet long: the usual rule of thumb
INCH = 0.0254


def _how_much(s: Summary, length_m: float | None, length_name: str, bound: str) -> tuple[str, str]:
    """The trim in inches and cm, and where the length came from. `bound`: "about" or "at least".
    The percent is of the antenna as it is now, so the estimate is at the best match's frequency."""
    if length_m is None:
        feet = HALF_WAVE_FEET_MHZ / (s.best.hz / 1e6)
        length, source = feet * FOOT, (
            f"  Inches assume a half-wave wire, a dipole or an end-fed on its main band (about {feet:.1f} ft at "
            f"{_mhz(s.best.hz)} MHz, from the 468 / MHz rule of thumb); for any other antenna, give its length "
            f"({length_name}).")
    else:
        length, source = length_m, f"  From the antenna length you gave: {length_m / FOOT:.1f} ft ({length_m:.2f} m)."
    whole = length * abs(s.trim_percent) / 100
    ends = "off each end" if s.trim_percent < 0 else "on each end"
    return f"{bound} {_inch_cm(whole)}; on a dipole, {_inch_cm(whole / 2)} {ends}", source


def _inch_cm(meters: float) -> str:
    inches, cm = meters / INCH, meters * 100
    return f"{inches:.{1 if inches < 10 else 0}f} in / {cm:.{1 if cm < 10 else 0}f} cm"


def _trim(s: Summary, length_m: float | None = None, length_name: str = "--antenna-length") -> tuple[list[str], list[str]]:
    """(What to do, for Tune; how trimming works, for More detail)."""
    target = _mhz(s.target_hz)
    if s.flat:  # what to check is the thing to do, so it stays in Tune
        return [f"No clear dip: SWR stays between {_swr(s.best.swr)} and {_swr(s.worst.swr)} across the band, so there's",
                "  no best match to move, and trimming won't fix it. The antenna is probably resonant well outside",
                "  this band (made for another band, or a multiband antenna that needs a tuner here), or something",
                "  is missing or wrong: a counterpoise or ground an antenna needs, a bad connector, or a lossy cable."], []
    explain = ["  This assumes an antenna you can trim (a wire dipole or end-fed, or an adjustable whip): its",
               "  best-match frequency moves the opposite way to its length, so longer goes lower. Trim a little at",
               "  a time and measure again; the percent is of the whole antenna's length.",
               "  A fixed antenna (a rubber duck or a bought whip) can't be trimmed: a best match away from your",
               "  target means it was made for somewhat different frequencies."]
    if s.best_at_edge:
        where, fix = ("below", "too long") if s.best_at_edge == "low" else ("above", "too short")
        verb = "Shorten" if s.best_at_edge == "low" else "Lengthen"
        amount, source = _how_much(s, length_m, length_name, "at least")
        return [f"The best match is at the {s.best_at_edge} edge, so the real best is {where} the band: the antenna is {fix}.",
                f"{verb} the antenna at least {abs(s.trim_percent):.1f}% ({amount}) to move the best match to {target} MHz, "
                "then measure again.", source], \
            ["  dipstick doesn't sweep outside the band with an antenna connected, so it can't see how far:",
             "  that's why it says \"at least\".", *explain]
    if abs(s.trim_percent) < NO_TRIM_PERCENT:
        return [f"No trim needed: the best match is within {NO_TRIM_PERCENT}% of {target} MHz."], []
    verb = "Lengthen" if s.trim_percent > 0 else "Shorten"
    amount, source = _how_much(s, length_m, length_name, "about")
    return [f"{verb} the antenna about {abs(s.trim_percent):.1f}% ({amount}) to move the best match to {target} MHz.",
            source], explain


def _rating(swr: float, band: str) -> str:
    if swr <= 1.5:
        return "excellent"
    if swr <= TWO_TO_ONE:
        return "good"
    need = tuner_need(swr, band)
    return f"{'poor' if need.startswith('beyond') else 'high'}: {need}"


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
    return "\n".join(lines + _two_port_note(calibrated, thru)) + "\n"


def _two_port_note(calibrated: bool, thru: bool) -> list[str]:
    if not thru:
        return ["", "The NanoVNA's calibration has no thru step (or isn't switched on), so these numbers",
                "  aren't corrected and could be far off. Calibrate first: the Calibrate tab, HF wide, Both ports."]
    if not calibrated:
        return ["", f"Measured with the NanoVNA's current calibration. For accurate numbers, calibrate over "
                    f"{START_HZ / 1e6:g} to {STOP_HZ / 1e6:g} MHz",
                "  first with the wires you'll use (the Calibrate tab: HF wide, Both ports)."]
    return []


def loss_report(r: LossResult, calibrated: bool = False, thru: bool = True) -> str:
    """The through-loss test in plain words; `calibrated` and `thru` as for choke_report."""
    pair = r.connection == "back-to-back"
    clean = [b for b in r.bands if b.status == "loss"]
    if clean:
        most, least = max(clean, key=lambda b: b.loss_db), min(clean, key=lambda b: b.loss_db)
        answer = (f"most {max(most.loss_db, 0):.2f} dB on {most.band}, "
                  f"least {max(least.loss_db, 0):.2f} dB on {least.band}.")
    else:
        answer = "no band read cleanly; see below."
    lines = [f"Through loss, {'each of two transformers back to back' if pair else 'direct'}: {answer}",
             "", "Band by band (the sweep point nearest each band's middle):"]
    for b in r.bands:
        if b.status == "beyond":
            reading = f"over {DEEPEST_DB / (2 if pair else 1):g} dB{' each' if pair else ''}: almost nothing arrives"
        elif b.status == "gain":
            reading = (f"reads {-b.loss_db:.2f} dB of gain, which a passive item can't have: "
                       "recheck the thru calibration")
        elif b.loss_db <= 0:
            reading = "about 0 dB: no loss this setup can measure"
        else:
            lost = 100 * (1 - 10 ** (-b.loss_db / 10))
            reading = f"{b.loss_db:.2f} dB  ({'under 1' if lost < 1 else f'{lost:.0f}'}% of the power doesn't arrive)"
        lines.append(f"  {b.band:<5}{_mhz(b.hz):>8} MHz  {reading}")
    lines.append("  3 dB is half the power; 1 dB is about a fifth (21%); 0.1 dB is about 2%.")
    if pair:
        lines += ["  Each transformer's loss is half the pair's total, if the two are identical; the wire",
                  "  between them adds a little. What doesn't arrive was turned into heat or reflected."]
    else:
        lines += ["  Direct suits a 1:1 balun, a cable or a filter: things meant for 50 ohms at both ends.",
                  "  A step-up transformer such as a 49:1 alone reflects most of the signal and reads as a big",
                  "  loss; test it with a resistor (the transformer test) or as a back to back pair."]
    lines += ["", f"What the NanoVNA measured: {POINTS} frequencies from {_mhz(START_HZ)} to {_mhz(STOP_HZ)} MHz,",
              f"  through the {'pair' if pair else 'item'} from CH0 to CH1."]
    return "\n".join(lines + _two_port_note(calibrated, thru)) + "\n"


def _transformer_rating(swr: float) -> str:
    if swr <= 1.5:
        return "excellent"
    if swr <= MATCHED:
        return "good"
    return "high"
