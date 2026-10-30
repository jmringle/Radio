"""Shared test setup."""

from zoneinfo import ZoneInfo

import pytest

from ft8_forecast import cli


@pytest.fixture(autouse=True)
def eastern_time(monkeypatch):
    """Local times on the page and in the terminal follow this computer's time zone; pin it so
    tests read the same on any machine (GitHub's runners are on UTC). Through cli._local_zone,
    not TZ and time.tzset(), which Windows doesn't have."""
    monkeypatch.setattr(cli, "_local_zone", lambda: ZoneInfo("America/New_York"))
