"""CHIRP's CSV fields, read the way CHIRP reads them.

From CHIRP's source (chirp_common.py and drivers/generic_csv.py, commit d99bb22709,
2026-11-13): frequencies are MHz with up to 6 decimals ("146.940000"), optionally
followed by " MHz". Duplex is "", "+", "-", "split" (Offset then holds the transmit
frequency itself) or "off" (transmit disabled).
"""

import re

_MHZ = re.compile(r"([0-9]+)(?:\.([0-9]{0,6}))?")  # ASCII digits only: int() would also take "٣"
DUPLEX = ("", "+", "-", "split", "off")


def parse_mhz(text: str) -> int:
    """A CHIRP frequency in MHz -> exact Hz. ValueError if it isn't one."""
    text = text.strip().removesuffix(" MHz").strip()
    match = _MHZ.fullmatch(text)
    if not match:
        raise ValueError(f"{text[:20]!r} isn't a frequency in MHz like 146.940000")
    whole, fraction = match.group(1), match.group(2) or ""
    return int(whole) * 1_000_000 + int(fraction.ljust(6, "0"))


def transmit_hz(rx_hz: int, duplex: str, offset: str) -> int | None:
    """Where the channel transmits; None if transmit is off. ValueError for a bad duplex or offset."""
    if duplex not in DUPLEX:
        raise ValueError(f"Duplex {duplex[:10]!r} isn't one of: blank, +, -, split, off")
    if duplex == "off":
        return None
    if duplex == "":
        return rx_hz
    shift = parse_mhz(offset)
    return {"+": rx_hz + shift, "-": rx_hz - shift, "split": shift}[duplex]
