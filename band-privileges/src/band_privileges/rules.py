"""Rule engine: is a frequency + mode allowed for a US amateur license class?

Values come from 47 CFR Part 97 for ITU Region 2 (the continental US), checked
against eCFR on 2026-10-25 (eCFR current as of 2026-10-22). Only 40 m and 20 m are
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
        Segment(mhz("7.000"), mhz("7.300"), "§97.301(b)"),
        Segment(mhz("14.000"), mhz("14.350"), "§97.301(b)"),
    ],
    LicenseClass.GENERAL: [
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(d)"),
        Segment(mhz("7.175"), mhz("7.300"), "§97.301(d)"),
        Segment(mhz("14.025"), mhz("14.150"), "§97.301(d)"),
        Segment(mhz("14.225"), mhz("14.350"), "§97.301(d)"),
    ],
    LicenseClass.TECHNICIAN: [  # no 20 m privileges
        Segment(mhz("7.025"), mhz("7.125"), "§97.301(e)"),
    ],
}

# §97.307(f)(9): Technicians may only use CW in these segments.
TECH_CW_ONLY: list[Segment] = [
    Segment(mhz("7.025"), mhz("7.125"), "§97.307(f)(9)"),
]

# §97.305(c): where each non-CW mode may be used. CW is allowed anywhere the
# operator has privileges (§97.305(a)), so it has no entry here. On a shared
# edge (e.g. 7.100 data) the first matching segment is cited, so keep each list
# in frequency order.
EMISSIONS: dict[Mode, list[Segment]] = {
    Mode.DATA: [
        Segment(mhz("7.000"), mhz("7.100"), "§97.305(c)(3)(iv)"),
        Segment(mhz("7.100"), mhz("7.125"), "§97.305(c)(3)(vi)"),
        Segment(mhz("14.00"), mhz("14.15"), "§97.305(c)(3)(ix)"),
    ],
    Mode.PHONE: [
        Segment(mhz("7.125"), mhz("7.300"), "§97.305(c)(3)(vii)"),
        Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)"),
    ],
    Mode.IMAGE: [
        Segment(mhz("7.125"), mhz("7.300"), "§97.305(c)(3)(vii)"),
        Segment(mhz("14.15"), mhz("14.35"), "§97.305(c)(3)(x)"),
    ],
}


# §97.305(c)(3)(v) authorizes phone/image on 7.075-7.100 MHz, but §97.307(f)(11)
# limits it to Region 2 stations west of 130° W or south of 20° N (e.g. Hawaii).
# v1 assumes a continental US station, so it's left out of EMISSIONS and denied.
REGION_LIMITED_PHONE = Segment(mhz("7.075"), mhz("7.100"), "§97.307(f)(11)")


def _find(segments: list[Segment], freq_hz: int) -> Segment | None:
    return next((s for s in segments if s.contains(freq_hz)), None)


def check(freq_hz: int, mode: Mode, license_class: LicenseClass) -> Result:
    # Order matters: privileges first, then CW (allowed anywhere with
    # privileges), then the Technician CW-only rule before EMISSIONS, so a
    # Technician on a shared edge like 7.125 is denied (the safe reading).
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
    if license_class is LicenseClass.TECHNICIAN:
        cw_only = _find(TECH_CW_ONLY, freq_hz)
        if cw_only is not None:
            return Result(
                False,
                "technicians may only use CW here",
                (privilege.cite, cw_only.cite),
            )
    emission = _find(EMISSIONS[mode], freq_hz)
    if emission is None:
        if mode in (Mode.PHONE, Mode.IMAGE) and REGION_LIMITED_PHONE.contains(freq_hz):
            return Result(
                False,
                f"{mode.value} here is only for stations west of 130° W or south of 20° N",
                (privilege.cite, REGION_LIMITED_PHONE.cite),
            )
        return Result(
            False,
            f"{mode.value} is not authorized at this frequency",
            (privilege.cite, "§97.305(c)"),
        )
    return Result(True, f"{mode.value} is allowed here", (privilege.cite, emission.cite))
