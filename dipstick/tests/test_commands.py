"""Commands sent to the NanoVNA (threat model T1, T2): only read-and-sweep commands on the
allowlist, and arguments that are whole numbers, so nothing can change the NanoVNA's
calibration or settings, or smuggle a second command in."""

import pytest

from dipstick.commands import command


def test_allowed_commands_are_framed_with_a_carriage_return():
    assert command("version") == b"version\r"
    assert command("scan", 7_000_000, 7_300_000, 101, 3) == b"scan 7000000 7300000 101 3\r"


@pytest.mark.parametrize("name", ["clearconfig", "saveconfig", "cal", "reset", "power", "touchcal", "", "VERSION"])
def test_anything_off_the_allowlist_is_refused(name):
    # These erase or overwrite calibration and settings, or change the output level.
    with pytest.raises(ValueError, match="not allowed"):
        command(name)


@pytest.mark.parametrize("arg", ["7000000\rclearconfig", "7e6", 7.0e6, True, "", -1])
def test_arguments_must_be_whole_numbers(arg):
    # A carriage return in an argument would end the scan command and run clearconfig next.
    with pytest.raises(ValueError):
        command("scan", arg, 7_300_000, 101, 3)


def test_a_command_name_cant_carry_a_second_command():
    with pytest.raises(ValueError):
        command("version\rclearconfig")
