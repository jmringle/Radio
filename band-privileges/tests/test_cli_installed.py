"""Smoke test: the installed `bandcheck` command runs (needs `pip install -e .`)."""

import subprocess
import sys
from pathlib import Path

# The venv's scripts folder sits next to its python, wherever the venv is.
BANDCHECK = Path(sys.executable).parent / "bandcheck"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BANDCHECK, *args], capture_output=True, text=True, timeout=30)


def test_installed_command_answers_and_exits_0():
    result = _run("14.074", "data", "general")
    assert result.returncode == 0
    assert result.stdout.startswith("ALLOWED: ")


def test_installed_command_passes_exit_code_3_through():
    # The console-script wrapper must hand main()'s return value to the shell.
    assert _run("146.52", "phone", "general").returncode == 3
