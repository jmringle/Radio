"""Settings, level compensation, peak hold and recording (README: acceptance criteria; T3, T4)."""
import json
from datetime import UTC, datetime

import pytest

from foxhunt.dsp import Measurement
from foxhunt.meter import Meter, Settings, parse_settings

NOW = datetime(2026, 11, 8, 15, 30, 0, tzinfo=UTC)


def meter(tmp_path, **kwargs):
    return Meter(Settings(146_565_000, 20.0, 0.0), tmp_path, clock=lambda: NOW, **kwargs)


def m(channel_db, over_noise_db=20.0, overload=False):
    return Measurement(channel_db, channel_db - over_noise_db, over_noise_db, overload)


# --- settings ---

@pytest.mark.parametrize("mhz, hz", [(146.565, 146_565_000), (0.5, 500_000), (1766, 1_766_000_000), ("433.1", 433_100_000)])
def test_frequencies_in_the_v4s_range(mhz, hz):
    assert parse_settings(mhz, 20, 0).freq_hz == hz


@pytest.mark.parametrize("mhz", [0.499, 1766.001, -146, "abc", "", None, float("nan"), float("inf")])
def test_frequencies_outside_it_are_refused(mhz):
    with pytest.raises(ValueError, match="Frequency"):
        parse_settings(mhz, 20, 0)


@pytest.mark.parametrize("gain", [-0.1, 50.1, "x", float("nan")])
def test_bad_gain_is_refused(gain):
    with pytest.raises(ValueError, match="Gain"):
        parse_settings(146.565, gain, 0)


@pytest.mark.parametrize("att", [-1, 120.1, "ten", None, float("inf")])
def test_bad_attenuator_is_refused(att):
    with pytest.raises(ValueError, match="Attenuator"):
        parse_settings(146.565, 20, att)


def test_the_edges_are_allowed():
    assert parse_settings(146.565, 0, 120) == Settings(146_565_000, 0.0, 120.0)
    assert parse_settings(146.565, 50, 0).gain_db == 50.0


# --- level and peak ---

def test_level_takes_out_gain_and_attenuator(tmp_path):
    meter_ = meter(tmp_path)
    before = meter_.update(m(-40), gain_used=20.0)["level_db"]
    meter_.apply(Settings(146_565_000, 20.0, 10.0))  # 10 dB more attenuation: the dongle sees 10 dB less
    after = meter_.update(m(-50), gain_used=20.0)["level_db"]
    assert before == after == -60.0


def test_level_uses_the_gain_the_dongle_actually_set(tmp_path):
    assert meter(tmp_path).update(m(-40), gain_used=19.7)["level_db"] == -59.7


def test_peak_holds_the_highest_level_until_reset(tmp_path):
    meter_ = meter(tmp_path)
    meter_.update(m(-40), 20.0)
    assert meter_.update(m(-55), 20.0)["peak_db"] == -60.0
    meter_.reset_peak()
    assert meter_.update(m(-55), 20.0)["peak_db"] == -75.0


def test_an_overloaded_reading_doesnt_set_the_peak(tmp_path):
    meter_ = meter(tmp_path)
    meter_.update(m(-40), 20.0)
    assert meter_.update(m(-10, overload=True), 20.0)["peak_db"] == -60.0  # clipped: its level is wrong


def test_a_new_frequency_resets_the_peak_but_a_new_attenuator_doesnt(tmp_path):
    meter_ = meter(tmp_path)
    meter_.update(m(-40), 20.0)
    meter_.apply(Settings(146_565_000, 20.0, 10.0))
    assert meter_.update(m(-60), 20.0)["peak_db"] == -60.0
    meter_.apply(Settings(147_000_000, 20.0, 10.0))
    assert meter_.update(m(-60), 20.0)["peak_db"] == -70.0


def test_every_reading_has_the_fields_later_phases_need(tmp_path):
    reading = meter(tmp_path, node_id="N0CALL-1").update(m(-40), 20.0)
    assert {"heading", "lat", "lon"} <= reading.keys() and reading["heading"] is None
    assert reading["node_id"] == "N0CALL-1" and reading["time"] == "2026-11-08T15:30:00.000Z"
    assert reading["freq_hz"] == 146_565_000 and reading["over_noise_db"] == 20.0


# --- recording ---

def test_recording_writes_one_json_line_per_reading(tmp_path):
    meter_ = meter(tmp_path)
    path = meter_.start_recording()
    first, second = meter_.update(m(-40), 20.0), meter_.update(m(-45), 20.0)
    assert path == tmp_path / "sessions" / "20261108-153000Z.jsonl"
    assert [json.loads(line) for line in path.read_text().splitlines()] == [first, second]  # flushed as written
    meter_.stop_recording()
    meter_.update(m(-50), 20.0)
    assert len(path.read_text().splitlines()) == 2


def test_two_recordings_in_the_same_second_dont_overwrite(tmp_path):
    meter_ = meter(tmp_path)
    first = meter_.start_recording()
    meter_.update(m(-40), 20.0)
    meter_.stop_recording()
    second = meter_.start_recording()
    assert first != second and second.name == "20261108-153000Z-2.jsonl"
    assert first.read_text()  # the first one is untouched


def test_starting_twice_keeps_the_same_file(tmp_path):
    meter_ = meter(tmp_path)
    assert meter_.start_recording() == meter_.start_recording()
