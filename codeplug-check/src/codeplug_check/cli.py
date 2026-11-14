"""codeplug-check FILE.csv: check a CHIRP channel list and print what's wrong.

Exit codes: 0 no errors (warnings and notes don't fail), 1 at least one error, 2 the file
can't be checked or the command was used wrongly.
"""

import argparse
import sys
import unicodedata
from pathlib import Path

from codeplug_check.checks import check
from codeplug_check.chirp import ReadError, read_channels

MAX_NAME = 40  # characters of a channel name to print; CHIRP radios store far fewer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codeplug-check", description="Check a CHIRP channel list (CSV export).")
    parser.add_argument("file", type=Path, help="a CSV exported from CHIRP (File > Export)")
    args = parser.parse_args(argv)
    name = _safe(args.file.name)
    try:
        channels, problems = read_channels(args.file)
    except ReadError as error:
        print(f"codeplug-check: {_safe(str(error))}", file=sys.stderr)
        return 2
    findings = check(channels)

    summary = f"{name}: {len(channels)} channel{'' if len(channels) == 1 else 's'} checked"
    if problems:
        summary += f", {len(problems)} row{'' if len(problems) == 1 else 's'} couldn't be read"
    if not problems and not findings:
        print(summary + ", no problems found.")
        return 0
    print(summary)
    # Unreadable rows are errors: a row the check couldn't see may be the one that's wrong.
    unread = [(line, f"  line {line}: {_safe(message)}") for line, message in problems]
    groups = {severity: [(f.line, f'  line {f.line}, location {f.location} "{_safe(f.name[:MAX_NAME])}": {_safe(f.message)}')
                         for f in findings if f.severity == severity]
              for severity in ("error", "warning", "note")}
    groups["error"] = sorted(unread + groups["error"], key=lambda item: item[0])
    for severity, title in (("error", "Errors"), ("warning", "Warnings"), ("note", "Notes")):
        if groups[severity]:
            print(f"\n{title} ({len(groups[severity])})")
            print("\n".join(text for _, text in groups[severity]))
    return 1 if groups["error"] else 0


def _safe(text: str) -> str:
    """Text from the file, made safe for a terminal (T2): every control or format character
    (ANSI escapes, bells, right-to-left overrides) becomes U+FFFD, so you can see one was there."""
    return "".join("\ufffd" if _unsafe(ch) else ch for ch in text)


def _unsafe(ch: str) -> bool:
    # C*: control, format (ANSI escapes, bells, right-to-left overrides), private, unassigned.
    # Zl/Zp: the Unicode line and paragraph separators, which some terminals break lines on.
    category = unicodedata.category(ch)
    return category[0] == "C" or category in ("Zl", "Zp")
