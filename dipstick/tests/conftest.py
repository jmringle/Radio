"""Shared test setup."""

import pytest
import serial


# No test opens a real serial port, apart from test_hardware.py, which asks for the NanoVNA by name
# and runs only when you ask. A test that reached the real port once sent a carriage return to
# whatever was on COM7 (a CH340 that wasn't a NanoVNA, Windows, 2026-11-17): a radio's cable there
# could have keyed it (T3). Tests that check how the port is opened put their own stand-in over this.
@pytest.fixture(autouse=True)
def no_real_serial_ports(request, monkeypatch):
    if request.module.__name__ == "test_hardware":
        return

    def refuse(self):
        raise serial.SerialException(f"tests don't open real serial ports ({self.port})")
    monkeypatch.setattr(serial.Serial, "open", refuse)


# pytest-playwright 0.10.0 (the latest, checked 2026-11-16) supplies a base_url fixture when
# pytest-base-url isn't installed, written as a session fixture on a class instance, which pytest 10
# will refuse (PytestRemovedIn10Warning). The page tests load index.html from a file and never use
# a base URL, so this replaces it; a conftest fixture wins over a plugin's. Remove it once
# pytest-playwright fixes theirs (pyproject's filterwarnings will say if it's still needed).
@pytest.fixture(scope="session")
def base_url():
    return None
