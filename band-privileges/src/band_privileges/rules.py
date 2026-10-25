"""Rule engine: is a frequency + mode allowed for a US amateur license class?

Values come from 47 CFR Part 97 for ITU Region 2 (the continental US), checked
against eCFR on 2026-10-25 (eCFR current as of 2026-10-22). Only 20 m is
entered so far; the other HF bands are added test-first.

Frequencies are integer Hz so band edges compare exactly (floats can't hold
14.150 exactly). Segment edges are inclusive at both ends for now; see the
README's open questions.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class LicenseClass(Enum):
    TECHNICIAN = "technician"
    GENERAL = "general"
    EXTRA = "extra"


class Mode(Enum):
    CW = "cw"
    PHONE = "phone"
    DATA = "data"  # includes RTTY, as §97.305 groups them
    IMAGE = "image"


def mhz(value: str) -> int:
    """Convert a MHz string like "14.074" to integer Hz without float rounding."""
    return int(Decimal(value) * 1_000_000)


@dataclass(frozen=True)
class Segment:
    low_hz: int
    high_hz: int
    cite: str

    def contains(self, freq_hz: int) -> bool:
        return self.low_hz <= freq_hz <= self.high_hz


@dataclass(frozen=True)
class Result:
    allowed: bool
    reason: str
    citations: tuple[str, ...]


# §97.301: frequencies each class may use (Region 2 column).
PRIVILEGES: dict[LicenseClass, list[Segment]] = {
    LicenseClass.EXTRA: [
        Segment(mhz("14.000"), mhz("14.350"), "§97.301(b)"),
    ],
    LicenseClass.GENERAL: [
        Segment(mhz("14.025"), mhz("14.150"), "§97.301(d)"),
        Segment(mhz("14.225"), mhz("14.350"), "§97.301(d)"),
    ],
    LicenseClass.TECHNICIAN: [],  # no 20 m privileges, §97.301(e)
}

# §97.305(c): where each non-CW mode may be used. CW is allowed anywhere the
# operator has privileges (§97.305(a)), so it has no entry here.
EMISSIONS: dict[Mode, list[Segment]] = {
    Mode.DATA: [Segment(mhz("14.00"), mhz("14.15"), "§97.305(c)(3)(ix)")],
    Mode.PHONE: [Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)")],
    Mode.IMAGE: [Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)")],
}


def _find(segments: list[Segment], freq_hz: int) -> Segment | None:
    return next((s for s in segments if s.contains(freq_hz)), None)


def check(freq_hz: int, mode: Mode, license_class: LicenseClass) -> Result:
    privilege = _find(PRIVILEGES[license_class], freq_hz)
    if privilege is None:
        return Result(
            False,
            f"{license_class.value} privileges do not include this frequency",
            ("§97.301",),
        )
    if mode is Mode.CW:
        return Result(
            True,
            "CW is allowed on any frequency the operator is authorized for",
            (privilege.cite, "§97.305(a)"),
        )
    emission = _find(EMISSIONS[mode], freq_hz)
    if emission is None:
        return Result(
            False,
            f"{mode.value} is not authorized at this frequency",
            (privilege.cite, "§97.305(c)"),
        )
    return Result(True, f"{mode.value} is allowed here", (privilege.cite, emission.cite))
