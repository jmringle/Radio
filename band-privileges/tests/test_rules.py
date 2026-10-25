"""20 m rules from §97.301 and §97.305 (eCFR checked 2026-10-25)."""

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
