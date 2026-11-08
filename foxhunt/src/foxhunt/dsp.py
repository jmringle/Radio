"""Signal strength from IQ samples: power in the fox's channel, the noise floor beside it, and
whether the dongle is clipping. Pure numpy, no hardware, so it's tested with made-up samples."""
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 1_024_000  # samples/s: enough room for the offset and the noise window either side
OFFSET_HZ = 200_000  # the dongle tunes this far below the fox, keeping it off the DC spike
CHANNEL_HZ = 12_500  # a narrow FM fox fits in this
NOISE_NEAR_HZ, NOISE_FAR_HZ = 20_000, 100_000  # noise window, either side of the fox
FFT_SIZE = 8192  # 125 Hz bins at 1.024 MHz
CLIP_LEVEL = 0.99  # samples are scaled to -1..1; the 8-bit ADC tops out here
OVERLOAD_SHARE = 0.001  # more than 0.1% of samples at full scale is overload
_TINY = 1e-20  # keeps log10 finite on all-zero input


@dataclass(frozen=True)
class Measurement:
    channel_db: float  # power in the channel, dB relative to full scale (dBFS)
    noise_db: float  # noise floor in the same bandwidth, dBFS
    over_noise_db: float  # channel_db - noise_db: the hot/cold reading
    overload: bool  # the ADC is clipping: add attenuation or lower the gain


def measure(samples: np.ndarray, offset_hz: int = OFFSET_HZ, sample_rate: int = SAMPLE_RATE,
            channel_hz: int = CHANNEL_HZ) -> Measurement:
    """One reading from a block of IQ samples (complex, scaled to -1..1)."""
    segments = len(samples) // FFT_SIZE
    if segments == 0:
        raise ValueError(f"need at least {FFT_SIZE} samples, got {len(samples)}")
    clipped = (np.abs(samples.real) >= CLIP_LEVEL) | (np.abs(samples.imag) >= CLIP_LEVEL)
    overload = bool(clipped.mean() > OVERLOAD_SHARE)

    # Averaged FFTs (Welch). This scaling makes the bins add up to the signal's mean power
    # (Parseval), so a band's power is the sum of its bins.
    window = np.hanning(FFT_SIZE)
    blocks = samples[: segments * FFT_SIZE].reshape(segments, FFT_SIZE) * window
    power = (np.abs(np.fft.fft(blocks, axis=1)) ** 2).mean(axis=0) / (FFT_SIZE * (window ** 2).sum())
    freqs = np.fft.fftfreq(FFT_SIZE, 1 / sample_rate)

    away = np.abs(freqs - offset_hz)
    channel = away <= channel_hz / 2
    noise_bins = (away >= NOISE_NEAR_HZ) & (away <= NOISE_FAR_HZ)
    channel_power = power[channel].sum()
    # The median per bin ignores other stations in the window; scaled to the channel's width.
    noise_power = np.median(power[noise_bins]) * channel.sum()
    channel_db = 10 * np.log10(channel_power + _TINY)
    noise_db = 10 * np.log10(noise_power + _TINY)
    return Measurement(float(channel_db), float(noise_db), float(channel_db - noise_db), overload)
