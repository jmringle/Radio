"""Smoke test: the installed `bandcheck` command runs (needs `pip install -e .`)."""

import shutil
import subprocess
import sysconfig

import pytest

# Look in this environment's scripts folder, so a `bandcheck` from elsewhere on
# PATH can't stand in for the one under test.
BANDCHECK = shutil.which("bandcheck", path=sysconfig.get_path("scripts"))


def _run(*args: str) -> subprocess.CompletedProcess:
    if BANDCHECK is None:
        pytest.fail("bandcheck isn't installed in this environment: run `pip install -e .`")
    return subprocess.run([BANDCHECK, *args], capture_output=True, text=True, timeout=30)


def test_installed_command_answers_and_exits_0():
    result = _run("14.074", "data", "general")
    assert result.returncode == 0
    assert result.stdout.startswith("ALLOWED: ")


def test_installed_command_passes_exit_code_3_through():
    # The console-script wrapper must hand main()'s return value to the shell.
    assert _run("146.52", "phone", "general").returncode == 3
