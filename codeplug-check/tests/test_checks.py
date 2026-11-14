"""The checks (README acceptance criteria). Band plan: ARRL, arrl.org/band-plan (checked 2026-11-13).
Band edges: 47 CFR 97.301(a)."""

from dataclasses import replace

import pytest

from codeplug_check.checks import check
from codeplug_check.chirp import Channel

MHZ = 1_000_000


def ch(rx, tx="same", tx_tone="Tone 100.0", rx_tone=None, mode="FM", line=2, location=1, name="RPT"):
    """A channel; frequencies in MHz. tx: 'same' for simplex, None for transmit off."""
    rx_hz = round(rx * MHZ)
    tx_hz = rx_hz if tx == "same" else None if tx is None else round(tx * MHZ)
    return Channel(line, location, name, rx_hz, tx_hz, tx_tone, rx_tone, mode)


def found(*channels):
    return [(f.severity, f.line, f.message) for f in check(list(channels))]


# --- transmitting outside the amateur bands (error) ---

@pytest.mark.parametrize("channel", [
    ch(462.5625, tx_tone=None),  # GMRS channel 1 with transmit on
    ch(147.9, 148.5),  # +600 kHz from near the top of 2 m lands above it
    ch(143.95),
])
def test_transmitting_outside_the_amateur_bands_is_an_error(channel):
    findings = found(channel)
    assert len(findings) == 1 and findings[0][0] == "error"
    assert "outside the amateur bands (47 CFR 97.301)" in findings[0][2]


@pytest.mark.parametrize("channel", [ch(162.55, None, tx_tone=None), ch(462.5625, None, tx_tone=None)])
def test_receive_only_channels_may_be_anywhere(channel):
    assert found(channel) == []  # NOAA weather, GMRS listening: transmit off


def test_the_error_names_the_transmit_frequency_and_the_fix(channel=ch(147.9, 148.5)):
    message = found(channel)[0][2]
    assert "transmits on 148.500 MHz" in message and message.endswith("; set Duplex to off for receive-only")


# --- repeater offsets (2 m: 600 kHz, direction by output segment; 70 cm: 5 MHz, either way) ---

@pytest.mark.parametrize("channel", [
    ch(146.94, 146.34), ch(145.33, 144.73),  # outputs 146.61-146.97 and 145.20-145.50: input 600 kHz lower
    ch(147.12, 147.72),  # outputs 147.00-147.39: input 600 kHz higher
    ch(146.61, 146.01), ch(146.97, 146.37), ch(147.00, 147.60), ch(147.39, 147.99),  # segment edges
    ch(443.1, 448.1), ch(447.5, 442.5),  # 70 cm: 5 MHz, local option either way
    ch(146.52, tx_tone=None), ch(446.0, tx_tone=None),  # simplex calling frequencies
])
def test_band_plan_repeaters_and_simplex_pass(channel):
    assert found(channel) == []


@pytest.mark.parametrize("channel, says", [
    (ch(146.94, 147.54), "+0.600 MHz; the band plan has -0.600 MHz for outputs 146.610-146.970"),
    (ch(147.12, 146.52), "-0.600 MHz; the band plan has +0.600 MHz for outputs 147.000-147.390"),
    (ch(146.94, 146.44), "-0.500 MHz; the band plan has -0.600 MHz for outputs 146.610-146.970"),
    (ch(443.1, 444.7), "+1.600 MHz; 70 cm repeaters are 5 MHz apart"),
])
def test_offsets_off_the_band_plan_are_warnings(channel, says):
    findings = found(channel)
    assert [f[0] for f in findings] == ["warning"] and says in findings[0][2]


@pytest.mark.parametrize("channel, warn", [(ch(146.40, 147.00), False), (ch(146.40, 147.10), True),
                                           (ch(440.0, 445.0), False)])
def test_outputs_outside_the_band_plans_repeater_segments_are_a_note(channel, warn):
    # 146.40 is a repeater input in some areas (ARRL note): local plans differ, so only a note,
    # plus a warning if the offset isn't the band's usual one.
    findings = found(channel)
    assert ("note", 2) in [(f[0], f[1]) for f in findings]
    assert any("isn't in a band-plan repeater output segment; check your local coordinator's plan" in f[2] for f in findings)
    assert ("warning" in [f[0] for f in findings]) == warn


def test_split_is_checked_like_plus_and_minus():
    assert found(ch(146.94, 146.34)) == []  # the reader turns split into a transmit frequency too


# --- repeater channels with no transmit tone (warning) ---

@pytest.mark.parametrize("tx_tone, rx_tone", [(None, None), (None, "Tone 100.0"), (None, "DTCS 023")])
def test_a_repeater_channel_that_sends_no_tone_is_a_warning(tx_tone, rx_tone):
    findings = found(ch(146.94, 146.34, tx_tone=tx_tone, rx_tone=rx_tone))
    assert findings == [("warning", 2, "Repeater channel sends no tone on transmit; most repeaters need one (CTCSS or DCS) to open")]


@pytest.mark.parametrize("channel", [
    ch(146.94, 146.34, tx_tone="DTCS 023"),
    ch(146.52, tx_tone=None),  # simplex: no tone needed
    ch(146.94, None, tx_tone=None),  # transmit off
    ch(145.33, 144.73, tx_tone=None, mode="DMR"),  # digital: no CTCSS/DCS
])
def test_no_tone_warning_only_for_fm_repeater_channels_that_transmit(channel):
    assert found(channel) == []


# --- duplicates (note) ---

def test_the_same_channel_stored_twice_is_a_note_on_the_later_one():
    findings = found(ch(146.94, 146.34, line=2, location=1, name="RPT A"),
                     ch(146.94, 146.34, line=5, location=4, name="RPT B"))
    assert findings == [("note", 5, "Same frequencies, tones and mode as location 1 (line 2)")]


def test_one_name_for_different_settings_is_a_note():
    findings = found(ch(146.94, 146.34, line=2, location=1, name="CLUB"),
                     ch(147.12, 147.72, line=3, location=2, name="CLUB"))
    assert findings == [("note", 3, "Name 'CLUB' is also location 1 (line 2), with different settings")]


@pytest.mark.parametrize("other", [ch(146.94, 146.34, tx_tone="Tone 88.5", line=3, location=2),
                                   ch(146.94, 146.34, mode="NFM", line=3, location=2)])
def test_different_tones_or_mode_arent_duplicates(other):
    assert found(ch(146.94, 146.34, name="A"), replace(other, name="B")) == []


def test_blank_names_arent_compared():
    assert found(ch(146.94, 146.34, name=""), ch(147.12, 147.72, name="", line=3, location=2)) == []


def test_findings_are_in_file_order():
    findings = found(ch(146.94, 146.34, tx_tone=None, line=4, location=3, name="B"),
                     ch(462.5625, line=2, location=1, name="A"))
    assert [(f[0], f[1]) for f in findings] == [("error", 2), ("warning", 4)]
