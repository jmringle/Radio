"""ALL.TXT import, against the layout of the user's real file (surveyed 2026-10-28).

Lines copy that file's columns exactly; callsigns and grids are made up.
"""

from datetime import UTC, datetime

import pytest

from ft8_forecast import Decode, parse_all_txt


def line(msg: str, *, ts="261027_143015", dial="14.074", direction="Rx", mode="FT8", snr="-9") -> bytes:
    return f"{ts} {dial:>9} {direction} {mode} {snr:>6}  0.2  627 {msg}\r\n".encode()


WHEN = datetime(2026, 10, 27, 14, 30, 15, tzinfo=UTC)


def only(data: bytes) -> Decode:
    result = parse_all_txt([data])
    assert result.problems == []
    (decode,) = result.decodes
    return decode


# --- happy path ---

def test_reads_a_decode_line():
    assert only(line("N0CALL/M N0CALL FN31")) == Decode(WHEN, 14_074_000, False, -9, "N0CALL", "FN31")


def test_reads_your_own_transmission():
    decode = only(line("CQ N0CALL AA00", direction="Tx", snr="0"))
    assert decode.transmit is True


def test_reads_a_file_object_line_by_line(tmp_path):
    path = tmp_path / "ALL.TXT"
    path.write_bytes(line("CQ N0CALL FN31") + line("CQ N0CALL/P AA00", dial="7.074"))
    with path.open("rb") as file:
        result = parse_all_txt(file)
    assert [d.dial_hz for d in result.decodes] == [14_074_000, 7_074_000]


@pytest.mark.parametrize("snr", ["-26", "0", "42"])  # the range seen in the real file
def test_snr_is_read(snr):
    assert only(line("CQ N0CALL FN31", snr=snr)).snr_db == int(snr)


def test_lf_line_endings_work_too():
    assert only(line("CQ N0CALL FN31").replace(b"\r\n", b"\n")).sender == "N0CALL"


def test_blank_lines_are_ignored():
    result = parse_all_txt([b"\r\n", line("CQ N0CALL FN31"), b"   \n"])
    assert (len(result.decodes), result.problems) == (1, [])


# --- who sent it, and where they are ---

@pytest.mark.parametrize("msg, sender, grid", [
    ("CQ N0CALL FN31", "N0CALL", "FN31"),
    ("CQ N0CALL", "N0CALL", None),
    ("CQ DX N0CALL FN31", "N0CALL", "FN31"),
    ("CQ POTA N0CALL/P AA00", "N0CALL/P", "AA00"),
    ("N0CALL/M N0CALL FN31", "N0CALL", "FN31"),  # a reply carries the sender's grid
    ("N0CALL/M N0CALL -07", "N0CALL", None),
    ("N0CALL/M N0CALL R-07", "N0CALL", None),
    ("N0CALL/M N0CALL RR73", "N0CALL", None),  # RR73 is the sign-off, not grid RR73
    ("N0CALL/M N0CALL 73", "N0CALL", None),
    ("N0CALL/M N0CALL", "N0CALL", None),
    ("N0CALL/M <N0CALL> FN31", "N0CALL", "FN31"),  # hashed call WSJT-X resolved
    ("CQ N0CALL FN31 a1", "N0CALL", "FN31"),  # a priori tag dropped
    ("N0CALL/M N0CALL FN31 a9", "N0CALL", "FN31"),
    ("CQ N0CALL RR99", "N0CALL", "RR99"),  # the last real square
])
def test_sender_and_grid(msg, sender, grid):
    decode = only(line(msg))
    assert (decode.sender, decode.grid) == (sender, grid)


@pytest.mark.parametrize("msg", [
    "N0CALL/M <...> FN31",  # hash WSJT-X couldn't resolve
    "TNX FER QSO",  # free text: "FER" has no digit, so not a call
    "CQ",
    "",
    "CQ DX POTA N0CALL FN31",  # unrecognized CQ shape: don't guess
    "N0CALL/M N0CALLN0CALLN0CA FN31",  # 16 characters: longer than any callsign
    "N0CALL/M 12345 FN31",  # no letter
])
def test_unknown_sender_is_none_but_the_decode_still_counts(msg):
    decode = only(line(msg))
    assert (decode.sender, decode.grid) == (None, None)


@pytest.mark.parametrize("grid", ["SA00", "FN3", "FNXX", "fn31"])
def test_not_a_grid(grid):
    assert only(line(f"CQ N0CALL {grid}")).grid is None


# --- skipped on purpose, counted, not errors ---

@pytest.mark.parametrize("mode", ["FT4", "JTTY"])
def test_other_modes_are_counted(mode):
    result = parse_all_txt([line("CQ N0CALL FN31", mode=mode)])
    assert (result.decodes, result.problems, result.other_modes) == ([], [], 1)


def test_unknown_dial_frequency_is_counted():
    # WSJT-X logs 0.000 when it doesn't know the frequency, so the band is unknown.
    result = parse_all_txt([line("CQ N0CALL FN31", dial="0.000")])
    assert (result.decodes, result.problems, result.unknown_dial) == ([], [], 1)


def test_lines_out_of_time_order_are_all_kept():
    later, earlier = line("CQ N0CALL FN31", ts="261027_143030"), line("CQ N0CALL FN31")
    assert len(parse_all_txt([later, earlier]).decodes) == 2


# --- damaged lines: reported with the line number, rest of the file kept ---

@pytest.mark.parametrize("bad", [
    b"garbage\r\n",
    line("CQ N0CALL FN31").replace(b"Rx", b"RX"),
    line("CQ N0CALL FN31").replace(b"261027_143015", b"2026-10-27 14:30"),  # another program's layout
    line("CQ N0CALL FN31").replace(b"-9", b"x9"),
    line("CQ N0CALL FN31", dial="14074"),  # no decimal point
    line("CQ N0CALL FN31", dial="1e1"),
    line("CQ N0CALL FN31", snr="-1234"),
    line("CQ N0CALL FN31", ts="261027 143015"),
    line("CQ N0CALL FN31")[:30],  # truncated mid-line
])
def test_malformed_line_is_reported(bad):
    result = parse_all_txt([line("CQ N0CALL FN31"), bad, line("CQ N0CALL FN31")])
    assert len(result.decodes) == 2
    assert [p.line for p in result.problems] == [2]
    assert "not an ALL.TXT decode line" in result.problems[0].message


@pytest.mark.parametrize("ts", ["261332_143015", "260229_143015", "261027_240000", "261027_143060"])
def test_impossible_date_or_time_is_reported(ts):
    result = parse_all_txt([line("CQ N0CALL FN31", ts=ts)])
    assert result.decodes == []
    assert "isn't a real date" in result.problems[0].message


def test_non_ascii_line_is_reported():
    result = parse_all_txt([line("CQ N0CÅLL FN31"), line("CQ N0CALL FN31")])
    assert len(result.decodes) == 1
    assert result.problems[0].line == 1 and "non-ASCII" in result.problems[0].message


def test_long_garbage_line_message_is_shortened():
    result = parse_all_txt([b"x" * 100_000])
    assert len(result.problems[0].message) < 100
