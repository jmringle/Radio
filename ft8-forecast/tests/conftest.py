"""Shared test setup."""

import time

import pytest


@pytest.fixture(autouse=True)
def eastern_time(monkeypatch):
    """Local times on the page and in the terminal follow this computer's time zone; pin it so
    tests read the same on any machine (GitHub's runners are on UTC)."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()
