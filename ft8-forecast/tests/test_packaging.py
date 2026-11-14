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


def test_the_build_includes_every_page_file():
    """The spec names its files one by one (so data/ and .env can't come along); a page file left
    out works from source but is missing in the app, as busy.js nearly was (2026-11-13)."""
    root = Path(__file__).resolve().parents[1]
    spec_text = (root / "packaging" / "ft8forecast.spec").read_text()
    source = root / "src" / "ft8_forecast"
    files = [path.relative_to(source).as_posix() for folder in ("templates", "static")
             for path in (source / folder).iterdir() if path.is_file()]
    assert files and [name for name in files if f"{{source}}/{name}" not in spec_text] == []
