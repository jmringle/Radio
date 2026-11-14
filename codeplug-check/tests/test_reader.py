"""Reading a whole CHIRP CSV: channels with their CSV line, and every bad row reported (README: bad input)."""

import pytest

from codeplug_check.chirp import Channel, ReadError, read_channels

HEADER = ("Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,"
          "CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE")


def row(loc=1, name="RPT", freq="146.940000", duplex="-", offset="0.600000", tone="Tone", rtone="100.0",
        ctone="100.0", dtcs="023", rx_dtcs="023", cross="Tone->Tone", mode="FM"):
    # Unused columns hold CHIRP's defaults, as in a real export (CHIRP's tests/images/Generic_CSV.csv).
    return f"{loc},{name},{freq},{duplex},{offset},{tone},{rtone},{ctone},{dtcs},NN,{rx_dtcs},{cross},{mode},5.00,,5W,,,,,"


@pytest.fixture
def csv_file(tmp_path):
    def write(*lines, header=HEADER, bom=False):
        path = tmp_path / "channels.csv"
        path.write_text(("﻿" if bom else "") + "\n".join([header, *lines]) + "\n", encoding="utf-8")
        return path
    return write


def test_a_repeater_channel(csv_file):
    channels, problems = read_channels(csv_file(row()))
    assert problems == []
    assert channels == [Channel(line=2, location=1, name="RPT", rx_hz=146_940_000, tx_hz=146_340_000,
                                tx_tone="Tone 100.0", rx_tone=None, mode="FM")]


def test_byte_order_mark_comments_and_empty_memories(csv_file):
    # CHIRP writes "# ..." comment lines and skips memories with no frequency; Excel adds a byte-order mark.
    channels, problems = read_channels(csv_file("# from the club list", row(loc=1), row(loc=2, freq=""),
                                                row(loc=3, freq="0.000000"), row(loc=4, name="SPX", freq="146.520000", duplex="", tone=""),
                                                bom=True))
    assert problems == []
    assert [(c.line, c.location, c.name) for c in channels] == [(3, 1, "RPT"), (6, 4, "SPX")]


@pytest.mark.parametrize("tone, cross, tx_tone, rx_tone", [
    ("", "Tone->Tone", None, None),  # CrossMode is filled in but unused unless Tone is Cross
    ("Tone", "Tone->Tone", "Tone 88.5", None),  # sends rToneFreq, listens to anything
    ("TSQL", "Tone->Tone", "Tone 100.0", "Tone 100.0"),  # cToneFreq both ways
    ("DTCS", "Tone->Tone", "DTCS 023", "DTCS 023"),
    ("TSQL-R", "Tone->Tone", None, "Tone 100.0"),  # reverse: listens for the tone, sends none
    ("DTCS-R", "Tone->Tone", None, "DTCS 023"),
    ("Cross", "Tone->DTCS", "Tone 88.5", "DTCS 754"),
    ("Cross", "DTCS->Tone", "DTCS 023", "Tone 100.0"),
    ("Cross", "->Tone", None, "Tone 100.0"),
    ("Cross", "DTCS->", "DTCS 023", None),
])
def test_tones_follow_chirps_tone_modes(csv_file, tone, cross, tx_tone, rx_tone):
    channels, problems = read_channels(csv_file(row(tone=tone, rtone="88.5", ctone="100.0", dtcs="023",
                                                    rx_dtcs="754", cross=cross)))
    assert problems == []
    assert (channels[0].tx_tone, channels[0].rx_tone) == (tx_tone, rx_tone)


@pytest.mark.parametrize("bad, problem", [
    (row(freq="146.9400001"), "'146.9400001' isn't a frequency in MHz"),
    (row(duplex="-", offset="0.6.0"), "'0.6.0' isn't a frequency in MHz"),
    (row(duplex="minus"), "Duplex 'minus' isn't one of"),
    (row(tone="CTCSS"), "Tone 'CTCSS' isn't one of"),
    (row(tone="Tone", rtone="1000.0"), "rToneFreq '1000.0' isn't a CTCSS tone"),
    (row(tone="DTCS", dtcs="089"), "DtcsCode '089' isn't a DCS code"),  # octal: no 8 or 9
    (row(tone="Cross", cross="Tone->Off"), "CrossMode 'Tone->Off' isn't one of"),
    (row(loc="A1"), "Location 'A1' isn't a memory number"),
    ("5,SHORT,146.520000", "has 3 columns, the header has 21"),
])
def test_a_bad_row_is_reported_with_its_line_and_the_rest_still_read(csv_file, bad, problem):
    channels, problems = read_channels(csv_file(row(loc=1), bad, row(loc=3)))
    assert [c.location for c in channels] == [1, 3]
    assert len(problems) == 1 and problems[0][0] == 3 and problem in problems[0][1]


def test_unused_tone_columns_are_not_checked(csv_file):
    # A channel without a tone may carry anything in the tone columns; CHIRP ignores them too.
    channels, problems = read_channels(csv_file(row(tone="", rtone="junk", dtcs="999", cross="nonsense")))
    assert problems == [] and channels[0].tx_tone is None


def test_offset_only_counts_when_duplex_uses_it(csv_file):
    # CHIRP keeps a simplex channel's old Offset (Generic_CSV.csv has 147.440000 with Offset 0.600000).
    channels, _ = read_channels(csv_file(row(freq="147.440000", duplex="", offset="junk")))
    assert channels[0].tx_hz == 147_440_000


def test_a_missing_file(tmp_path):
    with pytest.raises(ReadError, match="Can't read nope.csv"):
        read_channels(tmp_path / "nope.csv")


def test_a_file_over_5_mb(tmp_path):
    path = tmp_path / "huge.csv"
    path.write_text(HEADER + "\n" + "x" * (5 * 1024 * 1024))
    with pytest.raises(ReadError, match="over 5 MB"):
        read_channels(path)


def test_a_file_that_isnt_utf8(tmp_path):
    path = tmp_path / "latin.csv"
    path.write_bytes((HEADER + "\n" + row(name="CAF\xc9")).encode("latin-1"))
    with pytest.raises(ReadError, match="isn't UTF-8 text"):
        read_channels(path)


@pytest.mark.parametrize("header, missing", [("Name,Frequency", "Location"), ("Location,Name", "Frequency"),
                                             ("Channel,Name,RX Freq", "Location or Frequency")])
def test_a_csv_that_isnt_from_chirp(csv_file, header, missing):
    with pytest.raises(ReadError, match=f"isn't a CHIRP CSV export: no {missing} column"):
        read_channels(csv_file(header=header))


def test_an_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(ReadError, match="is empty"):
        read_channels(path)


def test_broken_quoting_names_its_line(csv_file):
    with pytest.raises(ReadError, match="line 3: not readable as CSV"):
        read_channels(csv_file(row(), '2,"OPEN QUOTE,146.52'))


@pytest.mark.parametrize("code", [0x2028, 0x2029, 0x85, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E])
def test_only_carriage_return_and_line_feed_end_a_row(csv_file, code):
    # str.splitlines() also breaks on these; CSV doesn't (CHIRP opens files with newline="").
    name = "A" + chr(code) + "B"
    channels, problems = read_channels(csv_file(row(name=name), row(loc=2)))
    assert problems == [] and [(c.line, c.name) for c in channels] == [(2, name), (3, "RPT")]


def test_windows_line_endings(tmp_path):
    path = tmp_path / "crlf.csv"
    path.write_bytes((HEADER + "\r\n" + row() + "\r\n").encode())
    channels, problems = read_channels(path)
    assert problems == [] and channels[0].line == 2
