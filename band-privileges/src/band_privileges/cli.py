"""bandcheck: command-line front end for the rule engine."""

import argparse
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from band_privileges.rules import (
    LicenseClass,
    Mode,
    Status,
    check,
    parse_choice,
    parse_frequency,
)

# Status -> (output label, exit code). Exit codes are in the README; argparse
# already uses 2 for usage errors, and bad input of ours uses 2 as well.
_OUTCOMES = {
    Status.ALLOWED: ("ALLOWED", 0),
    Status.DENIED: ("DENIED", 1),
    Status.NOT_COVERED: ("NOT COVERED", 3),
}

E = TypeVar("E", bound=Enum)


def _names(enum: type[Enum]) -> str:
    return ", ".join(member.value for member in enum)


def _choice(enum: type[E], name: str) -> Callable[[str], E]:
    # Our own message instead of argparse's `choices`, whose wording differs
    # between Python versions.
    def convert(text: str) -> E:
        try:
            return parse_choice(enum, name, text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from None

    return convert


def _frequency(text: str) -> int:
    try:
        return parse_frequency(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bandcheck",
        description="Check US amateur HF privileges (47 CFR Part 97, ITU Region 2).",
        epilog=(
            "Disclaimer: advisory only, no warranty. The control operator is solely "
            "responsible for every transmission; verify against current 47 CFR Part 97."
        ),
    )
    parser.add_argument("freq", type=_frequency, help="frequency in MHz, e.g. 14.074")
    parser.add_argument("mode", type=_choice(Mode, "mode"), help=_names(Mode))
    parser.add_argument(
        "license_class",
        metavar="class",
        type=_choice(LicenseClass, "class"),
        help=_names(LicenseClass),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        # argparse has printed usage and the error to stderr (code 2), or the
        # help text (code 0). Return the code so tests can call main() directly.
        return int(exit_.code or 0)

    result = check(args.freq, args.mode, args.license_class)
    label, code = _OUTCOMES[result.status]
    cites = f" ({', '.join(result.citations)})" if result.citations else ""
    print(f"{label}: {result.reason}{cites}")
    for note in result.notes:
        print(f"NOTE: {note}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return code
