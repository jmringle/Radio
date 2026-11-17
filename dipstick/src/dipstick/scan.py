"""One sweep of a frequency range, as readings (SWR, impedance, return loss per frequency).

Found on a NanoVNA-H, firmware 1.2.43 (2026-11-15): `scan` replaces the NanoVNA's own
frequency list and point count, and afterward `sweep` still reports the old start and stop.
So the settings are read before the scan and always put back after it.

Reply lines are "frequency S11-real S11-imaginary " (mask 3: frequency and S11), or
"frequency S21-real S21-imaginary " (mask 5: frequency and S21; hugen79/NanoVNA-H cmd_scan,
read 2026-11-17).
"""

import re

from dipstick.bands import check_antenna_sweep
from dipstick.device import DeviceError, NanoVNA
from dipstick.s11 import Reading, reading
from dipstick.s21 import Through, through

MAX_POINTS = 101  # this firmware's limit ("p:101" in `info`)
FREQUENCY_AND_S11 = 3  # scan output mask: bit 0 frequency, bit 1 S11, bit 2 S21
FREQUENCY_AND_S21 = 5
# `cal` alone prints the names of the status bits that are set, in this order (cmd_cal's items[]).
CAL_STATUS = ("load", "open", "short", "thru", "isoln", "Es", "Er", "Et", "cal'ed")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?(e[-+]?[0-9]+)?")  # plain decimals as the NanoVNA prints them
_HZ = re.compile(r"[0-9]+")


def scan(nano: NanoVNA, start_hz: int, stop_hz: int, points: int, *, no_antenna: bool = False) -> list[Reading]:
    """Sweep start..stop with `points` points. Antenna sweeps must stay inside one amateur band
    (T5); a wider sweep needs no_antenna=True, meaning nothing that radiates is connected."""
    return _scan(nano, start_hz, stop_hz, points, no_antenna, FREQUENCY_AND_S11, reading)


def scan_s21(nano: NanoVNA, start_hz: int, stop_hz: int, points: int, *, no_antenna: bool = False) -> list[Through]:
    """Like scan, but what arrives at CH1. CH0 still sends, so the same one-band rule applies (T5)."""
    return _scan(nano, start_hz, stop_hz, points, no_antenna, FREQUENCY_AND_S21, through)


def calibration_status(nano: NanoVNA) -> set[str]:
    """What the NanoVNA's calibration in memory holds, from `cal` alone: such as {"load", "isoln",
    "Es", "Er", "Et", "cal'ed"} after a full two-port calibration."""
    answer = nano.ask("cal")
    words = answer[0].split() if len(answer) == 1 else None
    if words is None or len(set(words)) != len(words) or not set(words) <= set(CAL_STATUS):
        raise DeviceError(f"Can't read the NanoVNA's calibration status (got {answer!r})")
    return set(words)


def thru_calibrated(status: set[str]) -> bool:
    """Whether S21 is corrected: a thru was measured (Et) and the calibration is on (cal'ed)."""
    return {"Et", "cal'ed"} <= status


def _scan(nano, start_hz, stop_hz, points, no_antenna, mask, convert):
    if not no_antenna:
        check_antenna_sweep(start_hz, stop_hz)
    if not 2 <= points <= MAX_POINTS:
        raise ValueError(f"A scan needs 2 to {MAX_POINTS} points, got {points}")
    settings = _settings(nano)  # before anything changes: without these there's nothing to put back
    error = None
    try:
        return _readings(nano.ask("scan", start_hz, stop_hz, points, mask), start_hz, stop_hz, points, convert)
    except DeviceError as scan_error:
        error = scan_error
        raise
    finally:
        _restore(nano, settings, error)


def _settings(nano: NanoVNA) -> tuple[int, int, int]:
    answer = nano.ask("sweep")
    parts = answer[0].split() if len(answer) == 1 else []
    if len(parts) != 3 or not all(_HZ.fullmatch(p) for p in parts):
        raise DeviceError(f"Can't read the NanoVNA's sweep settings (got {answer!r}); nothing was changed")
    start, stop, points = map(int, parts)
    return start, stop, points


def _restore(nano: NanoVNA, settings: tuple[int, int, int], scan_error: DeviceError | None) -> None:
    start, stop, points = settings
    try:
        nano.ask("sweep", start, stop, points)
    except DeviceError as restore_error:
        by_hand = (f"Couldn't put the NanoVNA's sweep back ({restore_error}); set it by hand: "
                   f"{start / 1e6:g} to {stop / 1e6:g} MHz, {points} points")
        if scan_error is not None:
            raise DeviceError(f"{scan_error}\n{by_hand}") from None
        raise DeviceError(by_hand) from None


def _readings(lines: list[str], start_hz: int, stop_hz: int, points: int, convert) -> list:
    if len(lines) != points:
        raise DeviceError(f"The NanoVNA sent {len(lines)} line{'' if len(lines) == 1 else 's'} for a {points}-point scan")
    readings, previous = [], start_hz - 1
    for number, line in enumerate(lines, 1):
        parts = line.split()
        if (len(parts) != 3 or not _HZ.fullmatch(parts[0])
                or not all(_NUMBER.fullmatch(p) for p in parts[1:])):
            raise DeviceError(f"Scan line {number} isn't 'frequency real imaginary': {line!r}")
        hz, real, imaginary = int(parts[0]), float(parts[1]), float(parts[2])
        if not (previous < hz <= stop_hz):
            raise DeviceError(f"Scan line {number}: {hz} Hz is out of order or outside {start_hz}-{stop_hz} Hz")
        try:
            readings.append(convert(hz, complex(real, imaginary)))
        except ValueError as error:
            raise DeviceError(f"Scan line {number}: {error}") from None
        previous = hz
    return readings
