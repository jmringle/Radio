"""The build check (README threat model, T15)."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_build", Path(__file__).resolve().parents[1] / "packaging" / "check_build.py")
check_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_build)


@pytest.mark.parametrize("name", ["ALL.TXT", "all.txt", ".env", "wsjtx_log.adi", "log.ADIF", "ft8cast.sqlite"])
def test_private_files_are_found_at_any_depth(tmp_path, name):
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    (inner / name).write_text("")
    assert [path.name for path in check_build.private_files(tmp_path)] == [name]


def test_a_clean_build_passes(tmp_path):
    (tmp_path / "page.html").write_text("")
    (tmp_path / "FT8 Forecast").write_text("")
    assert check_build.private_files(tmp_path) == []
