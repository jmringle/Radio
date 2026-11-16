"""Shared test setup."""

import pytest


# pytest-playwright 0.10.0 (the latest, checked 2026-11-16) supplies a base_url fixture when
# pytest-base-url isn't installed, written as a session fixture on a class instance, which pytest 10
# will refuse (PytestRemovedIn10Warning). The page tests load index.html from a file and never use
# a base URL, so this replaces it; a conftest fixture wins over a plugin's. Remove it once
# pytest-playwright fixes theirs (pyproject's filterwarnings will say if it's still needed).
@pytest.fixture(scope="session")
def base_url():
    return None
