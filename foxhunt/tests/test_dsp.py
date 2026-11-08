"""The signal math (README: How a reading is made; acceptance criteria). Made-up IQ samples only."""
import numpy as np
import pytest

from foxhunt.dsp import CHANNEL_HZ, OFFSET_HZ, SAMPLE_RATE, measure

N = SAMPLE_RATE // 10  # one reading's worth: 0.1 s


def iq(tone_db=None, offset=OFFSET_HZ, noise=0.01, n=N, seed=1):
    """Complex noise, plus a tone `tone_db` dB above the noise power if given."""
    rng = np.random.default_rng(seed)
    samples = noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    if tone_db is not None:
        amplitude = noise * 10 ** (tone_db / 20)
        samples = samples + amplitude * np.exp(2j * np.pi * offset * np.arange(n) / SAMPLE_RATE)
    return samples.astype(np.complex64)


def tone(amplitude, offset, n=N):
    return (amplitude * np.exp(2j * np.pi * offset * np.arange(n) / SAMPLE_RATE)).astype(np.complex64)


def test_noise_alone_reads_about_zero_over_noise():
    assert measure(iq()).over_noise_db == pytest.approx(0, abs=1)


def test_a_signal_20_db_stronger_reads_20_db_stronger():
    weak, strong = measure(iq(tone_db=10)), measure(iq(tone_db=30))
    assert strong.channel_db - weak.channel_db == pytest.approx(20, abs=1)
    assert strong.over_noise_db > weak.over_noise_db + 18


def test_a_signal_outside_the_channel_doesnt_count():
    beside = measure(iq(tone_db=30, offset=OFFSET_HZ + 3 * CHANNEL_HZ))
    assert beside.over_noise_db == pytest.approx(0, abs=1)


def test_a_strong_signal_inside_the_noise_window_doesnt_raise_the_floor():
    # Another station 50 kHz away sits in the noise window; the median ignores it.
    quiet = measure(iq(tone_db=20))
    busy = measure(iq(tone_db=20) + tone(0.3, OFFSET_HZ + 50_000))  # about 30 dB over the noise
    assert busy.noise_db == pytest.approx(quiet.noise_db, abs=1)


def test_clipping_is_overload():
    clipped = np.clip(iq(tone_db=60).real, -1, 1) + 1j * np.clip(iq(tone_db=60).imag, -1, 1)
    assert measure(clipped.astype(np.complex64)).overload
    assert not measure(iq(tone_db=20)).overload


@pytest.mark.parametrize("bad", [np.array([], dtype=np.complex64), np.zeros(100, dtype=np.complex64)])
def test_too_few_samples_is_an_error(bad):
    with pytest.raises(ValueError, match="samples"):
        measure(bad)


def test_silence_doesnt_divide_by_zero():
    reading = measure(np.zeros(N, dtype=np.complex64))
    assert np.isfinite(reading.channel_db) and np.isfinite(reading.over_noise_db)
