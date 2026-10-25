"""Rule engine: is a frequency + mode allowed for a US amateur license class?

Values come from 47 CFR Part 97 for ITU Region 2 (the continental US), checked
against eCFR on 2026-10-25 (eCFR current as of 2026-10-22). Only 80/75 m, 40 m and 20 m are
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
        Segment(mhz("3.500"), mhz("4.000"), "§97.301(b)"),  # 80 m + 75 m
        Segment(mhz("7.000"), mhz("7.300"), "§97.301(b)"),
        Segment(mhz("14.000"), mhz("14.350"), "§97.301(b)"),
    ],
    LicenseClass.GENERAL: [
        Segment(mhz("3.525"), mhz("3.600"), "§97.301(d)"),
        Segment(mhz("3.800"), mhz("4.000"), "§97.301(d)"),
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(d)"),
        Segment(mhz("7.175"), mhz("7.300"), "§97.301(d)"),
        Segment(mhz("14.025"), mhz("14.150"), "§97.301(d)"),
        Segment(mhz("14.225"), mhz("14.350"), "§97.301(d)"),
    ],
    LicenseClass.TECHNICIAN: [  # no 20 m privileges
        Segment(mhz("3.525"), mhz("3.600"), "§97.301(e)"),
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(e)"),
    ],
}

# §97.305(c): where each non-CW mode may be used. CW is allowed anywhere the
# operator has privileges (§97.305(a)), so it has no entry here. On a shared
# edge (e.g. 7.100 data) the first matching segment is cited, so keep each list
# in frequency order.
EMISSIONS: dict[Mode, list[Segment]] = {
    Mode.DATA: [
        Segment(mhz("3.500"), mhz("3.600"), "§97.305(c)(3)(i)"),
        Segment(mhz("7.000"), mhz("7.100"), "§97.305(c)(3)(iv)"),
        Segment(mhz("7.100"), mhz("7.125"), "§97.305(c)(3)(vi)"),
        Segment(mhz("14.00"), mhz("14.15"), "§97.305(c)(3)(ix)"),
    ],
    Mode.PHONE: [
        Segment(mhz("3.600"), mhz("4.000"), "§97.305(c)(3)(ii)"),
        Segment(mhz("7.125"), mhz("7.300"), "§97.305(c)(3)(vii)"),
        Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)"),
    ],
    Mode.IMAGE: [
        Segment(mhz("3.600"), mhz("4.000"), "§97.305(c)(3)(ii)"),
        Segment(mhz("7.125"), mhz("7.300"), "§97.305(c)(3)(vii)"),
        Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)"),
    ],
}


@dataclass(frozen=True)
class Restriction:
    """A §97.307 rule that denies some modes in a segment, for some classes."""

    segment: Segment
    classes: frozenset[LicenseClass]
    denied_modes: frozenset[Mode]
    reason: str

    def applies(self, freq_hz: int, mode: Mode, license_class: LicenseClass) -> bool:
        return (
            license_class in self.classes
            and mode in self.denied_modes
            and self.segment.contains(freq_hz)
        )


_TECH = frozenset({LicenseClass.TECHNICIAN})
_ALL_CLASSES = frozenset(LicenseClass)
_NON_CW = frozenset({Mode.PHONE, Mode.DATA, Mode.IMAGE})

# Checked in order; the first match decides, so Technician rules come first.
RESTRICTIONS: list[Restriction] = [
    # §97.307(f)(9): Technicians may only use CW.
    Restriction(
        Segment(mhz("3.525"), mhz("3.600"), "§97.307(f)(9)"),
        _TECH,
        _NON_CW,
        "technicians may only use CW here",
    ),
    Restriction(
        Segment(mhz("7.025"), mhz("7.125"), "§97.307(f)(9)"),
        _TECH,
        _NON_CW,
        "technicians may only use CW here",
    ),
    # §97.305(c)(3)(v) authorizes phone/image on 7.075-7.100 MHz, but
    # §97.307(f)(11) limits it to Region 2 stations west of 130° W or south of
    # 20° N (e.g. Hawaii). v1 assumes a continental US station, so it's left
    # out of EMISSIONS and denied here with the real reason.
    Restriction(
        Segment(mhz("7.075"), mhz("7.100"), "§97.307(f)(11)"),
        _ALL_CLASSES,
        frozenset({Mode.PHONE, Mode.IMAGE}),
        "phone and image here are only for stations west of 130° W or south of 20° N",
    ),
]


def _find(segments: list[Segment], freq_hz: int) -> Segment | None:
    return next((s for s in segments if s.contains(freq_hz)), None)


def check(freq_hz: int, mode: Mode, license_class: LicenseClass) -> Result:
    # Order matters: privileges first, then CW (allowed anywhere with
    # privileges), then RESTRICTIONS before EMISSIONS, so a Technician on a
    # shared edge like 7.125 is denied (the safe reading).
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
    for restriction in RESTRICTIONS:
        if restriction.applies(freq_hz, mode, license_class):
            return Result(
                False,
                restriction.reason,
                (privilege.cite, restriction.segment.cite),
            )
    emission = _find(EMISSIONS[mode], freq_hz)
    if emission is None:
        return Result(
            False,
            f"{mode.value} is not authorized at this frequency",
            (privilege.cite, "§97.305(c)"),
        )
    return Result(True, f"{mode.value} is allowed here", (privilege.cite, emission.cite))
