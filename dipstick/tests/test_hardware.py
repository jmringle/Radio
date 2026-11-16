"""The real NanoVNA, plugged in (what the fake link can't show: USB, timing, the real firmware).

All but one only ask for the version, board and sweep settings. test_a_40m_scan_puts_the_settings_back
sweeps 40 m once (inside the band, the NanoVNA's tiny signal) and checks your settings come back.
They run only when you ask:

    DIPSTICK_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py
"""

import os
import re

import pytest
from serial.tools import list_ports

from dipstick.device import DeviceError, NanoVNA, find_port
from dipstick.scan import scan

pytestmark = pytest.mark.skipif(os.environ.get("DIPSTICK_HARDWARE") != "1",
                                reason="set DIPSTICK_HARDWARE=1 with the NanoVNA plugged in")


@pytest.fixture(scope="module")
def nano():
    device = NanoVNA.open(find_port(list_ports.comports()))
    yield device
    device.close()


def test_it_answers_with_a_version(nano):
    [version] = nano.ask("version")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)


def test_it_is_a_nanovna(nano):
    assert any("NanoVNA" in line for line in nano.ask("info"))


def test_it_reports_its_sweep_settings(nano):
    [settings] = nano.ask("sweep")
    start, stop, points = map(int, settings.split())
    assert 0 < start < stop and points > 1


def test_asking_twice_stays_in_step(nano):
    assert nano.ask("version") == nano.ask("version")


def test_a_40m_scan_puts_the_settings_back(nano):
    before = nano.ask("sweep")
    first_frequency = nano.ask("frequencies")[0]
    readings = scan(nano, 7_000_000, 7_300_000, 11)
    assert [r.hz for r in readings] == list(range(7_000_000, 7_300_001, 30_000))
    assert nano.ask("sweep") == before
    assert nano.ask("frequencies")[0] == first_frequency  # the frequency list really came back too


def test_a_second_open_is_refused_while_the_first_holds_the_port(nano):
    # QA 2026-11-16, F2: the lock is what stops two programs mixing commands on macOS/Linux.
    # Asks nothing of the NanoVNA: the second open fails before any command is sent.
    with pytest.raises(DeviceError, match="Another program is using the NanoVNA"):
        NanoVNA.open(find_port(list_ports.comports()))
