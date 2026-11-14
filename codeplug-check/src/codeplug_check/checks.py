"""The checks (README acceptance criteria): errors, warnings and notes for a list of channels.

Repeater offsets follow the ARRL band plan (arrl.org/band-plan, checked 2026-11-13): on 2 m,
outputs 145.20-145.50 and 146.61-146.97 have their inputs 600 kHz lower and 147.00-147.39
600 kHz higher; on 70 cm, 442-445 and 447-450 MHz are "repeater inputs and outputs (local
option)", 5 MHz apart, so the split is checked but not its direction. Local plans differ, so an
output outside these segments is only a note.
"""

from dataclasses import dataclass

from codeplug_check.bands import band_for
from codeplug_check.chirp import Channel

MHZ = 1_000_000
TWO_M_OUTPUTS = [  # (lowest output, highest output, input minus output), Hz
    (145_200_000, 145_500_000, -600_000),
    (146_610_000, 146_970_000, -600_000),
    (147_000_000, 147_390_000, +600_000),
]
TWO_M_SPLIT = 600_000
SEVENTY_CM_OUTPUTS = [(442_000_000, 445_000_000), (447_000_000, 450_000_000)]
SEVENTY_CM_SPLIT = 5_000_000
FM_MODES = ("FM", "NFM", "WFM")  # CTCSS/DCS are analog FM features; DMR and other digital modes don't use them
SEVERITIES = ("error", "warning", "note")


@dataclass(frozen=True)
class Finding:
    severity: str  # "error", "warning" or "note"
    line: int
    location: int
    name: str
    message: str


def check(channels: list[Channel]) -> list[Finding]:
    """Every finding, in file order; on one line, errors first."""
    findings = []
    for channel in channels:
        findings += [Finding(severity, channel.line, channel.location, channel.name, message)
                     for severity, message in _channel_findings(channel)]
    findings += _duplicates(channels)
    return sorted(findings, key=lambda f: (f.line, SEVERITIES.index(f.severity)))


def _channel_findings(channel: Channel) -> list[tuple[str, str]]:
    tx = channel.tx_hz
    if tx is None:
        return []  # receive only: any frequency is fine
    if band_for(tx) is None:
        # One clear error; offset advice on top of it would only be noise.
        return [("error", f"This channel transmits on {tx / MHZ:.3f} MHz, outside the amateur bands (47 CFR 97.301); "
                          "set Duplex to off for receive-only")]
    if tx == channel.rx_hz:
        return []  # simplex
    findings = _offset(channel.rx_hz, tx - channel.rx_hz)
    if channel.tx_tone is None and channel.mode in FM_MODES:
        findings.append(("warning", "Repeater channel sends no tone on transmit; most repeaters need one (CTCSS or DCS) to open"))
    return findings


def _offset(rx: int, shift: int) -> list[tuple[str, str]]:
    """Band-plan advice for a repeater channel listening on `rx` and transmitting `shift` Hz away."""
    off_plan = ("note", f"Output {rx / MHZ:.3f} MHz isn't in a band-plan repeater output segment; "
                        "check your local coordinator's plan")
    band = band_for(rx)
    if band == "2m":
        for low, high, expected in TWO_M_OUTPUTS:
            if low <= rx <= high:
                if shift == expected:
                    return []
                return [("warning", f"Offset {shift / MHZ:+.3f} MHz; the band plan has {expected / MHZ:+.3f} MHz "
                                    f"for outputs {low / MHZ:.3f}-{high / MHZ:.3f}")]
        findings = [off_plan]
        if abs(shift) != TWO_M_SPLIT:
            findings.append(("warning", f"Offset {shift / MHZ:+.3f} MHz; 2 m repeaters are 600 kHz apart"))
        return findings
    if band == "70cm":
        findings = []
        if not any(low <= rx <= high for low, high in SEVENTY_CM_OUTPUTS):
            findings.append(off_plan)
        if abs(shift) != SEVENTY_CM_SPLIT:
            findings.append(("warning", f"Offset {shift / MHZ:+.3f} MHz; 70 cm repeaters are 5 MHz apart"))
        return findings
    return []  # other bands: no offset rule here


def _duplicates(channels: list[Channel]) -> list[Finding]:
    """A channel stored twice (names may differ), and one name used for different settings."""
    findings, first_by_settings, first_by_name = [], {}, {}
    for channel in sorted(channels, key=lambda c: c.line):
        settings = (channel.rx_hz, channel.tx_hz, channel.tx_tone, channel.rx_tone, channel.mode)
        if (first := first_by_settings.setdefault(settings, channel)) is not channel:
            findings.append(Finding("note", channel.line, channel.location, channel.name,
                                    f"Same frequencies, tones and mode as location {first.location} (line {first.line})"))
        name = channel.name.strip()
        if not name:
            continue
        first = first_by_name.setdefault(name, channel)
        if first is not channel and (first.rx_hz, first.tx_hz, first.tx_tone, first.rx_tone, first.mode) != settings:
            findings.append(Finding("note", channel.line, channel.location, channel.name,
                                    f"Name {name!r} is also location {first.location} (line {first.line}), with different settings"))
    return findings
