"""Two balun tests: a transformer (unun or voltage balun) with a resistor on its output, port 1 on its input;
and a choke (current balun) in series between CH0 and CH1 (bottom of the file).

An ideal n:1 transformer with a resistor R on its output looks like R / n at its input. With
R = 50 x n (2450 ohms on a 49:1, 50 ohms on a 1:1) the NanoVNA should see 50 ohms, so the SWR it
reads on each band shows how well the transformer itself does there. The resistor stands in for
the antenna at its best, so a real antenna only does worse.
"""

import math
from dataclasses import dataclass

from dipstick.bands import BANDS
from dipstick.s11 import Reading, Z0

RATIOS = {"1:1": 1, "4:1": 4, "9:1": 9, "49:1": 49}
# 160 m to 6 m in one scan: 0.522 MHz between points, fine for a transformer, which changes slowly.
START_HZ, STOP_HZ, POINTS = 1_800_000, 54_000_000, 101
HF_BANDS = [name for name, (low, high) in BANDS.items() if START_HZ <= low and high <= STOP_HZ]
MATCHED = 2.0  # the app's usual rule of thumb: many radios cut power above about 2:1
NOTHING = 10.0  # SWR over this at every point: nothing like the resistor is on the output
MAX_IDEAL_SWR = 1.5  # a resistor further off than this hides what the transformer does


@dataclass(frozen=True)
class BandSwr:
    band: str
    hz: int  # the sweep point nearest the band's middle
    swr: float


@dataclass(frozen=True)
class TransformerResult:
    ratio: str
    resistor_ohms: float
    ideal_swr: float  # what a perfect transformer would read with this resistor
    bands: list[BandSwr]  # 160 m to 6 m, in order

    @property
    def matched(self) -> list[str]:
        return [b.band for b in self.bands if b.swr <= MATCHED]

    @property
    def unmatched(self) -> list[str]:
        return [b.band for b in self.bands if b.swr > MATCHED]


def ideal_swr(ratio: str, resistor_ohms: float) -> float:
    seen = resistor_ohms / RATIOS[ratio]
    return max(seen / Z0, Z0 / seen)


def analyze_transformer(readings: list[Reading], ratio: str, resistor_ohms: float) -> TransformerResult:
    if all(r.swr > NOTHING for r in readings):
        raise ValueError(f"SWR is over {NOTHING:g} across the whole sweep. Is the resistor connected to the "
                         "transformer's output, and the transformer's input to the NanoVNA?")
    bands = []
    for band in HF_BANDS:
        low, high = BANDS[band]
        nearest = min(readings, key=lambda r: abs(r.hz - (low + high) / 2))
        bands.append(BandSwr(band, nearest.hz, nearest.swr))
    return TransformerResult(ratio, resistor_ohms, ideal_swr(ratio, resistor_ohms), bands)


# --- the choke test: a current balun in series between CH0 and CH1 (S21) ----------------------------
# A series impedance Z between two 50-ohm ports passes S21 = 2 x 50 / (2 x 50 + Z), so
# Z = 2 x 50 x (1 - S21) / S21: K6JCA's series-through method (k6jca.blogspot.com, 2020-07).
# Choking guidelines (all read 2026-11-17):
WEAK_OHMS = 500     # |Z| under 10 x the line's 50 ohms: under Palomar's minimum (AK6R, "Choosing a Feedline Choke", 2022)
GOOD_OHMS = 1000    # R of at least 1000 at a dipole's feed point: G3TXQ, quoted by K6JCA (2018-06)
PLENTY_OHMS = 5000  # "5K ohms is plenty" for a well matched, balanced antenna: K9YC, quoted by K6JCA
# What this setup can't resolve. Under 1 dB (about 12 ohms) the reading is mostly the calibration's
# error. Over 40 dB (about 10 kilohms) it nears the noise floor: nanovna.com gives the NanoVNA 40 dB
# of dynamic range at 900 MHz, so 40 dB is a cautious limit at HF, where it does better.
SHALLOWEST_DB = 1.0
DEEPEST_DB = 40.0


@dataclass(frozen=True)
class BandChoke:
    band: str
    hz: int  # the sweep point nearest the band's middle
    loss_db: float
    z: complex  # the choke's impedance: R (the real part) does the choking
    rating: str  # beneath, weak, fair, good, plenty or beyond


@dataclass(frozen=True)
class ChokeResult:
    bands: list[BandChoke]  # 160 m to 6 m, in order


def choke_impedance(s21: complex) -> complex:
    return 2 * Z0 * (1 - s21) / s21


def choke_rating(z: complex, loss_db: float) -> str:
    if loss_db > DEEPEST_DB:
        return "beyond"
    if loss_db < SHALLOWEST_DB:
        return "beneath"
    if abs(z) < WEAK_OHMS:
        return "weak"
    if z.real >= PLENTY_OHMS:
        return "plenty"
    return "good" if z.real >= GOOD_OHMS else "fair"


def analyze_choke(throughs: list) -> ChokeResult:
    if all(t.loss_db > DEEPEST_DB for t in throughs):
        raise ValueError(f"Almost nothing arrives at CH1 across the whole sweep (over {DEEPEST_DB:g} dB down). "
                         "Is the choke connected between CH0 and CH1, as the wiring shows?")
    bands = []
    for band in HF_BANDS:
        low, high = BANDS[band]
        t = min(throughs, key=lambda t: abs(t.hz - (low + high) / 2))
        z = choke_impedance(t.s21) if t.s21 else complex(math.inf)
        bands.append(BandChoke(band, t.hz, t.loss_db, z, choke_rating(z, t.loss_db)))
    return ChokeResult(bands)
