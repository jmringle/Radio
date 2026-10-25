"""bandcheck CLI: arguments, output and exit codes (README acceptance criteria)."""

import pytest

from band_privileges.cli import main


def test_allowed_prints_result_line_and_exits_0(capsys):
    code = main(["14.074", "data", "general"])
    out = capsys.readouterr().out
    assert code == 0
    assert out == "ALLOWED: data is allowed here (§97.301(d), §97.305(c)(3)(ix))\n"


def test_denied_prints_result_line_and_exits_1(capsys):
    code = main(["14.200", "phone", "general"])
    out = capsys.readouterr().out
    assert code == 1
    assert out == "DENIED: general privileges do not include this frequency (§97.301)\n"


def test_not_covered_prints_result_line_without_citations_and_exits_3(capsys):
    code = main(["146.52", "phone", "general"])
    out = capsys.readouterr().out
    assert code == 3
    assert out == "NOT COVERED: only HF 1.8-29.7 MHz is covered by this tool\n"


def test_note_is_printed_on_its_own_line(capsys):
    code = main(["28.400", "phone", "technician"])
    out = capsys.readouterr().out
    assert code == 0
    assert out == (
        "ALLOWED: phone is allowed here (§97.301(e), §97.305(c)(3)(xviii))\n"
        "NOTE: SSB only (J3E/R3E), §97.307(f)(10)\n"
    )


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["abc", "data", "general"], "frequency must be a number"),
        (["nan", "data", "general"], "frequency must be finite"),
        (["0", "data", "general"], "greater than 0"),
        (["-14.074", "data", "general"], "greater than 0"),  # not mistaken for a flag
        (["14.0740001", "data", "general"], "finer than 1 Hz"),
        # 1000 or more: probably kHz, so hint at the MHz value.
        (["14074", "data", "general"], "did you mean 14.074 MHz?"),
        (["1000", "cw", "extra"], "did you mean 1 MHz?"),
        (["14.074", "ssb", "general"], "mode must be one of: cw, phone, data, image"),
        (["14.074", "data", "advanced"], "class must be one of: technician, general, extra"),
        ([], "required"),
        (["14.074", "data"], "required"),
        (["14.074", "data", "general", "extra"], "unrecognized arguments"),
    ],
)
def test_bad_input_exits_2_with_message_on_stderr(capsys, argv, message):
    code = main(argv)
    captured = capsys.readouterr()
    assert code == 2
    assert message in captured.err
    assert captured.out == ""  # a script never mistakes an error for an answer


def test_999_mhz_is_valid_input_not_covered_no_khz_hint(capsys):
    assert main(["999.999", "cw", "extra"]) == 3


def test_mode_and_class_are_case_insensitive(capsys):
    assert main(["14.074", "DATA", "General"]) == 0
