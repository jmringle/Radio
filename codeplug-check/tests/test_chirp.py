"""Reading CHIRP's CSV fields (CHIRP source, chirp_common.py and generic_csv.py, commit d99bb22709, 2026-11-13)."""

import pytest

from codeplug_check.chirp import parse_mhz, transmit_hz


@pytest.mark.parametrize("text, hz", [
    ("146.940000", 146_940_000), ("146.94", 146_940_000), ("446", 446_000_000),
    ("0.600000", 600_000), ("5.000000", 5_000_000), (" 147.315 ", 147_315_000),
    ("146.940000 MHz", 146_940_000),  # CHIRP accepts a unit too
])
def test_parse_mhz_gives_exact_hertz(text, hz):
    assert parse_mhz(text) == hz


@pytest.mark.parametrize("text", ["146.9400001", "abc", "-146.94", "146,94", "1e3", "146.94.1", "", "٣"])
def test_parse_mhz_refuses_anything_else(text):
    with pytest.raises(ValueError):
        parse_mhz(text)


@pytest.mark.parametrize("duplex, offset, tx", [
    ("", "0.000000", 146_520_000),  # simplex
    ("+", "0.600000", 147_120_000),
    ("-", "0.600000", 145_920_000),
    ("split", "445.500000", 445_500_000),  # Offset is the transmit frequency itself
    ("off", "0.000000", None),  # transmit disabled: receive only
])
def test_transmit_frequency_follows_duplex(duplex, offset, tx):
    assert transmit_hz(146_520_000, duplex, offset) == tx


@pytest.mark.parametrize("duplex", ["x", "+-", "SPLIT", "on"])
def test_unknown_duplex_is_refused(duplex):
    with pytest.raises(ValueError):
        transmit_hz(146_520_000, duplex, "0.6")
