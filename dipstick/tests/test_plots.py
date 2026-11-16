"""The SVG plots: points land where known answers say they must.

Tests read positions back out of the SVG (parsed as XML), so they check the drawing itself,
not just that some SVG came out."""

import math
import xml.etree.ElementTree as ET

import pytest
from test_analysis import antenna

from dipstick.plots import smith_svg, swr_svg
from dipstick.s11 import reading

SVG = "{http://www.w3.org/2000/svg}"


def parse(svg):
    return ET.fromstring(svg)


def find(root, tag, cls):
    found = [e for e in root.iter(SVG + tag) if cls in e.get("class", "").split()]
    assert found, f"no <{tag} class={cls}>"
    return found


def points(element):
    return [tuple(map(float, p.split(","))) for p in element.get("points").split()]


# --- SWR across the band ----------------------------------------------------------------------

def swr_plot(readings, band="40m"):
    return parse(swr_svg(readings, band))


def test_swr_plot_has_one_point_per_reading_from_edge_to_edge():
    root = swr_plot(antenna(7_150_000, 60_000))
    [trace] = find(root, "polyline", "swr")
    pts = points(trace)
    [axis] = find(root, "rect", "plot-area")
    left, width = float(axis.get("x")), float(axis.get("width"))
    assert len(pts) == 101
    assert pts[0][0] == pytest.approx(left) and pts[-1][0] == pytest.approx(left + width)


def test_swr_1_sits_on_the_bottom_and_swr_2_on_the_2_to_1_line():
    readings = antenna(7_150_000, 60_000)
    root = swr_plot(readings)
    pts = points(find(root, "polyline", "swr")[0])
    [area] = find(root, "rect", "plot-area")
    bottom = float(area.get("y")) + float(area.get("height"))
    [line] = find(root, "line", "two-to-one")
    best = min(range(len(readings)), key=lambda i: readings[i].swr)
    assert pts[best][1] == pytest.approx(bottom)  # SWR 1.00 at 7.150
    # SWR is exactly 2 at 7.090 MHz (reading 30: 7.000 + 30 x 3 kHz) for this antenna.
    assert readings[30].swr == pytest.approx(2.0, abs=0.001)
    assert pts[30][1] == pytest.approx(float(line.get("y1")), abs=0.1)


def test_higher_swr_is_higher_on_the_plot():
    readings = antenna(7_150_000, 60_000)
    pts = points(find(swr_plot(readings), "polyline", "swr")[0])
    assert pts[0][1] < pts[30][1] < pts[50][1]  # SVG y grows downward: SWR 4.9 above 2.0 above 1.0


def test_off_the_scale_and_infinite_swr_stay_inside_the_plot():
    readings = [reading(7_000_000 + i * 30_000, complex(s, 0)) for i, s in enumerate([0.99, 1.0, 0.0])]
    root = swr_plot(readings)
    [area] = find(root, "rect", "plot-area")
    top = float(area.get("y"))
    pts = points(find(root, "polyline", "swr")[0])
    assert pts[0][1] == pytest.approx(top) and pts[1][1] == pytest.approx(top)


def test_the_best_match_is_marked():
    readings = antenna(7_153_000, 60_000)
    root = swr_plot(readings)
    [best] = find(root, "circle", "best")
    pts = points(find(root, "polyline", "swr")[0])
    assert (float(best.get("cx")), float(best.get("cy"))) == pytest.approx(pts[51])  # 7.153 MHz


def test_the_target_is_marked_with_a_line_and_its_frequency():
    # So the gap between the dip and where you want it shows at a glance (UI review 2026-11-16).
    root = parse(swr_svg(antenna(7_150_000, 60_000), "40m", target_hz=7_074_000))
    [area] = find(root, "rect", "plot-area")
    left, top, width, height = (float(area.get(k)) for k in ("x", "y", "width", "height"))
    [line] = find(root, "line", "target")
    x = left + 74_000 / 300_000 * width  # 7.074 is 74 kHz into the 300 kHz band
    assert (float(line.get("x1")), float(line.get("x2"))) == pytest.approx((x, x))
    assert (float(line.get("y1")), float(line.get("y2"))) == pytest.approx((top, top + height))
    assert "target 7.074" in [t.text for t in root.iter(SVG + "text")]


def test_no_target_no_line():
    root = swr_plot(antenna(7_150_000, 60_000))
    assert not [e for e in root.iter(SVG + "line") if "target" in e.get("class", "")]


def test_axis_labels():
    root = swr_plot(antenna(7_150_000, 60_000))
    labels = [t.text for t in root.iter(SVG + "text")]
    assert {"7.000", "7.150", "7.300", "1", "2", "3", "10"} <= set(labels)
    assert any("40m" in label for label in labels)


# --- Smith chart ------------------------------------------------------------------------------

def smith(readings):
    root = parse(smith_svg(readings))
    [edge] = find(root, "circle", "edge")
    cx, cy, r = (float(edge.get(k)) for k in ("cx", "cy", "r"))
    return root, cx, cy, r


def test_smith_known_points():
    # S11 = 0: the center (perfect match). S11 = 1: right edge (open). -1: left edge (short).
    # +j: top (pure inductance). The trace draws exactly these, in order.
    readings = [reading(1_000_000 + i, s) for i, s in enumerate([0, 1, -1, 1j, -1j])]
    root, cx, cy, r = smith(readings)
    pts = points(find(root, "polyline", "trace")[0])
    expected = [(cx, cy), (cx + r, cy), (cx - r, cy), (cx, cy - r), (cx, cy + r)]
    assert [c for p in pts for c in p] == pytest.approx([c for p in expected for c in p])


def test_smith_trace_stays_inside_the_edge():
    root, cx, cy, r = smith(antenna(7_150_000, 60_000) + [reading(7_400_000, complex(1.03, 0))])  # noise over 1
    for x, y in points(find(root, "polyline", "trace")[0]):
        assert math.hypot(x - cx, y - cy) <= r + 1e-6


def test_smith_swr_2_circle():
    # Inside this circle SWR is under 2: |S11| < 1/3.
    root, cx, cy, r = smith(antenna(7_150_000, 60_000))
    [circle] = find(root, "circle", "swr-2")
    assert (float(circle.get("cx")), float(circle.get("cy")), float(circle.get("r"))) == pytest.approx((cx, cy, r / 3))


def test_smith_50_ohm_resistance_circle_passes_through_the_center():
    # Every impedance with R = 50 ohms lies on this circle, which touches the center and the right edge.
    root, cx, cy, r = smith(antenna(7_150_000, 60_000))
    [circle] = find(root, "circle", "r-50")
    assert (float(circle.get("cx")), float(circle.get("cy")), float(circle.get("r"))) == pytest.approx((cx + r / 2, cy, r / 2))


def test_smith_best_match_marked():
    readings = antenna(7_153_000, 60_000)
    root, cx, cy, r = smith(readings)
    [best] = find(root, "circle", "best")
    s = readings[51].s11
    assert (float(best.get("cx")), float(best.get("cy"))) == pytest.approx((cx + r * s.real, cy - r * s.imag))


def test_smith_key_lines_fit_inside_the_chart():
    # The key was cut off at the right edge in the app (seen 2026-11-16). 12px system text runs
    # about 5.8 SVG units a character (measured on that screenshot); 7 leaves room for wider fonts.
    root = parse(smith_svg(antenna(7_150_000, 60_000)))
    width = float(root.get("viewBox").split()[2])
    key = [t for t in root.iter(SVG + "text") if t.get("text-anchor") is None]
    assert len(key) >= 2
    for line in key:
        assert float(line.get("x")) + 7 * len(line.text) <= width, line.text


def test_smith_key_lines_sit_inside_the_chart_height():
    root = parse(smith_svg(antenna(7_150_000, 60_000)))
    height = float(root.get("viewBox").split()[3])
    assert all(float(t.get("y")) <= height - 4 for t in root.iter(SVG + "text"))


@pytest.mark.parametrize("make", [swr_svg, smith_svg])
def test_needs_two_readings(make):
    with pytest.raises(ValueError):
        make([reading(7_000_000, 0)], "40m") if make is swr_svg else make([reading(7_000_000, 0)])


def test_the_swr_scale_is_logarithmic_from_1_to_10():
    # On a log scale from 1 to 10, SWR 2 is log10(2) = 30.1% of the way up; on a straight
    # scale it would be only 11%. This gives 1-3, where antennas live, most of the height.
    root = swr_plot(antenna(7_150_000, 60_000))
    [area] = find(root, "rect", "plot-area")
    top, height = float(area.get("y")), float(area.get("height"))
    [line] = find(root, "line", "two-to-one")
    assert (top + height - float(line.get("y1"))) / height == pytest.approx(math.log10(2), abs=0.001)


@pytest.mark.parametrize("make", [lambda r: swr_svg(r, "40m", standalone=False), lambda r: smith_svg(r, standalone=False)])
def test_app_versions_have_no_inline_styles(make):
    # The app's Content Security Policy blocks inline styles: no <style>, no style="" attributes.
    root = parse(make(antenna(7_150_000, 60_000)))
    assert list(root.iter(SVG + "style")) == []
    assert all("style" not in e.attrib for e in root.iter())
