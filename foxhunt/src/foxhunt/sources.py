"""Where IQ samples come from: a real RTL-SDR, or a simulator for trying the meter without one.
Both raise SourceError with a message meant for the page."""
import math
import time

import numpy as np

from foxhunt.dsp import OFFSET_HZ, SAMPLE_RATE
from foxhunt.meter import Settings


class SourceError(Exception):
    """A problem with the signal source, worded for the person at the page."""


class SimSource:
    """A made-up fox that drifts stronger and weaker, like sweeping a yagi past it. Gain raises
    what it sees, the attenuator lowers it, and too much clips, as on a real dongle."""
    PERIOD_S = 20.0  # one strong-weak-strong swing
    NOISE_AT_20_DB = 0.005  # sample noise level at 20 dB gain

    def __init__(self, seed: int | None = None, realtime: bool = False):
        self.rng = np.random.default_rng(seed)
        self.realtime = realtime  # pace reads to the real sample rate, as the dongle does
        self.settings: Settings | None = None
        self.started = time.monotonic()

    def open(self, settings: Settings) -> float:
        self.settings = settings
        return settings.gain_db  # any gain is "supported"

    def read(self, n: int, t: float | None = None) -> np.ndarray:
        """n samples at time t (seconds into the swing; default: since the simulator started)."""
        if self.settings is None:
            raise SourceError("The simulator is not open.")
        if self.realtime:
            time.sleep(n / SAMPLE_RATE)
        t = time.monotonic() - self.started if t is None else t
        gain = 10 ** ((self.settings.gain_db - 20) / 20)
        noise = self.NOISE_AT_20_DB * gain
        # Strength against the noise across the whole sample rate. The meter's 12.5 kHz channel
        # holds about 19 dB less noise, so this reads about 5-45 dB over noise (before the attenuator).
        strength_db = 6 + 20 * math.cos(2 * math.pi * t / self.PERIOD_S) - self.settings.attenuator_db
        amplitude = noise * 10 ** (strength_db / 20)
        k = np.arange(n)
        samples = noise * (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)) / math.sqrt(2)
        samples += amplitude * np.exp(2j * np.pi * OFFSET_HZ * k / SAMPLE_RATE)
        # The ADC can't go past full scale.
        return (np.clip(samples.real, -1, 1) + 1j * np.clip(samples.imag, -1, 1)).astype(np.complex64)

    def close(self) -> None:
        self.settings = None


class RtlSource:
    """An RTL-SDR through pyrtlsdr, tuned OFFSET_HZ below the fox with fixed gain (no AGC)."""

    def __init__(self):
        self.sdr = None

    def open(self, settings: Settings) -> float:
        """Opens (or retunes) the dongle; returns the gain step it actually uses."""
        try:
            from rtlsdr import RtlSdr  # loads librtlsdr, so only when a dongle is wanted
        except ModuleNotFoundError:
            raise SourceError("pyrtlsdr isn't installed: pip install -r requirements-rtl.txt") from None
        except (ImportError, OSError):
            raise SourceError("librtlsdr wasn't found: brew install librtlsdr") from None
        try:
            if self.sdr is None:
                self.sdr = RtlSdr()
            sdr = self.sdr
            sdr.sample_rate = SAMPLE_RATE
            sdr.center_freq = settings.freq_hz - OFFSET_HZ
            sdr.set_agc_mode(False)  # AGC would change readings as you move
            gain = min(sdr.valid_gains_db, key=lambda step: abs(step - settings.gain_db))
            sdr.gain = gain
            return gain
        except OSError as error:
            self.close()
            raise SourceError(f"No RTL-SDR found: is it plugged in? ({error})") from None

    def read(self, n: int) -> np.ndarray:
        if self.sdr is None:
            raise SourceError("The RTL-SDR is not open.")
        try:
            samples = self.sdr.read_samples(n)
        except OSError as error:
            self.close()
            raise SourceError(f"RTL-SDR stopped: is it still plugged in? ({error})") from None
        return np.asarray(samples, dtype=np.complex64)

    def close(self) -> None:
        if self.sdr is not None:
            try:
                self.sdr.close()
            except OSError:
                pass  # already gone (unplugged)
        self.sdr = None

