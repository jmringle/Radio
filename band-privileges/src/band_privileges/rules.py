"""Rule engine: is a frequency + mode allowed for a US amateur license class?

Values come from 47 CFR Part 97 for ITU Region 2 (the continental US), checked
against eCFR on 2026-10-25 (eCFR current as of 2026-10-22). Every v1 band
(160-10 m, except 60 m) is entered.

Frequencies are integer Hz so band edges compare exactly (floats can't hold
14.150 exactly). Segment edges are inclusive at both ends, as decided in the
README's acceptance criteria.
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
    notes: tuple[str, ...] = ()


# §97.301: frequencies each class may use (Region 2 column). Every table in this
# module is kept in frequency order (a test checks this).
PRIVILEGES: dict[LicenseClass, list[Segment]] = {
    LicenseClass.EXTRA: [
        Segment(mhz("1.800"), mhz("2.000"), "§97.301(b)"),
        Segment(mhz("3.500"), mhz("4.000"), "§97.301(b)"),  # 80 m + 75 m
        Segment(mhz("7.000"), mhz("7.300"), "§97.301(b)"),
        Segment(mhz("10.100"), mhz("10.150"), "§97.301(b)"),
        Segment(mhz("14.000"), mhz("14.350"), "§97.301(b)"),
        Segment(mhz("18.068"), mhz("18.168"), "§97.301(b)"),
        Segment(mhz("21.000"), mhz("21.450"), "§97.301(b)"),
        Segment(mhz("24.890"), mhz("24.990"), "§97.301(b)"),
        Segment(mhz("28.000"), mhz("29.700"), "§97.301(b)"),
    ],
    LicenseClass.GENERAL: [
        Segment(mhz("1.800"), mhz("2.000"), "§97.301(d)"),
        Segment(mhz("3.525"), mhz("3.600"), "§97.301(d)"),
        Segment(mhz("3.800"), mhz("4.000"), "§97.301(d)"),
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(d)"),
        Segment(mhz("7.175"), mhz("7.300"), "§97.301(d)"),
        Segment(mhz("10.100"), mhz("10.150"), "§97.301(d)"),
        Segment(mhz("14.025"), mhz("14.150"), "§97.301(d)"),
        Segment(mhz("14.225"), mhz("14.350"), "§97.301(d)"),
        Segment(mhz("18.068"), mhz("18.168"), "§97.301(d)"),
        Segment(mhz("21.025"), mhz("21.200"), "§97.301(d)"),
        Segment(mhz("21.275"), mhz("21.450"), "§97.301(d)"),
        Segment(mhz("24.890"), mhz("24.990"), "§97.301(d)"),
        Segment(mhz("28.000"), mhz("29.700"), "§97.301(d)"),
    ],
    LicenseClass.TECHNICIAN: [  # no 20 m privileges
        Segment(mhz("3.525"), mhz("3.600"), "§97.301(e)"),
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(e)"),
        Segment(mhz("21.025"), mhz("21.200"), "§97.301(e)"),
        Segment(mhz("28.000"), mhz("28.500"), "§97.301(e)"),
    ],
}

# §97.305(c): where each non-CW mode may be used. CW is allowed anywhere the
# operator has privileges (§97.305(a)), so it has no entry here. On a shared
# edge (e.g. 7.100 data) the first matching segment is cited, so keep each list
# in frequency order.
#
# On every in-scope HF band §97.305 lists "phone, image" together, so the two
# modes share one list. 60 m is the exception (phone but not image); split
# this if 60 m comes into scope.
_PHONE_AND_IMAGE: list[Segment] = [
    Segment(mhz("1.800"), mhz("2.000"), "§97.305(c)(2)(iv)"),
    Segment(mhz("3.600"), mhz("4.000"), "§97.305(c)(3)(ii)"),
    Segment(mhz("7.125"), mhz("7.300"), "§97.305(c)(3)(vii)"),
    Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)"),
    Segment(mhz("18.110"), mhz("18.168"), "§97.305(c)(3)(xii)"),
    Segment(mhz("21.20"), mhz("21.45"), "§97.305(c)(3)(xiv)"),
    Segment(mhz("24.93"), mhz("24.99"), "§97.305(c)(3)(xvi)"),
    Segment(mhz("28.3"), mhz("28.5"), "§97.305(c)(3)(xviii)"),
    Segment(mhz("28.5"), mhz("29.0"), "§97.305(c)(3)(xix)"),
    Segment(mhz("29.0"), mhz("29.7"), "§97.305(c)(3)(xx)"),
]

EMISSIONS: dict[Mode, list[Segment]] = {
    Mode.DATA: [
        Segment(mhz("1.800"), mhz("2.000"), "§97.305(c)(2)(iii)"),
        Segment(mhz("3.500"), mhz("3.600"), "§97.305(c)(3)(i)"),
        Segment(mhz("7.000"), mhz("7.100"), "§97.305(c)(3)(iv)"),
        Segment(mhz("7.100"), mhz("7.125"), "§97.305(c)(3)(vi)"),
        Segment(mhz("10.100"), mhz("10.150"), "§97.305(c)(3)(viii)"),
        Segment(mhz("14.00"), mhz("14.15"), "§97.305(c)(3)(ix)"),
        Segment(mhz("18.068"), mhz("18.110"), "§97.305(c)(3)(xi)"),
        Segment(mhz("21.0"), mhz("21.2"), "§97.305(c)(3)(xiii)"),
        Segment(mhz("24.89"), mhz("24.93"), "§97.305(c)(3)(xv)"),
        Segment(mhz("28.0"), mhz("28.3"), "§97.305(c)(3)(xvii)"),
    ],
    Mode.PHONE: _PHONE_AND_IMAGE,
    Mode.IMAGE: _PHONE_AND_IMAGE,
}


@dataclass(frozen=True)
class Restriction:
    """A §97.307 rule matching some modes and classes in a segment.

    In RESTRICTIONS a match denies; in NOTES it adds a note to an allowed result.
    """

    segment: Segment
    classes: frozenset[LicenseClass]
    modes: frozenset[Mode]
    reason: str

    def applies(self, freq_hz: int, mode: Mode, license_class: LicenseClass) -> bool:
        return (
            license_class in self.classes
            and mode in self.modes
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
    Restriction(
        Segment(mhz("21.025"), mhz("21.200"), "§97.307(f)(9)"),
        _TECH,
        _NON_CW,
        "technicians may only use CW here",
    ),
    # §97.307(f)(10): Technicians may only use CW or SSB phone on 28.3-28.5.
    Restriction(
        Segment(mhz("28.3"), mhz("28.5"), "§97.307(f)(10)"),
        _TECH,
        frozenset({Mode.IMAGE}),
        "technicians may only use CW or SSB phone here",
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


# Matches like RESTRICTIONS, but an allowed result gets "<reason>, <cite>" as a
# note instead of being denied. §97.307(f)(10) allows Technician phone on
# 28.3-28.5 only as SSB, which the phone mode group can't express.
NOTES: list[Restriction] = [
    Restriction(
        Segment(mhz("28.3"), mhz("28.5"), "§97.307(f)(10)"),
        _TECH,
        frozenset({Mode.PHONE}),
        "SSB only (J3E/R3E)",
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
    notes = tuple(
        f"{note.reason}, {note.segment.cite}"
        for note in NOTES
        if note.applies(freq_hz, mode, license_class)
    )
    return Result(
        True, f"{mode.value} is allowed here", (privilege.cite, emission.cite), notes
    )
