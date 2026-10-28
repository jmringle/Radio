"""ADIF import, against ADIF 3.1.6 section IV.A (adif.org, checked 2026-10-28).

All callsigns and logs here are made up (N0CALL variants), in WSJT-X's export style.
"""

from datetime import UTC, datetime

import pytest

from ft8_forecast import Contact, parse_adi

HEADER = b"WSJT-X ADIF Export<adif_ver:5>3.1.0\n<programid:6>WSJT-X\n<EOH>\n"


def record(**fields: str) -> bytes:
    """One record with correct lengths, e.g. record(CALL="N0CALL")."""
    return b"".join(f"<{k}:{len(v)}>{v} ".encode() for k, v in fields.items()) + b"<EOR>\n"


def ft8(**overrides: str) -> bytes:
    fields = dict(CALL="N0CALL", GRIDSQUARE="FN31", MODE="FT8", QSO_DATE="20261027",
                  TIME_ON="143015", FREQ="14.075800")
    fields.update(overrides)
    return record(**{k: v for k, v in fields.items() if v is not None})


EXPECTED = Contact("N0CALL", datetime(2026, 10, 27, 14, 30, 15, tzinfo=UTC), 14_075_800, "FN31")


# --- happy path and the spec's format rules ---

def test_reads_a_wsjtx_style_export():
    result = parse_adi(HEADER + ft8())
    assert result.contacts == [EXPECTED]
    assert result.problems == []


def test_reads_a_file_with_no_header():
    # First character "<" means no header (IV.A).
    assert parse_adi(ft8()).contacts == [EXPECTED]


def test_tags_and_names_are_case_insensitive_and_types_ignored():
    data = HEADER.replace(b"<EOH>", b"<eoh>") + (
        b"<call:6:S>N0CALL<Mode:3>FT8<qso_date:8:D>20261027<time_on:6>143015"
        b"<freq:9:N>14.075800<gridsquare:4>fn31<eor>"
    )
    assert parse_adi(data).contacts == [EXPECTED]


def test_field_order_and_text_between_fields_dont_matter():
    data = b"<FREQ:9>14.075800\n\n  junk  <TIME_ON:6>143015<GRIDSQUARE:4>FN31\r\n" \
           b"<QSO_DATE:8>20261027<MODE:3>FT8<CALL:6>N0CALL\n<EOR>"
    assert parse_adi(data).contacts == [EXPECTED]


def test_length_decides_where_data_ends_even_with_brackets_inside():
    # A comment holding "<EOR>" mustn't end the record early.
    result = parse_adi(ft8(COMMENT="tnx <EOR> 73 <CALL:5>"))
    assert result.contacts == [EXPECTED]
    assert result.problems == []


def test_header_specifier_data_cant_hide_a_fake_eoh():
    data = b"Export <PROGRAMID:5><EOH><EOH>\n" + ft8()
    assert parse_adi(data).contacts == [EXPECTED]


def test_zero_length_field_is_allowed():
    assert parse_adi(ft8(COMMENT="")).problems == []


@pytest.mark.parametrize("time_on, expected", [("1430", (14, 30, 0)), ("000000", (0, 0, 0)),
                                               ("235959", (23, 59, 59))])
def test_time_on_accepts_hhmm_and_hhmmss(time_on, expected):
    (contact,) = parse_adi(ft8(TIME_ON=time_on)).contacts
    assert (contact.time.hour, contact.time.minute, contact.time.second) == expected


@pytest.mark.parametrize("grid, expected", [("FN31", "FN31"), ("fn31pr", "FN31"),
                                            ("FN31PR45", "FN31"), ("RR99", "RR99")])
def test_grid_is_kept_to_four_characters(grid, expected):
    assert parse_adi(ft8(GRIDSQUARE=grid)).contacts[0].grid == expected


@pytest.mark.parametrize("grid", [None, "", " "])  # WSJT-X writes <gridsquare:0> when unknown
def test_missing_or_empty_grid_is_fine(grid):
    result = parse_adi(ft8(GRIDSQUARE=grid))
    assert result.contacts[0].grid is None
    assert result.problems == []


@pytest.mark.parametrize("mode", [b"<MODE:2>CW", b"<MODE:3>SSB", b"<MODE:4>MFSK<SUBMODE:3>FT4"])
def test_other_modes_are_counted_not_reported(mode):
    data = ft8().replace(b"<MODE:3>FT8", mode)
    result = parse_adi(data)
    assert (result.contacts, result.problems, result.other_modes) == ([], [], 1)


def test_empty_file_gives_nothing_and_no_error():
    # Whether "nothing imported" is an error is the CLI's decision.
    result = parse_adi(b"")
    assert (result.contacts, result.problems) == ([], [])


# --- damaged files: report the line, skip the record, keep going ---

def test_problem_reports_the_line_the_record_starts_on():
    data = HEADER + ft8() + ft8(CALL="") + ft8()  # header is 3 lines; bad record on line 5
    result = parse_adi(data)
    assert len(result.contacts) == 2
    assert [(p.line, p.message) for p in result.problems] == [(5, "no CALL; record skipped")]


def test_truncated_last_record_is_skipped_and_reported():
    data = HEADER + ft8() + ft8().removesuffix(b"<EOR>\n")
    result = parse_adi(data)
    assert result.contacts == [EXPECTED]
    assert result.problems[0].line == 5
    assert "no <EOR>" in result.problems[0].message


@pytest.mark.parametrize("tail", [b"<CALL:6>N0C", b"<CALL:999999999>N0CALL<EOR>"])
def test_data_running_past_the_end_stops_the_import(tail):
    result = parse_adi(ft8() + tail)
    assert result.contacts == [EXPECTED]
    assert "past the end" in result.problems[0].message


def test_stray_bracket_at_end_is_a_truncated_record():
    result = parse_adi(ft8() + b"<CALL:6>N0CALL <")
    assert result.contacts == [EXPECTED]
    assert "no <EOR>" in result.problems[0].message


@pytest.mark.parametrize("bad_tag", [b"<CALL:six>N0CALL", b"<CALL>N0CALL", b"<CALL:-6>N0CALL",
                                     b"<CALL:\xef\xbc\x96>N0CALL", b"<>"])
def test_unreadable_tag_skips_that_record_only(bad_tag):
    data = ft8().replace(b"<CALL:6>N0CALL", bad_tag) + ft8()
    result = parse_adi(data)
    assert result.contacts == [EXPECTED]
    assert "unreadable tag" in result.problems[0].message


def test_header_without_eoh_reads_nothing():
    result = parse_adi(b"WSJT-X ADIF Export\n" + ft8())
    assert result.contacts == []
    assert "no <EOH>" in result.problems[0].message


def test_duplicate_field_skips_the_record():
    result = parse_adi(ft8(COMMENT="x").replace(b"<COMMENT:1>x", b"<CALL:7>N0CALL2"))
    assert result.contacts == []
    assert "appears twice" in result.problems[0].message


@pytest.mark.parametrize("overrides, message", [
    (dict(CALL=None), "no CALL"),
    (dict(CALL="N0 CALL"), "isn't a callsign"),
    (dict(CALL="N0CALL/"), "isn't a callsign"),
    (dict(CALL="N" * 21), "isn't a callsign"),
    (dict(MODE=None), "no MODE"),
    (dict(QSO_DATE=None), "no QSO_DATE"),
    (dict(TIME_ON=None), "no QSO_DATE"),
    (dict(QSO_DATE="2026-10-27"), "isn't YYYYMMDD"),
    (dict(QSO_DATE="2026102"), "isn't YYYYMMDD"),
    (dict(TIME_ON="14301"), "isn't YYYYMMDD"),
    (dict(QSO_DATE="20261332"), "isn't a real date"),
    (dict(QSO_DATE="20260229"), "isn't a real date"),  # 2026 isn't a leap year
    (dict(TIME_ON="2400"), "isn't a real date"),
    (dict(TIME_ON="143060"), "isn't a real date"),
    (dict(QSO_DATE="19291231"), "before 1930"),
    (dict(FREQ=None), "no FREQ"),
    (dict(FREQ="nan"), "FREQ:"),
    (dict(FREQ="1e1"), "FREQ:"),
    (dict(FREQ="-14.074"), "FREQ:"),
    (dict(FREQ="0"), "FREQ:"),
    (dict(FREQ="14.0758001"), "FREQ:"),  # finer than 1 Hz
])
def test_invalid_field_skips_the_record(overrides, message):
    result = parse_adi(ft8(**overrides) + ft8())
    assert result.contacts == [EXPECTED]
    assert message in result.problems[0].message


def test_earliest_allowed_date_is_accepted():
    assert parse_adi(ft8(QSO_DATE="19300101")).problems == []


def test_non_ascii_field_skips_the_record():
    data = ft8().replace(b"<CALL:6>N0CALL", "<CALL:6>N0CÅL".encode())  # Å is 2 bytes
    result = parse_adi(data + ft8())
    assert result.contacts == [EXPECTED]
    assert "non-ASCII" in result.problems[0].message


@pytest.mark.parametrize("grid", ["FN3", "ZZ99", "F N31", "FNXX", "FN"])
def test_bad_grid_keeps_the_contact_without_it(grid):
    result = parse_adi(ft8(GRIDSQUARE=grid))
    assert result.contacts[0].grid is None
    assert "contact kept without it" in result.problems[0].message
