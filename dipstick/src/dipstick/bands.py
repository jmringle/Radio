"""Amateur bands an antenna sweep may use.

When the NanoVNA sweeps an antenna, it puts a very small signal on the air at every frequency
it steps through, so antenna sweeps stay inside one amateur band. Whole bands, as you chose
(2026-11-15): you control the sweep, and the signal is tiny. Wide sweeps for feed line checks
go into a cable with no antenna, and are handled separately.

Band edges, ITU Region 2 (eCFR): HF from 47 CFR 97.301(b) (read 2026-11-15); 6 m and up from
97.301(a) (read 2026-11-12, for codeplug-check). Left out: 60 m (five channels, not a band,
97.303(h)); 2200 m and 630 m (need prior notification, 97.303(g)); 1.25 m's 219-220 MHz
(fixed digital message forwarding only, 97.303(l)); bands above the NanoVNA-H's range.
"""

BANDS = {  # name: (lowest Hz, highest Hz), both edges inside the band
    "160m": (1_800_000, 2_000_000),
    "80m": (3_500_000, 4_000_000),  # includes 75 m
    "40m": (7_000_000, 7_300_000),
    "30m": (10_100_000, 10_150_000),
    "20m": (14_000_000, 14_350_000),
    "17m": (18_068_000, 18_168_000),
    "15m": (21_000_000, 21_450_000),
    "12m": (24_890_000, 24_990_000),
    "10m": (28_000_000, 29_700_000),
    "6m": (50_000_000, 54_000_000),
    "2m": (144_000_000, 148_000_000),
    "1.25m": (222_000_000, 225_000_000),
    "70cm": (420_000_000, 450_000_000),
    "33cm": (902_000_000, 928_000_000),
    "23cm": (1_240_000_000, 1_300_000_000),
}


def band_range(band: str) -> tuple[int, int]:
    if band not in BANDS:
        raise ValueError(f"Unknown band {band!r}; choose one of {', '.join(BANDS)}")
    return BANDS[band]


def check_antenna_sweep(start_hz: int, stop_hz: int) -> None:
    """Refuse an antenna sweep that isn't entirely inside one amateur band."""
    if start_hz < stop_hz and any(low <= start_hz and stop_hz <= high for low, high in BANDS.values()):
        return
    raise ValueError(f"An antenna sweep must stay inside one amateur band, from low to high; "
                     f"{start_hz} to {stop_hz} Hz doesn't")
