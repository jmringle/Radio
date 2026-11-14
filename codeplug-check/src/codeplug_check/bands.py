"""Amateur bands a handheld or mobile channel list can reach.

47 CFR 97.301(a), ITU Region 2 (the US), from the eCFR (up to date as of 2026-11-12).
That paragraph covers Technician, General, Advanced and Extra alike: above 50 MHz every
class has the whole band, so no license-class check is needed here. Left out on purpose:
1.25 m's 219-220 MHz (fixed digital message forwarding only, 97.303(l)), and the bands
above 23 cm, which these radios can't reach. Some of 70 cm has location limits
(97.303(m)) that a file can't show; the README says so.
"""

# (name, lowest Hz, highest Hz); both edges are inside the band.
BANDS = [
    ("6m", 50_000_000, 54_000_000),
    ("2m", 144_000_000, 148_000_000),
    ("1.25m", 222_000_000, 225_000_000),
    ("70cm", 420_000_000, 450_000_000),
    ("33cm", 902_000_000, 928_000_000),
    ("23cm", 1_240_000_000, 1_300_000_000),
]


def band_for(hz: int) -> str | None:
    """The amateur band containing `hz`, or None if it's outside them all."""
    return next((name for name, low, high in BANDS if low <= hz <= high), None)
