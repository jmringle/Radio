"""HF rules from §97.301, §97.305 and §97.307 (eCFR checked 2026-10-25)."""

import pytest

from band_privileges import LicenseClass, Mode, check, mhz

EXTRA = LicenseClass.EXTRA
GENERAL = LicenseClass.GENERAL
TECH = LicenseClass.TECHNICIAN


def test_ft8_on_20m_is_allowed_for_general_with_citations():
    result = check(mhz("14.074"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(ix)")


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed"),
    [
        ("14.010", Mode.CW, EXTRA, True),  # 14.000-14.025 is Extra only
        ("14.010", Mode.CW, GENERAL, False),
        ("14.200", Mode.PHONE, EXTRA, True),
        ("14.200", Mode.PHONE, GENERAL, False),  # General phone starts 14.225
        ("14.250", Mode.PHONE, GENERAL, True),
        ("14.074", Mode.PHONE, GENERAL, False),  # phone not allowed below 14.15
        ("14.250", Mode.DATA, GENERAL, False),  # data not allowed above 14.15
        ("14.074", Mode.DATA, TECH, False),  # no Technician privileges on 20 m
        ("13.000", Mode.CW, EXTRA, False),  # not an amateur band
    ],
)
def test_20m_privileges(freq, mode, license_class, allowed):
    assert check(mhz(freq), mode, license_class).allowed is allowed


def test_mhz_converts_without_float_rounding():
    assert mhz("14.150") == 14_150_000


# 40 m: §97.301(b)/(d)/(e), §97.305(c)(3)(iv)-(vii), §97.307(f)(9)/(11)


def test_40m_extra_only_cw_segment_is_allowed_for_extra():
    assert check(mhz("7.010"), Mode.CW, EXTRA).allowed


def test_40m_data_is_allowed_for_general_with_citations():
    result = check(mhz("7.074"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(iv)")


def test_40m_general_has_no_privileges_in_the_7125_to_7175_gap():
    result = check(mhz("7.150"), Mode.PHONE, GENERAL)
    assert not result.allowed
    assert result.citations == ("§97.301",)


def test_40m_phone_above_7175_is_allowed_for_general_with_citations():
    result = check(mhz("7.200"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(vii)")


@pytest.mark.parametrize(
    ("freq", "mode", "allowed"),
    [
        ("7.110", Mode.DATA, True),  # §97.305(c)(3)(vi)
        ("7.200", Mode.DATA, False),  # phone/image only above 7.125
        ("7.200", Mode.IMAGE, True),  # §97.305(c)(3)(vii)
        ("7.050", Mode.IMAGE, False),
    ],
)
def test_40m_mode_segments_for_extra(freq, mode, allowed):
    assert check(mhz(freq), mode, EXTRA).allowed is allowed


def test_40m_phone_7075_to_7100_is_denied_for_continental_us_station():
    result = check(mhz("7.090"), Mode.PHONE, EXTRA)
    assert not result.allowed
    assert "§97.307(f)(11)" in result.citations


def test_40m_technician_may_use_cw():
    assert check(mhz("7.050"), Mode.CW, TECH).allowed


def test_40m_technician_data_is_denied_cw_only():
    result = check(mhz("7.074"), Mode.DATA, TECH)
    assert not result.allowed
    assert "§97.307(f)(9)" in result.citations


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed"),
    [
        ("7.000", Mode.CW, EXTRA, True),  # lower band edge
        ("7.300", Mode.PHONE, EXTRA, True),  # upper band edge
        ("7.300001", Mode.CW, EXTRA, False),  # 1 Hz past the band
        ("7.024999", Mode.CW, GENERAL, False),  # 1 Hz below General
        ("7.025", Mode.CW, GENERAL, True),
        # Shared edge 7.125: inside General's lower segment, and on both the
        # data and phone mode segments (edges inclusive).
        ("7.125", Mode.DATA, GENERAL, True),
        ("7.125", Mode.PHONE, GENERAL, True),
        ("7.125001", Mode.DATA, GENERAL, False),
        ("7.175", Mode.PHONE, GENERAL, True),
        ("7.174999", Mode.PHONE, GENERAL, False),
    ],
)
def test_40m_edges(freq, mode, license_class, allowed):
    assert check(mhz(freq), mode, license_class).allowed is allowed


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        # Shared data edge (iv)/(vi): allowed, first segment cited.
        ("7.100", Mode.DATA, GENERAL, True, "§97.305(c)(3)(iv)"),
        # Region-limited phone/image segment 7.075-7.100, both edges.
        ("7.075", Mode.PHONE, EXTRA, False, "§97.307(f)(11)"),
        ("7.100", Mode.PHONE, EXTRA, False, "§97.307(f)(11)"),
        ("7.090", Mode.IMAGE, EXTRA, False, "§97.307(f)(11)"),
        ("7.074999", Mode.PHONE, EXTRA, False, "§97.305(c)"),
        # Technician privilege edges and CW-only rule.
        ("7.024999", Mode.CW, TECH, False, "§97.301"),
        ("7.025", Mode.CW, TECH, True, "§97.305(a)"),
        ("7.125", Mode.CW, TECH, True, "§97.305(a)"),
        ("7.125001", Mode.CW, TECH, False, "§97.301"),
        ("7.100", Mode.PHONE, TECH, False, "§97.307(f)(9)"),
        # 7.125 is also the start of phone/image segment (vii); Tech is denied.
        ("7.125", Mode.PHONE, TECH, False, "§97.307(f)(9)"),
        ("7.125", Mode.IMAGE, TECH, False, "§97.307(f)(9)"),
    ],
)
def test_40m_shared_and_restricted_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 80/75 m: §97.301(b)/(d)/(e), §97.305(c)(3)(i)-(ii), §97.307(f)(9)


def test_80m_extra_only_cw_segment_is_allowed_for_extra():
    assert check(mhz("3.510"), Mode.CW, EXTRA).allowed


def test_80m_data_is_allowed_for_general_with_citations():
    result = check(mhz("3.580"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(i)")


def test_80m_phone_above_3800_is_allowed_for_general_with_citations():
    result = check(mhz("3.900"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(ii)")


def test_80m_technician_may_use_cw():
    assert check(mhz("3.550"), Mode.CW, TECH).allowed


def test_80m_technician_data_is_denied_cw_only():
    result = check(mhz("3.580"), Mode.DATA, TECH)
    assert not result.allowed
    assert "§97.307(f)(9)" in result.citations


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("3.700", Mode.PHONE, GENERAL, False, "§97.301"),  # General gap 3.600-3.800
        ("3.700", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(ii)"),
        ("3.900", Mode.IMAGE, GENERAL, True, "§97.305(c)(3)(ii)"),
        ("3.550", Mode.IMAGE, EXTRA, False, "§97.305(c)"),  # data/CW only below 3.600
        ("3.700", Mode.DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 3.600
        # Band and class edges.
        ("3.500", Mode.CW, EXTRA, True, "§97.305(a)"),
        ("3.499999", Mode.CW, EXTRA, False, "§97.301"),
        ("4.000", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(ii)"),
        ("4.000001", Mode.CW, EXTRA, False, "§97.301"),
        ("3.524999", Mode.CW, GENERAL, False, "§97.301"),
        ("3.799999", Mode.PHONE, GENERAL, False, "§97.301"),
        ("3.800", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(ii)"),
        # Shared data/phone edge 3.600 (inclusive), and Tech denied on it.
        ("3.600", Mode.DATA, GENERAL, True, "§97.305(c)(3)(i)"),
        ("3.600", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(ii)"),
        ("3.600", Mode.CW, TECH, True, "§97.305(a)"),
        ("3.600", Mode.PHONE, TECH, False, "§97.307(f)(9)"),
        ("3.600001", Mode.CW, TECH, False, "§97.301"),
    ],
)
def test_80m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 15 m: §97.301(b)/(d)/(e), §97.305(c)(3)(xiii)-(xiv), §97.307(f)(9)


def test_15m_extra_only_cw_segment_is_allowed_for_extra():
    assert check(mhz("21.010"), Mode.CW, EXTRA).allowed


def test_15m_data_is_allowed_for_general_with_citations():
    result = check(mhz("21.074"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xiii)")


def test_15m_phone_above_21275_is_allowed_for_general_with_citations():
    result = check(mhz("21.300"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xiv)")


def test_15m_technician_may_use_cw():
    assert check(mhz("21.050"), Mode.CW, TECH).allowed


def test_15m_technician_data_is_denied_cw_only():
    result = check(mhz("21.074"), Mode.DATA, TECH)
    assert not result.allowed
    assert "§97.307(f)(9)" in result.citations


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("21.250", Mode.PHONE, GENERAL, False, "§97.301"),  # General gap 21.200-21.275
        ("21.250", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(xiv)"),
        ("21.300", Mode.IMAGE, GENERAL, True, "§97.305(c)(3)(xiv)"),
        ("21.100", Mode.IMAGE, EXTRA, False, "§97.305(c)"),  # data/CW only below 21.2
        ("21.300", Mode.DATA, GENERAL, False, "§97.305(c)"),  # phone/image only above 21.2
        # Band and class edges.
        ("21.000", Mode.CW, EXTRA, True, "§97.305(a)"),
        ("20.999999", Mode.CW, EXTRA, False, "§97.301"),
        ("21.450", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(xiv)"),
        ("21.450001", Mode.CW, EXTRA, False, "§97.301"),
        ("21.024999", Mode.CW, GENERAL, False, "§97.301"),
        ("21.274999", Mode.PHONE, GENERAL, False, "§97.301"),
        ("21.275", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(xiv)"),
        # Shared data/phone edge 21.200 (inclusive), and Tech denied on it.
        ("21.200", Mode.DATA, GENERAL, True, "§97.305(c)(3)(xiii)"),
        ("21.200", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(xiv)"),
        ("21.200", Mode.CW, TECH, True, "§97.305(a)"),
        ("21.200", Mode.PHONE, TECH, False, "§97.307(f)(9)"),
        ("21.200001", Mode.CW, TECH, False, "§97.301"),
    ],
)
def test_15m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 160 m: §97.301(b)/(d), §97.305(c)(2)(iii)-(iv) (filed under MF, not HF)


def test_160m_cw_is_allowed_for_general():
    assert check(mhz("1.810"), Mode.CW, GENERAL).allowed


def test_160m_data_is_allowed_for_extra_with_mf_citations():
    result = check(mhz("1.840"), Mode.DATA, EXTRA)
    assert result.allowed
    assert result.citations == ("§97.301(b)", "§97.305(c)(2)(iii)")


def test_160m_phone_is_allowed_for_general_with_mf_citations():
    result = check(mhz("1.900"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(2)(iv)")


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("1.810", Mode.CW, TECH, False, "§97.301"),  # no Technician privileges on 160 m
        ("1.950", Mode.IMAGE, GENERAL, True, "§97.305(c)(2)(iv)"),
        ("1.990", Mode.DATA, GENERAL, True, "§97.305(c)(2)(iii)"),  # data across the whole band
        ("1.800", Mode.CW, GENERAL, True, "§97.305(a)"),
        ("1.799999", Mode.CW, EXTRA, False, "§97.301"),
        ("2.000", Mode.PHONE, GENERAL, True, "§97.305(c)(2)(iv)"),
        ("2.000001", Mode.CW, EXTRA, False, "§97.301"),
    ],
)
def test_160m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 30 m: §97.301(b)/(d), §97.305(c)(3)(viii): data and CW only, no phone/image


def test_30m_data_is_allowed_for_general_with_citations():
    result = check(mhz("10.136"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(viii)")


def test_30m_cw_is_allowed_for_extra():
    assert check(mhz("10.110"), Mode.CW, EXTRA).allowed


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("10.120", Mode.PHONE, EXTRA, False, "§97.305(c)"),  # no phone anywhere on 30 m
        ("10.120", Mode.IMAGE, GENERAL, False, "§97.305(c)"),
        ("10.136", Mode.DATA, TECH, False, "§97.301"),  # no Technician privileges
        ("10.100", Mode.DATA, GENERAL, True, "§97.305(c)(3)(viii)"),
        ("10.099999", Mode.CW, EXTRA, False, "§97.301"),
        ("10.150", Mode.DATA, EXTRA, True, "§97.305(c)(3)(viii)"),
        ("10.150001", Mode.CW, GENERAL, False, "§97.301"),
    ],
)
def test_30m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 17 m: §97.301(b)/(d), §97.305(c)(3)(xi)-(xii)


def test_17m_data_is_allowed_for_general_with_citations():
    result = check(mhz("18.100"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xi)")


def test_17m_phone_is_allowed_for_general_with_citations():
    result = check(mhz("18.130"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xii)")


def test_17m_cw_is_allowed_for_extra():
    assert check(mhz("18.080"), Mode.CW, EXTRA).allowed


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("18.100", Mode.DATA, TECH, False, "§97.301"),  # no Technician privileges
        ("18.130", Mode.DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 18.110
        ("18.100", Mode.PHONE, GENERAL, False, "§97.305(c)"),  # data/CW only below 18.110
        ("18.150", Mode.IMAGE, GENERAL, True, "§97.305(c)(3)(xii)"),
        # Band edges.
        ("18.068", Mode.CW, GENERAL, True, "§97.305(a)"),
        ("18.067999", Mode.CW, EXTRA, False, "§97.301"),
        ("18.168", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(xii)"),
        ("18.168001", Mode.CW, GENERAL, False, "§97.301"),
        # Shared data/phone edge 18.110 (inclusive).
        ("18.110", Mode.DATA, GENERAL, True, "§97.305(c)(3)(xi)"),
        ("18.110", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(xii)"),
    ],
)
def test_17m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations


# 12 m: §97.301(b)/(d), §97.305(c)(3)(xv)-(xvi)


def test_12m_data_is_allowed_for_general_with_citations():
    result = check(mhz("24.915"), Mode.DATA, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xv)")


def test_12m_phone_is_allowed_for_general_with_citations():
    result = check(mhz("24.950"), Mode.PHONE, GENERAL)
    assert result.allowed
    assert result.citations == ("§97.301(d)", "§97.305(c)(3)(xvi)")


def test_12m_cw_is_allowed_for_extra():
    assert check(mhz("24.900"), Mode.CW, EXTRA).allowed


@pytest.mark.parametrize(
    ("freq", "mode", "license_class", "allowed", "cite"),
    [
        ("24.915", Mode.DATA, TECH, False, "§97.301"),  # no Technician privileges
        ("24.950", Mode.DATA, EXTRA, False, "§97.305(c)"),  # phone/image only above 24.93
        ("24.915", Mode.PHONE, GENERAL, False, "§97.305(c)"),  # data/CW only below 24.93
        ("24.970", Mode.IMAGE, GENERAL, True, "§97.305(c)(3)(xvi)"),
        # Band edges.
        ("24.890", Mode.CW, GENERAL, True, "§97.305(a)"),
        ("24.889999", Mode.CW, EXTRA, False, "§97.301"),
        ("24.990", Mode.PHONE, EXTRA, True, "§97.305(c)(3)(xvi)"),
        ("24.990001", Mode.CW, GENERAL, False, "§97.301"),
        # Shared data/phone edge 24.930 (inclusive).
        ("24.930", Mode.DATA, GENERAL, True, "§97.305(c)(3)(xv)"),
        ("24.930", Mode.PHONE, GENERAL, True, "§97.305(c)(3)(xvi)"),
    ],
)
def test_12m_modes_and_edges(freq, mode, license_class, allowed, cite):
    result = check(mhz(freq), mode, license_class)
    assert result.allowed is allowed
    assert cite in result.citations
