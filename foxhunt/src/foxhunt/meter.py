"""Turns measurements into readings: checks settings, takes the gain and attenuator back out of
the level, holds the peak and records sessions."""
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foxhunt.dsp import Measurement

# The RTL-SDR Blog V4's tuning range (maker's spec: 500 kHz-1.766 GHz).
MIN_HZ, MAX_HZ = 500_000, 1_766_000_000
MAX_GAIN_DB = 50.0  # the R828D tuner's highest gain step is 49.6 dB
MAX_ATTENUATOR_DB = 120.0  # beyond any handheld step attenuator


@dataclass(frozen=True)
class Settings:
    freq_hz: int  # the fox's frequency
    gain_db: float  # tuner gain asked for; the dongle may use the nearest step
    attenuator_db: float  # what the external attenuator is set to


def _number(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, not {str(value)[:20]!r}.") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a number, not {str(value)[:20]!r}.")
    return number


def parse_settings(freq_mhz, gain_db, attenuator_db) -> Settings:
    """Settings from user input (MHz, dB, dB). ValueError says what's wrong; nothing is half-applied."""
    hz = round(_number(freq_mhz, "Frequency") * 1_000_000)
    if not MIN_HZ <= hz <= MAX_HZ:
        raise ValueError(f"Frequency must be 0.5-1766 MHz (the RTL-SDR V4's range), not {freq_mhz}.")
    gain = _number(gain_db, "Gain")
    if not 0 <= gain <= MAX_GAIN_DB:
        raise ValueError(f"Gain must be 0-{MAX_GAIN_DB:.0f} dB, not {gain_db}.")
    attenuator = _number(attenuator_db, "Attenuator")
    if not 0 <= attenuator <= MAX_ATTENUATOR_DB:
        raise ValueError(f"Attenuator must be 0-{MAX_ATTENUATOR_DB:.0f} dB, not {attenuator_db}.")
    return Settings(hz, gain, attenuator)


def parse_heading(value) -> float:
    """A yagi heading in degrees from user input; 360 is north, the same as 0."""
    if isinstance(value, bool):  # float(True) is 1.0, which isn't a heading anyone typed
        value = str(value)
    heading = _number(value, "Heading")
    if not 0 <= heading <= 360:
        raise ValueError(f"Heading must be 0-360 degrees, not {str(value)[:20]}.")
    return heading % 360


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Meter:
    def __init__(self, settings: Settings, data_dir: Path, node_id: str | None = None,
                 clock: Callable[[], datetime] = _utc_now):
        self.settings = settings
        self.data_dir = data_dir
        self.node_id = node_id  # set by receiver nodes in a later phase
        self.clock = clock
        self.peak_db: float | None = None
        self.last: dict | None = None  # the latest reading
        self.bearings: list[dict] = []  # this frequency's bearings
        self.recording: Path | None = None
        self._file = None

    def apply(self, settings: Settings) -> None:
        """New settings. A new frequency is a new signal, so the peak starts over."""
        if settings.freq_hz != self.settings.freq_hz:
            self.peak_db, self.last, self.bearings = None, None, []
        self.settings = settings

    def reset_peak(self) -> None:
        self.peak_db = None

    def update(self, measurement: Measurement, gain_used: float) -> dict:
        """One reading, as sent to the page and written to a recording."""
        # Gain raises what the dongle sees and the attenuator lowers it; taking both back out
        # keeps readings comparable while you change them. Relative dB, not calibrated dBm.
        level = measurement.channel_db - gain_used + self.settings.attenuator_db
        if not measurement.overload:  # a clipped reading's level is wrong
            self.peak_db = level if self.peak_db is None else max(self.peak_db, level)
        reading = {
            "time": self.clock().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "freq_hz": self.settings.freq_hz,
            "over_noise_db": round(measurement.over_noise_db, 1),
            "level_db": round(level, 1),
            "peak_db": None if self.peak_db is None else round(self.peak_db, 1),
            "noise_db": round(measurement.noise_db, 1),
            "gain_db": gain_used,
            "attenuator_db": self.settings.attenuator_db,
            "overload": measurement.overload,
            # For bearing capture and receiver nodes (later phases); empty for now.
            "heading": None, "lat": None, "lon": None, "node_id": self.node_id,
        }
        self._write(reading)
        self.last = reading
        return reading

    def mark_bearing(self, heading: float) -> dict:
        """Save the yagi's heading with the signal now. ValueError if there's no trustworthy reading."""
        if self.last is None:
            raise ValueError("No signal reading yet; wait for the meter to show one.")
        if self.last["overload"]:  # clipping flattens the peak, so the heading of the peak is a guess
            raise ValueError("Overload: add attenuation or lower the gain before marking a bearing.")
        bearing = {"kind": "bearing", "time": self.clock().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                   "freq_hz": self.settings.freq_hz, "heading": heading, "peak_db": self.last["peak_db"],
                   "level_db": self.last["level_db"], "over_noise_db": self.last["over_noise_db"],
                   "lat": None, "lon": None, "node_id": self.node_id}  # position comes in a later phase
        self.bearings.append(bearing)
        self._write(bearing)
        return bearing

    def _write(self, line: dict) -> None:
        if self._file:
            self._file.write(json.dumps(line) + "\n")
            self._file.flush()  # a crash loses at most the line being written

    def start_recording(self) -> Path:
        """Start a session file named from the time (never from input); already recording: the same file."""
        if self.recording:
            return self.recording
        folder = self.data_dir / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        stem = self.clock().strftime("%Y%m%d-%H%M%SZ")
        for n in range(1, 1000):
            path = folder / (f"{stem}.jsonl" if n == 1 else f"{stem}-{n}.jsonl")
            try:
                self._file = path.open("x", encoding="utf-8")  # "x": never overwrite
            except FileExistsError:
                continue
            self.recording = path
            return path
        raise OSError(f"too many recordings started at {stem}")

    def stop_recording(self) -> None:
        if self._file:
            self._file.close()
        self._file, self.recording = None, None
