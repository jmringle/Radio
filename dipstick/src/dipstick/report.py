"""A band report in plain words: every number comes with what it means."""

from dipstick.analysis import Summary
from dipstick.cable import CableResult
from dipstick.s11 import Reading

NO_TRIM_PERCENT = 0.5  # closer than this to the target: leave it alone


def report(s: Summary, band: str) -> str:
    lines = [f"{band}: {_mhz(s.low.hz)}-{_mhz(s.high.hz)} MHz, {s.points} points", ""]
    if s.nothing_connected:
        worst = ("SWR is infinite everywhere: all of the signal comes back." if s.best.swr == float("inf")
                 else f"SWR is over 10 everywhere (lowest {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz).")
        lines += [
            worst,
            "  That looks like nothing connected (an open or a short), or a broken cable or connector.",
            "  Check the connection and measure again.",
        ]
        return "\n".join(lines) + "\n"

    lines += [
        f"Best match: SWR {_swr(s.best.swr)} at {_mhz(s.best.hz)} MHz ({_rating(s.best.swr)})",
        "  SWR (standing wave ratio) says how well the antenna matches your 50-ohm coax:",
        "  1.0 is a perfect match, and the higher it is, the more power bounces back toward the radio.",
        "  On low-loss coax it reads the same at both ends of the cable, so this is the antenna's own best match.",
        "",
        "Across the band: " + " | ".join(f"{_mhz(r.hz)} MHz SWR {_swr(r.swr)}" for r in (s.low, s.middle, s.high)),
        "",
    ]
    lines += _two_to_one(s) + [""] + _reactance(s) + [""] + _trim(s) + [""]
    lines += [
        "Measured with the NanoVNA's current calibration. If it was made over a different range, or you",
        "added a cable or adapter since, recalibrate for this band (the app's Calibrate tab) for the most",
        "accurate numbers.",
    ]
    return "\n".join(lines) + "\n"


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
        return [f"No point in the band has X = 0 (at {_mhz(s.middle.hz)} MHz: {_impedance(s.middle)})."] + explain
    return [f"X = 0 at {', '.join(_mhz(hz) for hz in s.zero_reactance)} MHz "
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
        return [f"No trim needed: the best match is within {NO_TRIM_PERCENT}% of {target} MHz.", explain]
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
    lines = [f"Cable: {_mhz(start_hz)}-{_mhz(stop_hz)} MHz sweep, {points} points", ""]
    if r.end == "matched":
        lines += ["Nothing comes back from the far end (a dummy load, an antenna, or a cable with a lot of loss),",
                  "so the length can't be measured. Leave the far end open or short it, and run again."]
        return "\n".join(lines) + "\n"
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
