"""The real NanoVNA, plugged in (what the fake link can't show: USB, timing, the real firmware).

Read-only: these only ask for the version, board and current sweep settings, so they change
nothing on the NanoVNA and start no sweep of their own. They run only when you ask:

    DIPSTICK_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py
"""

import os
import re

import pytest
from serial.tools import list_ports

from dipstick.device import NanoVNA, find_port

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
