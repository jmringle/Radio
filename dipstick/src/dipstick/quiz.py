""""Check yourself": a few questions about your own sweep, answered by the same analysis as the report.

Each question has 2 to 4 choices, the index of the right one, and why, with your numbers. A question
that doesn't apply is left out (no trim question for a flat curve; nothing when nothing is connected).
"""

from dataclasses import dataclass

from dipstick.analysis import Summary
from dipstick.cable import CableResult
from dipstick.report import NO_TRIM_PERCENT

RADIO_W = 20  # a typical HF radio's power, for the cable loss question
FOAM_VF, SOLID_VF = 0.82, 0.66  # velocity factors to compare with: foam and solid polyethylene coax


@dataclass(frozen=True)
class Question:
    ask: str
    choices: tuple[str, ...]
    answer: int  # index into choices
    why: str


def antenna_questions(s: Summary) -> list[Question]:
    if s.nothing_connected:
        return []
    return [q for q in (_trim(s), _reflected(s), _tuner(s)) if q]


def cable_questions(r: CableResult) -> list[Question]:
    if r.end == "matched":
        return []
    return [q for q in (_speed(r), _loss(r)) if q]


def _mhz(hz: float) -> str:
    return f"{hz / 1e6:.3f}"


def _trim(s: Summary) -> Question | None:
    if s.flat:  # no dip to move: trimming won't fix it
        return None
    best, target = _mhz(s.best.hz), _mhz(s.target_hz)
    choices = ("Longer", "Shorter", "Leave it as it is")
    ask = (f"Your best match is at {best} MHz and your target is {target} MHz. To move the best match to "
           "your target, should the antenna be:")
    if s.best_at_edge:
        shorter = s.best_at_edge == "low"
        amount = f"at least {abs(s.trim_percent):.1f}%"
        where = f"The lowest SWR is at the band's {s.best_at_edge} edge, so the real best match is " \
                f"{'below' if shorter else 'above'} the band, {'below' if shorter else 'above'} your target."
    elif abs(s.trim_percent) < NO_TRIM_PERCENT:
        return Question(ask, choices, 2, f"The best match is within {NO_TRIM_PERCENT}% of your target: close "
                                         "enough to leave alone.")
    else:
        shorter = s.trim_percent < 0
        amount = f"about {abs(s.trim_percent):.1f}%"
        where = f"The best match is {'below' if shorter else 'above'} your target."
    return Question(ask, choices, 1 if shorter else 0,
                    f"{where} A longer antenna resonates lower, so to move the best match "
                    f"{'up' if shorter else 'down'}, make it {'shorter' if shorter else 'longer'}: {amount}.")


def _reflected(s: Summary) -> Question:
    swr = s.best.swr
    voltage = (swr - 1) / (swr + 1)  # the reflection, as a share of the voltage
    percent = 100 * voltage ** 2  # power goes as the voltage squared
    choices = ("Under 1%", "About 1% to 10%", "About 10% to 25%", "Over 25%")
    answer = 0 if percent < 1 else 1 if percent < 10 else 2 if percent < 25 else 3
    return Question(f"At your best match the SWR is {swr:.2f}. About how much of the power sent up the coax "
                    "comes back?", choices, answer,
                    f"{percent:.1f}% comes back. The reflection is (SWR - 1) / (SWR + 1) = {voltage:.2f} of the "
                    "voltage, and power goes as its square. Even SWR 2 sends back only about 11%.")


def _tuner(s: Summary) -> Question:
    # The band edge farther from the best match: the harder case.
    edge = s.high if s.high.hz - s.best.hz >= s.best.hz - s.low.hz else s.low
    fine = edge.swr <= 2
    return Question(f"Could you use {_mhz(edge.hz)} MHz without a tuner, if your radio wants an SWR of 2 or less?",
                    ("Yes", "No"), 0 if fine else 1,
                    f"The SWR at {_mhz(edge.hz)} MHz is {edge.swr:.2f}, {'at or under' if fine else 'over'} 2. "
                    "The report's 2:1 bandwidth gives the same answer.")


def _speed(r: CableResult) -> Question | None:
    if r.length_m is None:
        return None
    if not r.vf_given:  # the length was given, and the velocity factor worked out from it
        return Question(f"Dipstick worked out velocity factor {r.vf:.2f} from the {r.length_m:.2f} m you gave. "
                        "If the cable were really longer than that, its velocity factor would be:",
                        ("Higher", "Lower", "The same"), 0,
                        "The echo took the time it took. For a longer cable to fit in that time, the signal must "
                        "move faster, which is a higher velocity factor (velocity factor = length / (delay x the "
                        "speed of light)).")
    other = FOAM_VF if r.vf < (FOAM_VF + SOLID_VF) / 2 else SOLID_VF
    other_length = r.length_m * other / r.vf
    longer = other > r.vf
    return Question(f"This cable measured {r.length_m:.2f} m at velocity factor {r.vf:.2f}. If it were coax with "
                    f"velocity factor {other:.2f} instead, the same echo would mean a cable that's:",
                    ("Longer", "Shorter", "The same length"), 0 if longer else 1,
                    f"The echo's delay stays the same. A signal moves {'faster' if longer else 'slower'} in coax "
                    f"with a {'higher' if longer else 'lower'} velocity factor, so in that time it covers "
                    f"{'more' if longer else 'less'} cable: {r.length_m:.2f} x {other:.2f} / {r.vf:.2f} = "
                    f"{other_length:.2f} m.")


def _loss(r: CableResult) -> Question | None:
    if not r.loss_db:
        return None
    hz = 28_000_000 if 28_000_000 in r.loss_db else max(r.loss_db)  # 10 m if the sweep reached it
    db = r.loss_db[hz]
    arrives = RADIO_W * 10 ** (-db / 10)
    twice = RADIO_W * 10 ** (-2 * db / 10)  # the echo's round trip: a common mix-up
    right = f"{arrives:.1f} W"
    choices = [f"{RADIO_W:.1f} W", right, f"{twice:.1f} W"]
    if len(set(choices)) < 3:  # so little loss that the choices round to the same number
        return None
    shift = round(db * 100) % 3  # where the right one sits varies, but the same cable always asks the same
    choices = choices[shift:] + choices[:shift]
    mhz = hz // 1_000_000
    return Question(f"A {RADIO_W} W radio feeds this cable at {mhz} MHz. About how much power reaches the far end?",
                    tuple(choices), choices.index(right),
                    f"One-way loss at {mhz} MHz is {db:.2f} dB: {RADIO_W} W x 10^(-{db:.2f} / 10) = {right} "
                    "arrives, and the rest warms the cable. Twice the loss would be the echo's round trip, out "
                    "and back, not the trip to the antenna.")
