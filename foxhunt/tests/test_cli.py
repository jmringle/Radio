"""Command-line checks that happen before anything starts (README: acceptance criteria)."""
import pytest

from foxhunt.__main__ import main


@pytest.mark.parametrize("args, reason", [
    (["--freq", "2000"], "Frequency must be 0.5-1766 MHz"),
    (["--freq", "146.565", "--gain", "70"], "Gain must be 0-50 dB"),
    (["--freq", "146.565", "--att", "-5"], "Attenuator must be 0-120 dB"),
])
def test_bad_settings_stop_before_starting(capsys, args, reason):
    assert main(args) == 2 and reason in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["--freq", "146.565", "--port", "80"], ["--freq", "146.565", "--source", "hackrf"],
                                  ["--freq", "146.565", "--sim-burst", "30"], ["--freq", "146.565", "--sim-burst", "0/90"],
                                  ["--freq", "146.565", "--sim-burst", "30/x"]])
def test_usage_errors(capsys, args):
    assert main(args) == 2 and "usage: foxhunt" in capsys.readouterr().err
