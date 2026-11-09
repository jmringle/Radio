"""The simulator and the RTL-SDR source's failure messages (README: acceptance criteria; T4).
No dongle is used: the RTL tests replace the pyrtlsdr import."""
import builtins
import sys
import types

import pytest

from foxhunt import sources
from foxhunt.dsp import SAMPLE_RATE, measure
from foxhunt.meter import Settings
from foxhunt.sources import RtlSource, SimSource, SourceError

N = SAMPLE_RATE // 10
FOX = Settings(146_565_000, 20.0, 0.0)


def reading(source, t=0.0):
    return measure(source.read(N, t=t))


def test_the_simulated_fox_drifts_stronger_and_weaker():
    sim = SimSource(seed=1)
    sim.open(FOX)
    strongest, weakest = reading(sim, t=0.0), reading(sim, t=SimSource.PERIOD_S / 2)
    assert strongest.over_noise_db > weakest.over_noise_db + 20


def test_the_simulator_can_transmit_in_bursts():
    sim = SimSource(seed=1, burst=(30.0, 90.0))
    sim.open(FOX)
    assert reading(sim, t=0.0).over_noise_db > 20  # on (30 s of every 120), at the drift's strongest
    assert abs(reading(sim, t=60.0).over_noise_db) < 3  # off: noise only
    assert reading(sim, t=120.0).over_noise_db > 20  # on again


def test_the_simulator_responds_to_the_attenuator_like_a_real_dongle():
    sim = SimSource(seed=1)
    sim.open(FOX)
    plain = reading(sim)
    sim.open(Settings(FOX.freq_hz, FOX.gain_db, 10.0))
    attenuated = reading(sim)
    assert plain.channel_db - attenuated.channel_db == pytest.approx(10, abs=1)


def test_too_much_gain_overloads_the_simulator():
    sim = SimSource(seed=1)
    assert sim.open(Settings(FOX.freq_hz, 50.0, 0.0)) == 50.0  # the gain it used
    assert reading(sim).overload
    sim.open(FOX)
    assert not reading(sim).overload


def test_reading_before_opening_is_an_error():
    with pytest.raises(SourceError, match="not open"):
        SimSource().read(N)


# --- the RTL-SDR, without one ---

def without_module(monkeypatch, error):
    real_import = builtins.__import__
    def fake(name, *args, **kwargs):
        if name == "rtlsdr":
            raise error
        return real_import(name, *args, **kwargs)
    monkeypatch.delitem(sys.modules, "rtlsdr", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake)


def test_missing_pyrtlsdr_says_what_to_install(monkeypatch):
    without_module(monkeypatch, ModuleNotFoundError("No module named 'rtlsdr'"))
    with pytest.raises(SourceError, match="requirements-rtl.txt"):
        RtlSource().open(FOX)


def test_missing_librtlsdr_says_what_to_install(monkeypatch):
    without_module(monkeypatch, ImportError("Error loading librtlsdr"))
    with pytest.raises(SourceError, match="brew install librtlsdr"):
        RtlSource().open(FOX)


class FakeSdr:
    """Stands in for pyrtlsdr's RtlSdr."""
    valid_gains_db = [0.0, 19.7, 20.7, 49.6]
    fail_read = False

    def __init__(self):
        self.gain = None
        self.closed = False

    def set_agc_mode(self, on):
        self.agc = on

    def read_samples(self, n):
        if FakeSdr.fail_read:
            raise OSError("LIBUSB_ERROR_NO_DEVICE")
        import numpy as np
        return np.zeros(n, dtype=np.complex128)

    def close(self):
        self.closed = True


def with_fake_sdr(monkeypatch, cls=FakeSdr):
    monkeypatch.setitem(sys.modules, "rtlsdr", types.SimpleNamespace(RtlSdr=cls))


def test_no_dongle_plugged_in_says_so(monkeypatch):
    class Missing:
        def __init__(self):
            raise OSError("No devices found")
    with_fake_sdr(monkeypatch, Missing)
    with pytest.raises(SourceError, match="No RTL-SDR found"):
        RtlSource().open(FOX)


def test_open_tunes_below_the_fox_with_fixed_nearest_gain(monkeypatch):
    with_fake_sdr(monkeypatch)
    rtl = RtlSource()
    assert rtl.open(FOX) == 19.7  # nearest step to 20 dB
    sdr = rtl.sdr
    assert sdr.center_freq == FOX.freq_hz - sources.OFFSET_HZ and sdr.sample_rate == SAMPLE_RATE
    assert sdr.agc is False and sdr.gain == 19.7


def test_unplugging_mid_hunt_is_a_source_error(monkeypatch):
    with_fake_sdr(monkeypatch)
    rtl = RtlSource()
    rtl.open(FOX)
    monkeypatch.setattr(FakeSdr, "fail_read", True)
    with pytest.raises(SourceError, match="RTL-SDR stopped"):
        rtl.read(N)
    assert rtl.sdr is None  # closed, so the next open starts clean
