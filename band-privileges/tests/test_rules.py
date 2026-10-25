"""HF rules from §97.301, §97.305 and §97.307 (eCFR checked 2026-10-25)."""

import pytest

from band_privileges import LicenseClass, Mode, Status, check, mhz
from band_privileges import rules

EXTRA = LicenseClass.EXTRA
GENERAL = LicenseClass.GENERAL
TECH = LicenseClass.TECHNICIAN
CW, PHONE, DATA, IMAGE = Mode.CW, Mode.PHONE, Mode.DATA, Mode.IMAGE

# (band, MHz, mode, class, allowed, a citation that must be in the result).
# Denials cite what decided them: §97.301 (no privileges), §97.305(c) (mode not
# authorized there) or a §97.307 restriction. CW cites §97.305(a).
CASES = [
    # 160 m (§97.305 files it under MF, so (c)(2), not (c)(3))
    ("160m", "1.810", CW, GENERAL, True, "§97.305(a)"),
    ("160m", "1.810", CW, TECH, False, "§97.301"),  # no Technician privileges
    ("160m", "1.950", IMAGE, GENERAL, True, "§97.305(c)(2)(iv)"),
    ("160m", "1.990", DATA, GENERAL, True, "§97.305(c)(2)(iii)"),  # data across the band
    ("160m", "1.800", CW, GENERAL, True, "§97.305(a)"),
    ("160m", "2.000", PHONE, GENERAL, True, "§97.305(c)(2)(iv)"),
    ("160m", "2.000001", CW, EXTRA, False, "§97.301"),
    # 80/75 m
    ("80m", "3.510", CW, EXTRA, True, "§97.305(a)"),  # 3.500-3.525 is Extra only
    ("80m", "3.700", PHONE, GENERAL, False, "§97.301"),  # General gap 3.600-3.800
    ("80m", "3.700", PHONE, EXTRA, True, "§97.305(c)(3)(ii)"),
    ("80m", "3.900", IMAGE, GENERAL, True, "§97.305(c)(3)(ii)"),
    ("80m", "3.550", IMAGE, EXTRA, False, "§97.305(c)"),  # data/CW only below 3.600
    ("80m", "3.700", DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 3.600
    ("80m", "3.550", CW, TECH, True, "§97.305(a)"),
    ("80m", "3.580", DATA, TECH, False, "§97.307(f)(9)"),  # Technician CW only
    ("80m", "3.500", CW, EXTRA, True, "§97.305(a)"),
    ("80m", "3.499999", CW, EXTRA, False, "§97.301"),
    ("80m", "4.000", PHONE, EXTRA, True, "§97.305(c)(3)(ii)"),
    ("80m", "4.000001", CW, EXTRA, False, "§97.301"),
    ("80m", "3.524999", CW, GENERAL, False, "§97.301"),
    ("80m", "3.799999", PHONE, GENERAL, False, "§97.301"),
    ("80m", "3.800", PHONE, GENERAL, True, "§97.305(c)(3)(ii)"),
    # Shared data/phone edge 3.600 (inclusive); Technician non-CW denied on it.
    ("80m", "3.600", DATA, GENERAL, True, "§97.305(c)(3)(i)"),
    ("80m", "3.600", PHONE, GENERAL, False, "§97.305(c)(3)(ii)"),  # single-point overlap
    ("80m", "3.600", CW, TECH, True, "§97.305(a)"),
    ("80m", "3.600", PHONE, TECH, False, "§97.307(f)(9)"),
    ("80m", "3.600001", CW, TECH, False, "§97.301"),
    # 40 m
    ("40m", "7.010", CW, EXTRA, True, "§97.305(a)"),  # 7.000-7.025 is Extra only
    ("40m", "7.110", DATA, EXTRA, True, "§97.305(c)(3)(vi)"),
    ("40m", "7.200", DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 7.125
    ("40m", "7.200", IMAGE, EXTRA, True, "§97.305(c)(3)(vii)"),
    ("40m", "7.050", IMAGE, EXTRA, False, "§97.305(c)"),
    ("40m", "7.050", CW, TECH, True, "§97.305(a)"),
    ("40m", "7.074", DATA, TECH, False, "§97.307(f)(9)"),  # Technician CW only
    ("40m", "7.000", CW, EXTRA, True, "§97.305(a)"),
    ("40m", "7.300", PHONE, EXTRA, True, "§97.305(c)(3)(vii)"),
    ("40m", "7.300001", CW, EXTRA, False, "§97.301"),
    ("40m", "7.024999", CW, GENERAL, False, "§97.301"),
    ("40m", "7.025", CW, GENERAL, True, "§97.305(a)"),
    ("40m", "7.125001", DATA, GENERAL, False, "§97.301"),  # General gap 7.125-7.175
    ("40m", "7.174999", PHONE, GENERAL, False, "§97.301"),
    ("40m", "7.175", PHONE, GENERAL, True, "§97.305(c)(3)(vii)"),
    # Shared edges: 7.100 data (iv)/(vi) cites the first; 7.125 data/phone.
    ("40m", "7.100", DATA, GENERAL, True, "§97.305(c)(3)(iv)"),
    ("40m", "7.125", DATA, GENERAL, True, "§97.305(c)(3)(vi)"),
    ("40m", "7.125", PHONE, GENERAL, False, "§97.305(c)(3)(vii)"),  # single-point overlap
    # Region-limited phone/image 7.075-7.100 (§97.307(f)(11)), both edges.
    ("40m", "7.090", PHONE, EXTRA, False, "§97.307(f)(11)"),
    ("40m", "7.075", PHONE, EXTRA, False, "§97.307(f)(11)"),
    ("40m", "7.100", PHONE, EXTRA, False, "§97.307(f)(11)"),
    ("40m", "7.090", IMAGE, EXTRA, False, "§97.307(f)(11)"),
    ("40m", "7.074999", PHONE, EXTRA, False, "§97.305(c)"),
    # Technician edges; 7.125 is also the start of (vii), and Tech is denied.
    ("40m", "7.024999", CW, TECH, False, "§97.301"),
    ("40m", "7.025", CW, TECH, True, "§97.305(a)"),
    ("40m", "7.125", CW, TECH, True, "§97.305(a)"),
    ("40m", "7.125001", CW, TECH, False, "§97.301"),
    ("40m", "7.100", PHONE, TECH, False, "§97.307(f)(9)"),
    ("40m", "7.125", PHONE, TECH, False, "§97.307(f)(9)"),
    ("40m", "7.125", IMAGE, TECH, False, "§97.307(f)(9)"),
    # 30 m: data and CW only, no phone/image anywhere
    ("30m", "10.110", CW, EXTRA, True, "§97.305(a)"),
    ("30m", "10.120", PHONE, EXTRA, False, "§97.305(c)"),
    ("30m", "10.120", IMAGE, GENERAL, False, "§97.305(c)"),
    ("30m", "10.136", DATA, TECH, False, "§97.301"),  # no Technician privileges
    ("30m", "10.100", DATA, GENERAL, True, "§97.305(c)(3)(viii)"),
    ("30m", "10.099999", CW, EXTRA, False, "§97.301"),
    ("30m", "10.150", DATA, EXTRA, True, "§97.305(c)(3)(viii)"),
    ("30m", "10.150001", CW, GENERAL, False, "§97.301"),
    # 20 m
    ("20m", "13.000", CW, EXTRA, False, "§97.301"),  # inside HF, not an amateur band
    ("20m", "14.010", CW, EXTRA, True, "§97.305(a)"),  # 14.000-14.025 is Extra only
    ("20m", "14.010", CW, GENERAL, False, "§97.301"),
    ("20m", "14.200", PHONE, EXTRA, True, "§97.305(c)(3)(x)"),
    ("20m", "14.200", PHONE, GENERAL, False, "§97.301"),  # General phone starts 14.225
    ("20m", "14.250", PHONE, GENERAL, True, "§97.305(c)(3)(x)"),
    ("20m", "14.074", PHONE, GENERAL, False, "§97.305(c)"),  # phone only above 14.15
    ("20m", "14.250", DATA, GENERAL, False, "§97.305(c)"),  # data only below 14.15
    # General ends at 14.150 where phone begins: they meet at one frequency, and
    # no phone signal fits in a single point, so deny (README).
    ("20m", "14.150", PHONE, GENERAL, False, "§97.305(c)(3)(x)"),
    ("20m", "14.150", DATA, GENERAL, True, "§97.305(c)(3)(ix)"),  # data overlaps widely
    ("20m", "14.150", PHONE, EXTRA, True, "§97.305(c)(3)(x)"),  # Extra overlaps widely
    ("20m", "14.074", DATA, TECH, False, "§97.301"),  # no Technician privileges
    # 17 m
    ("17m", "18.080", CW, EXTRA, True, "§97.305(a)"),
    ("17m", "18.100", DATA, TECH, False, "§97.301"),  # no Technician privileges
    ("17m", "18.130", DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 18.110
    ("17m", "18.100", PHONE, GENERAL, False, "§97.305(c)"),  # data/CW only below 18.110
    ("17m", "18.150", IMAGE, GENERAL, True, "§97.305(c)(3)(xii)"),
    ("17m", "18.068", CW, GENERAL, True, "§97.305(a)"),
    ("17m", "18.067999", CW, EXTRA, False, "§97.301"),
    ("17m", "18.168", PHONE, EXTRA, True, "§97.305(c)(3)(xii)"),
    ("17m", "18.168001", CW, GENERAL, False, "§97.301"),
    ("17m", "18.110", DATA, GENERAL, True, "§97.305(c)(3)(xi)"),  # shared edge
    ("17m", "18.110", PHONE, GENERAL, True, "§97.305(c)(3)(xii)"),
    # 15 m
    ("15m", "21.010", CW, EXTRA, True, "§97.305(a)"),  # 21.000-21.025 is Extra only
    ("15m", "21.250", PHONE, GENERAL, False, "§97.301"),  # General gap 21.200-21.275
    ("15m", "21.250", PHONE, EXTRA, True, "§97.305(c)(3)(xiv)"),
    ("15m", "21.300", IMAGE, GENERAL, True, "§97.305(c)(3)(xiv)"),
    ("15m", "21.100", IMAGE, EXTRA, False, "§97.305(c)"),  # data/CW only below 21.2
    ("15m", "21.300", DATA, GENERAL, False, "§97.305(c)"),  # phone/image only above 21.2
    ("15m", "21.050", CW, TECH, True, "§97.305(a)"),
    ("15m", "21.074", DATA, TECH, False, "§97.307(f)(9)"),  # Technician CW only
    ("15m", "21.000", CW, EXTRA, True, "§97.305(a)"),
    ("15m", "20.999999", CW, EXTRA, False, "§97.301"),
    ("15m", "21.450", PHONE, EXTRA, True, "§97.305(c)(3)(xiv)"),
    ("15m", "21.450001", CW, EXTRA, False, "§97.301"),
    ("15m", "21.024999", CW, GENERAL, False, "§97.301"),
    ("15m", "21.274999", PHONE, GENERAL, False, "§97.301"),
    ("15m", "21.275", PHONE, GENERAL, True, "§97.305(c)(3)(xiv)"),
    # Shared data/phone edge 21.200 (inclusive); Technician non-CW denied on it.
    ("15m", "21.200", DATA, GENERAL, True, "§97.305(c)(3)(xiii)"),
    ("15m", "21.200", PHONE, GENERAL, False, "§97.305(c)(3)(xiv)"),  # single-point overlap
    ("15m", "21.200", CW, TECH, True, "§97.305(a)"),
    ("15m", "21.200", PHONE, TECH, False, "§97.307(f)(9)"),
    ("15m", "21.200001", CW, TECH, False, "§97.301"),
    # 12 m
    ("12m", "24.900", CW, EXTRA, True, "§97.305(a)"),
    ("12m", "24.915", DATA, TECH, False, "§97.301"),  # no Technician privileges
    ("12m", "24.950", DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 24.93
    ("12m", "24.915", PHONE, GENERAL, False, "§97.305(c)"),  # data/CW only below 24.93
    ("12m", "24.970", IMAGE, GENERAL, True, "§97.305(c)(3)(xvi)"),
    ("12m", "24.890", CW, GENERAL, True, "§97.305(a)"),
    ("12m", "24.889999", CW, EXTRA, False, "§97.301"),
    ("12m", "24.990", PHONE, EXTRA, True, "§97.305(c)(3)(xvi)"),
    ("12m", "24.990001", CW, GENERAL, False, "§97.301"),
    ("12m", "24.930", DATA, GENERAL, True, "§97.305(c)(3)(xv)"),  # shared edge
    ("12m", "24.930", PHONE, GENERAL, True, "§97.305(c)(3)(xvi)"),
    # 10 m
    ("10m", "28.010", CW, EXTRA, True, "§97.305(a)"),
    ("10m", "28.400", DATA, EXTRA, False, "§97.305(c)"),  # data only below 28.3
    ("10m", "28.200", PHONE, GENERAL, False, "§97.305(c)"),  # phone only above 28.3
    ("10m", "28.400", IMAGE, GENERAL, True, "§97.305(c)(3)(xviii)"),  # (f)(10) is Tech-only
    ("10m", "28.000", CW, GENERAL, True, "§97.305(a)"),
    ("10m", "27.999999", CW, EXTRA, False, "§97.301"),
    ("10m", "29.700", PHONE, EXTRA, True, "§97.305(c)(3)(xx)"),
    ("10m", "28.500", PHONE, GENERAL, True, "§97.305(c)(3)(xviii)"),  # shared: first cited
    ("10m", "29.000", PHONE, GENERAL, True, "§97.305(c)(3)(xix)"),
    # Technician: data on 28.0-28.3 (no §97.307(f)(9) there), CW or SSB phone
    # on 28.3-28.5 (§97.307(f)(10)), nothing above 28.5.
    ("10m", "28.000", DATA, TECH, True, "§97.305(c)(3)(xvii)"),
    ("10m", "28.300", DATA, TECH, True, "§97.305(c)(3)(xvii)"),
    ("10m", "28.299999", PHONE, TECH, False, "§97.305(c)"),
    ("10m", "28.400", IMAGE, TECH, False, "§97.307(f)(10)"),
    ("10m", "28.300", IMAGE, TECH, False, "§97.307(f)(10)"),
    ("10m", "28.500", CW, TECH, True, "§97.305(a)"),
    ("10m", "28.500001", CW, TECH, False, "§97.301"),
    ("10m", "28.600", PHONE, TECH, False, "§97.301"),
]


@pytest.mark.parametrize(
    ("band", "freq", "mode", "license_class", "allowed", "cite"),
    CASES,
    ids=[f"{b}-{f}-{m.value}-{c.value}" for b, f, m, c, _, _ in CASES],
)
def test_privileges(band, freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# The full citation tuple, in order: the §97.301 privilege first, then what
# authorized (or denied) the mode.
EXACT_CITATIONS = [
    ("1.840", DATA, EXTRA, ("§97.301(b)", "§97.305(c)(2)(iii)")),
    ("1.900", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(2)(iv)")),
    ("3.580", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(i)")),
    ("3.900", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(ii)")),
    ("7.074", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(iv)")),
    ("7.150", PHONE, GENERAL, ("§97.301",)),  # General gap: no privilege to cite
    ("7.200", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(vii)")),
    ("10.136", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(viii)")),
    ("14.074", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(ix)")),
    ("18.100", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xi)")),
    ("18.130", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xii)")),
    ("21.074", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xiii)")),
    ("21.300", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xiv)")),
    ("24.915", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xv)")),
    ("24.950", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xvi)")),
    ("28.074", DATA, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xvii)")),
    ("28.400", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xviii)")),
    ("28.700", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xix)")),
    ("29.600", PHONE, GENERAL, ("§97.301(d)", "§97.305(c)(3)(xx)")),
    # §97.305(c)(3)(xvii) doesn't reference §97.307(f)(9), so a Technician may
    # use data/RTTY on 28.0-28.3 (the only HF band where that's true).
    ("28.074", DATA, TECH, ("§97.301(e)", "§97.305(c)(3)(xvii)")),
]


@pytest.mark.parametrize(("freq", "mode", "license_class", "citations"), EXACT_CITATIONS)
def test_exact_citations(freq, mode, license_class, citations):
    assert check(mhz(freq), mode, license_class).citations == citations


SSB_ONLY = ("SSB only (J3E/R3E), §97.307(f)(10)",)


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "notes"),
    [
        ("28.400", PHONE, TECH, SSB_ONLY),
        ("28.300", PHONE, TECH, SSB_ONLY),  # edge
        ("28.500", PHONE, TECH, SSB_ONLY),  # edge
        ("28.400", PHONE, GENERAL, ()),  # the SSB-only rule is Technician-only
        ("28.400", CW, TECH, ()),  # CW needs no note
        ("28.074", DATA, TECH, ()),
    ],
)
def test_ssb_only_note_applies_only_to_technician_phone(freq, mode, license_class, notes):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed
    assert result.notes == notes


def test_mhz_converts_without_float_rounding():
    assert mhz("14.150") == 14_150_000


def _all_segment_lists():
    yield from rules.PRIVILEGES.values()
    yield from rules.EMISSIONS.values()


def test_tables_are_in_frequency_order():
    # On a shared edge the first matching segment is cited, so order matters.
    for segments in _all_segment_lists():
        lows = [s.low_hz for s in segments]
        assert lows == sorted(lows)


def test_mode_and_restriction_segments_lie_inside_an_amateur_band():
    # Catches a typo like 2.18 for 21.8: every segment must sit inside one of
    # Extra's §97.301(b) bands, which cover every other class's privileges.
    bands = rules.PRIVILEGES[EXTRA]
    segments = [s for segs in _all_segment_lists() for s in segs]
    segments += [r.segment for r in rules.RESTRICTIONS + rules.NOTES]
    for s in segments:
        assert any(b.low_hz <= s.low_hz and s.high_hz <= b.high_hz for b in bands), s


# Out of v1 scope: 60 m (5.3305-5.4065 MHz, inclusive) and anything outside
# HF 1.8-29.7 MHz. Never answered allowed or denied, for any class or mode.
@pytest.mark.parametrize(
    "freq", ["5.3515", "5.3305", "5.4065", "5.332", "1.799999", "0.475", "29.700001", "146.52"]
)
@pytest.mark.parametrize("license_class", [TECH, GENERAL, EXTRA])
def test_out_of_scope_is_not_covered(freq, license_class):
    for mode in Mode:
        result = check(mhz(freq), mode, license_class)
        assert result.status is Status.NOT_COVERED
        assert not result.allowed


@pytest.mark.parametrize("freq", ["5.330499", "5.406501"])  # just outside 60 m: in HF
def test_just_outside_60m_is_an_ordinary_denial(freq):
    assert check(mhz(freq), Mode.DATA, EXTRA).status is Status.DENIED


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "must be a number"),
        ("abc", "must be a number"),
        ("14.074MHz", "must be a number"),
        # Only plain decimals: Decimal() also accepts these, but they're typos
        # or tricks, never a frequency someone meant.
        ("nan", "must be a number"),
        ("NaN", "must be a number"),
        ("inf", "must be a number"),
        ("-inf", "must be a number"),
        ("1e-7", "must be a number"),
        ("1e10000000", "must be a number"),  # exact math on this hangs
        ("1_4.074", "must be a number"),  # underscore digit separator
        ("１４.０７４", "must be a number"),  # full-width digits
        (" 14.074", "must be a number"),
        ("+14.074", "must be a number"),
        ("14.", "must be a number"),
        (".5", "must be a number"),
        ("1" * 33, "too long"),
        ("0", "greater than 0"),
        ("-14.074", "greater than 0"),
        ("14.0740001", "finer than 1 Hz"),  # 7 decimal places
        # 31 significant digits: Decimal arithmetic would round this to a whole Hz.
        ("14.0000000000000000000000000001", "finer than 1 Hz"),
    ],
)
def test_mhz_rejects_bad_input_with_one_error_type(value, message):
    with pytest.raises(ValueError, match=message):
        mhz(value)


def test_mhz_accepts_exactly_1_hz_resolution():
    assert mhz("14.000001") == 14_000_001


# Near-edge warnings (README: 1 kHz for CW, 3 kHz otherwise, either side, only
# edges that limit this class and mode; only on allowed results).


def test_data_just_below_where_data_stops_warns():
    result = check(mhz("14.149"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.warnings == (
        "within 3 kHz of 14.150 MHz, where data stops being allowed for general",
    )


def test_no_warning_mid_segment():
    assert check(mhz("14.074"), Mode.DATA, GENERAL).warnings == ()


def test_edge_with_the_same_mode_beyond_it_does_not_warn():
    # 7.100 ends data row (iv), but row (vi) continues data to 7.125, so
    # crossing it is fine for Extra.
    assert check(mhz("7.099"), Mode.DATA, EXTRA).warnings == ()


def _warns_at(edge_mhz, mode, license_class):
    margin = 1 if mode is Mode.CW else 3
    return (
        f"within {margin} kHz of {edge_mhz} MHz, where {mode.value} stops being "
        f"allowed for {license_class.value}",
    )


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "warnings"),
    [
        # CW margin is 1 kHz, inclusive; General CW starts at 14.025.
        ("14.026", CW, GENERAL, _warns_at("14.025", CW, GENERAL)),
        ("14.026001", CW, GENERAL, ()),
        # Other modes: 3 kHz, inclusive.
        ("14.028", DATA, GENERAL, _warns_at("14.025", DATA, GENERAL)),
        ("14.028001", DATA, GENERAL, ()),
        # LSB voice at 7.177 reaches below General's 7.175 phone edge.
        ("7.177", PHONE, GENERAL, _warns_at("7.175", PHONE, GENERAL)),
        # Band edge: beyond 29.700 is out of scope (not allowed).
        ("29.699", PHONE, EXTRA, _warns_at("29.700", PHONE, EXTRA)),
        # Technician data: 28.300 is allowed (decision 3) but data stops there.
        ("28.299", DATA, TECH, _warns_at("28.300", DATA, TECH)),
        ("28.300", DATA, TECH, _warns_at("28.300", DATA, TECH)),  # exactly on the edge
        # Shared phone edges inside 10 m: phone continues, no warning.
        ("28.500", PHONE, GENERAL, ()),
        ("28.999", PHONE, EXTRA, ()),
        # 30 m band edges, low and high.
        ("10.101", DATA, GENERAL, _warns_at("10.100", DATA, GENERAL)),
        ("10.149", DATA, GENERAL, _warns_at("10.150", DATA, GENERAL)),
    ],
)
def test_near_edge_warnings(freq, mode, license_class, warnings):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed
    assert result.warnings == warnings


def test_denied_and_not_covered_results_never_warn():
    assert check(mhz("14.151"), Mode.DATA, GENERAL).warnings == ()  # denied, near edge
    assert check(mhz("29.701"), Mode.CW, EXTRA).warnings == ()  # not covered
    # Denied, and the point beyond the nearby 14.150 edge isn't allowed either,
    # so a warning would fire if denied results were checked.
    assert check(mhz("14.149"), Mode.PHONE, GENERAL).warnings == ()
