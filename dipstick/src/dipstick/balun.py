"""Transformer test for ununs and voltage baluns: a resistor on the output, port 1 on the input.

An ideal n:1 transformer with a resistor R on its output looks like R / n at its input. With
R = 50 x n (2450 ohms on a 49:1, 50 ohms on a 1:1) the NanoVNA should see 50 ohms, so the SWR it
reads on each band shows how well the transformer itself does there. The resistor stands in for
the antenna at its best, so a real antenna only does worse.
"""

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
