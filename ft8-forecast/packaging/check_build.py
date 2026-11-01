"""Fails if a build folder holds logs, a database or settings (T15). Usage: check_build.py <folder>"""

import sys
from pathlib import Path

BLOCKED_NAMES = {"all.txt", ".env"}
BLOCKED_SUFFIXES = {".adi", ".adif", ".sqlite"}


def private_files(build: Path) -> list[Path]:
    return [path for path in build.rglob("*")
            if path.name.lower() in BLOCKED_NAMES or path.suffix.lower() in BLOCKED_SUFFIXES]


if __name__ == "__main__":
    found = private_files(Path(sys.argv[1]))
    for path in found:
        print(f"private file in build: {path}", file=sys.stderr)
    sys.exit(1 if found else 0)
