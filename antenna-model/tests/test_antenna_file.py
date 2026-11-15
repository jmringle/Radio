"""Reading an antenna file (README acceptance criteria: antenna files, bad input; threat model T1, T2).

Every test writes a small TOML file and reads it back through read_antenna, the same path the
command will use."""

import pytest

from antenna_model.antenna_file import AntennaFileError, read_antenna

EFHW_FT = """
name = "40m EFHW"
units = "ft"
ground = "average"
bands = ["40m", "20m", "15m", "10m"]

[[wire]]
from = [0, 0, 6]
to = [66, 0, 25]
size = "14 AWG"

[feed]
wire = 1
at = 0
ratio = 49
"""

DIPOLE_M = """
name = "40m dipole"
units = "m"
ground = "free-space"
bands = ["40m"]

[[wire]]
from = [0, -10, 10]
to = [0, 10, 10]
size = "2.0 mm"

[feed]
wire = 1
at = 0.5
"""


@pytest.fixture
def antenna_file(tmp_path):
    def write(text, name="antenna.toml"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path
    return write


def test_a_file_in_feet_is_converted_to_meters(antenna_file):
    antenna = read_antenna(antenna_file(EFHW_FT))
    assert antenna.name == "40m EFHW"
    assert antenna.ground == "average"
    assert antenna.bands == ("40m", "20m", "15m", "10m")
    [wire] = antenna.wires
    assert wire.start == pytest.approx((0, 0, 1.8288))  # 6 ft = 6 x 0.3048 m exactly
    assert wire.end == pytest.approx((20.1168, 0, 7.62))
    assert wire.radius_m == pytest.approx(0.001628 / 2, rel=0.002)  # 14 AWG is 1.628 mm across
    assert (antenna.feed.wire, antenna.feed.at, antenna.feed.ratio) == (0, 0, 49)  # wire 1 -> index 0


def test_a_file_in_meters_and_mm_with_no_transformer(antenna_file):
    antenna = read_antenna(antenna_file(DIPOLE_M))
    [wire] = antenna.wires
    assert (wire.start, wire.end, wire.radius_m) == ((0, -10, 10), (0, 10, 10), 0.001)
    assert (antenna.feed.at, antenna.feed.ratio) == (0.5, 1)


def with_(text, old, new):
    """The text with one line changed: each bad-input test differs from a good file in one place."""
    assert text.count(old) == 1, old
    return text.replace(old, new)


# Published AWG diameters (mm), e.g. the NEC / ASTM B258 wire tables: an independent check of the formula.
@pytest.mark.parametrize("size, mm", [
    ("0 AWG", 8.251), ("10 AWG", 2.588), ("12 AWG", 2.053), ("14 AWG", 1.628),
    ("16 AWG", 1.291), ("18 AWG", 1.024), ("24 AWG", 0.511),
    ("14 awg", 1.628), ("  14   AWG ", 1.628), ("1.5 mm", 1.5), ("25 mm", 25.0), ("0.8 MM", 0.8),
])
def test_wire_sizes(antenna_file, size, mm):
    wire = read_antenna(antenna_file(with_(DIPOLE_M, '"2.0 mm"', f'"{size}"'))).wires[0]
    assert wire.radius_m * 2 * 1000 == pytest.approx(mm, rel=0.002)


def test_several_wires_and_the_feed_on_the_second(antenna_file):
    text = with_(DIPOLE_M, "wire = 1", "wire = 2") + '\n[[wire]]\nfrom = [0, 10, 10]\nto = [0, 20, 5]\nsize = "12 AWG"\n'
    antenna = read_antenna(antenna_file(text))
    assert len(antenna.wires) == 2 and antenna.feed.wire == 1


def test_wires_on_the_ground_are_allowed(antenna_file):
    # A ground-mounted vertical starts at height 0.
    text = with_(with_(DIPOLE_M, "[0, -10, 10]", "[0, 0, 0]"), 'ground = "free-space"', 'ground = "average"')
    assert read_antenna(antenna_file(text)).wires[0].start == (0, 0, 0)


def test_underground_is_allowed_in_free_space(antenna_file):
    # Free space has no ground, so a negative height just means "below the origin".
    assert read_antenna(antenna_file(with_(DIPOLE_M, "[0, -10, 10]", "[0, -10, -10]"))).wires[0].start[2] == -10


BAD = [
    # (what's wrong, old text, new text, words the message must contain)
    ("units missing", 'units = "m"\n', "", ["units", "required"]),
    ("units unknown", 'units = "m"', 'units = "yd"', ["units", '"ft" or "m"']),
    ("name blank", 'name = "40m dipole"', 'name = "  "', ["name"]),
    ("name too long", 'name = "40m dipole"', f'name = "{"x" * 61}"', ["name", "60"]),
    ("name not text", 'name = "40m dipole"', "name = 40", ["name", "text"]),
    # T2: the name gets printed and shown on a page; an ANSI escape could rewrite the terminal.
    ("name control code", 'name = "40m dipole"', 'name = "40m\\u001b[2J"', ["name", "control"]),
    ("name line break", 'name = "40m dipole"', 'name = "40m\\nfake line"', ["name", "control"]),
    ("name line separator", 'name = "40m dipole"', 'name = "40m\\u2028fake line"', ["name", "control"]),
    ("ground unknown", 'ground = "free-space"', 'ground = "sand"', ["ground", "average"]),
    ("bands empty", 'bands = ["40m"]', "bands = []", ["bands"]),
    ("band unknown", 'bands = ["40m"]', 'bands = ["41m"]', ["41m", "40m", "10m"]),
    ("band twice", 'bands = ["40m"]', 'bands = ["40m", "40m"]', ["40m", "twice"]),
    ("60m left out", 'bands = ["40m"]', 'bands = ["60m"]', ["60m"]),
    ("bands not a list", 'bands = ["40m"]', 'bands = "40m"', ["bands", "list"]),
    ("typo at top", 'ground = "free-space"', 'ground = "free-space"\ngrond = "average"', ["grond"]),
    ("typo in a wire", 'size = "2.0 mm"', 'size = "2.0 mm"\nsiz = "1 mm"', ["wire 1", "siz"]),
    ("typo in feed", "at = 0.5", "at = 0.5\nratoi = 4", ["feed", "ratoi"]),
    ("no wires", "[[wire]]\nfrom = [0, -10, 10]\nto = [0, 10, 10]\nsize = \"2.0 mm\"\n", "", ["wire", "required"]),
    ("point too short", "[0, -10, 10]", "[0, -10]", ["wire 1", "from", "3 numbers"]),
    ("point has text", "[0, -10, 10]", '[0, "-10", 10]', ["wire 1", "from", "3 numbers"]),
    ("point has true", "[0, -10, 10]", "[0, true, 10]", ["wire 1", "from", "3 numbers"]),
    ("point is nan", "[0, -10, 10]", "[0, nan, 10]", ["wire 1", "from", "finite"]),
    ("point is inf", "[0, 10, 10]", "[0, inf, 10]", ["wire 1", "to", "finite"]),
    ("point too far", "[0, 10, 10]", "[0, 10, 1e7]", ["wire 1", "to", "10000"]),
    ("zero length", "[0, 10, 10]", "[0, -10, 10]", ["wire 1", "length"]),
    ("size missing", 'size = "2.0 mm"\n', "", ["wire 1", "size", "required"]),
    ("size no unit", '"2.0 mm"', '"2.0"', ["wire 1", "size", "AWG", "mm"]),
    ("size bad unit", '"2.0 mm"', '"2.0 in"', ["wire 1", "size", "AWG", "mm"]),
    ("size AWG fraction", '"2.0 mm"', '"14.5 AWG"', ["wire 1", "size"]),
    ("size AWG too thin", '"2.0 mm"', '"41 AWG"', ["wire 1", "size", "0", "40"]),
    ("size AWG negative", '"2.0 mm"', '"-1 AWG"', ["wire 1", "size"]),
    ("size mm zero", '"2.0 mm"', '"0 mm"', ["wire 1", "size"]),
    ("size mm huge", '"2.0 mm"', '"51 mm"', ["wire 1", "size", "50"]),
    ("size mm nan", '"2.0 mm"', '"nan mm"', ["wire 1", "size"]),
    ("size mm word", '"2.0 mm"', '"two mm"', ["wire 1", "size"]),
    ("size not text", '"2.0 mm"', "2.0", ["wire 1", "size"]),
    ("feed missing", "[feed]\nwire = 1\nat = 0.5\n", "", ["feed", "required"]),
    ("feed wire 0", "wire = 1", "wire = 0", ["feed", "wire", "1"]),
    ("feed wire past end", "wire = 1", "wire = 2", ["feed", "wire", "1 wire"]),
    ("feed wire fraction", "wire = 1", "wire = 1.0", ["feed", "wire", "whole number"]),
    ("feed wire true", "wire = 1", "wire = true", ["feed", "wire", "whole number"]),
    ("feed at past end", "at = 0.5", "at = 1.5", ["feed", "at", "0", "1"]),
    ("feed at negative", "at = 0.5", "at = -0.1", ["feed", "at"]),
    ("feed at missing", "at = 0.5\n", "", ["feed", "at", "required"]),
    ("ratio zero", "at = 0.5", "at = 0.5\nratio = 0", ["feed", "ratio"]),
    ("ratio huge", "at = 0.5", "at = 0.5\nratio = 1000", ["feed", "ratio", "100"]),
    ("ratio text", "at = 0.5", 'at = 0.5\nratio = "49:1"', ["feed", "ratio", "number"]),
    ("wire is a table", "[[wire]]", "[wire]", ["wire", "[[wire]]"]),
]


@pytest.mark.parametrize("why, old, new, words", BAD, ids=[b[0] for b in BAD])
def test_bad_files_are_refused_with_a_message_naming_the_field(antenna_file, why, old, new, words):
    with pytest.raises(AntennaFileError) as error:
        read_antenna(antenna_file(with_(DIPOLE_M, old, new)))
    message = str(error.value)
    assert message.startswith("antenna.toml: ")
    for word in words:
        assert word in message, f"{why}: {word!r} not in {message!r}"


def test_underground_is_refused_over_real_ground(antenna_file):
    text = with_(with_(DIPOLE_M, "[0, -10, 10]", "[0, -10, -0.5]"), 'ground = "free-space"', 'ground = "perfect"')
    with pytest.raises(AntennaFileError, match="wire 1: 'from' is below ground"):
        read_antenna(antenna_file(text))


def test_too_many_wires(antenna_file):
    wire = '\n[[wire]]\nfrom = [0, 0, 1]\nto = [0, 0, 2]\nsize = "1 mm"\n'
    with pytest.raises(AntennaFileError, match="100 wires"):
        read_antenna(antenna_file(DIPOLE_M + wire * 100))  # 101 in all


def test_broken_toml_names_its_line(antenna_file):
    with pytest.raises(AntennaFileError, match=r"antenna.toml: .*line 3"):
        read_antenna(antenna_file('name = "x"\nunits = "m"\nground = \n'))


@pytest.mark.parametrize("content, words", [
    (b"\xff\xfe not text", "UTF-8"),
    (b"#" * (64 * 1024 + 1), "64 KB"),
])
def test_files_that_arent_antenna_text(tmp_path, content, words):
    path = tmp_path / "antenna.toml"
    path.write_bytes(content)
    with pytest.raises(AntennaFileError, match=words):
        read_antenna(path)


def test_a_missing_file(tmp_path):
    with pytest.raises(AntennaFileError, match="nope.toml: can't read"):
        read_antenna(tmp_path / "nope.toml")


def test_a_folder_instead_of_a_file(tmp_path):
    with pytest.raises(AntennaFileError, match="can't read"):
        read_antenna(tmp_path)
