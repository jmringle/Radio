"""SVG plots of a sweep: SWR across the band, and the Smith chart.

Drawn by hand (no plotting library), so the command's saved files and the app's window show
the same drawings. Saved files carry their own colors (standalone=True); the app asks for
standalone=False and colors them from its stylesheet by class, since its Content Security
Policy blocks inline styles (and that lets the plots follow dark mode).
"""

import math
from xml.sax.saxutils import escape

from dipstick.analysis import THREE_TO_ONE, TWO_TO_ONE, spans
from dipstick.bands import BANDS
from dipstick.s11 import Reading

# SWR plot: plot area in SVG units. SWR runs 1 to 10 on a log scale: the part that matters
# (1 to 3) gets most of the height, and anything worse sits at the top.
W, H = 640, 320
LEFT, TOP, RIGHT, BOTTOM = 56, 28, 620, 280
SWR_TOP = 10.0
SWR_TICKS = (1, 1.5, 2, 3, 5, 10)

# Smith chart, with a key underneath: short lines, so they fit the chart's width.
SIZE = 340
KEY = 62
CX = CY = SIZE / 2
R = 150

STYLE = """
  text { font: 12px -apple-system, "Segoe UI", sans-serif; fill: #333; }
  .plot-area { fill: #fff; stroke: #bbb; }
  .grid { stroke: #e3e3e3; }
  .two-to-one, .swr-2 { stroke: #2e7d32; stroke-dasharray: 5 4; fill: none; }
  .swr, .trace { fill: none; stroke: #1f4fa3; stroke-width: 2; }
  .best { fill: #c62828; }
  .edge, .r-50, .axis { fill: none; stroke: #999; }
  .note { fill: #2e7d32; }
  .target { stroke: #666; stroke-dasharray: 2 3; }
  .target-label { fill: #666; }
  .ham-band { fill: #2e7d32; fill-opacity: 0.12; }
  .under-2 { fill: #2e7d32; fill-opacity: 0.14; }
  .under-3 { fill: #b26a00; fill-opacity: 0.12; }
  .three-to-one { stroke: #b26a00; stroke-dasharray: 5 4; fill: none; }
  .note-3 { fill: #b26a00; }
"""


def swr_svg(readings: list[Reading], band: str, standalone: bool = True, target_hz: int | None = None,
            ham_bands: bool = False) -> str:
    """`target_hz`: the frequency the person wants (already checked to be in the band), marked with a line.
    `ham_bands`: a sweep across several bands (`band` names what was measured), with the bands shaded.
    Otherwise it's one band's antenna, shaded where SWR is 3 or under (most built-in tuners) and 2 or
    under (no tuner), with a 3:1 line beside the 2:1 one."""
    _need_two(readings)
    start, stop = readings[0].hz, readings[-1].hz

    def x(hz: float) -> float:
        return LEFT + (hz - start) / (stop - start) * (RIGHT - LEFT)

    pts = [(x(r.hz), _swr_y(r.swr)) for r in readings]
    best = min(range(len(readings)), key=lambda i: readings[i].swr)
    parts = [f'<rect class="plot-area" x="{LEFT}" y="{TOP}" width="{RIGHT - LEFT}" height="{BOTTOM - TOP}"/>']
    if ham_bands:
        for low, high in BANDS.values():
            if start <= low and high <= stop:  # at least 1 unit wide, so 30 m's 50 kHz still shows
                parts.append(f'<rect class="ham-band" x="{x(low):.2f}" y="{TOP}" '
                             f'width="{max(1.0, x(high) - x(low)):.2f}" height="{BOTTOM - TOP}"/>')
    else:
        for limit, cls in ((THREE_TO_ONE, "under-3"), (TWO_TO_ONE, "under-2")):  # 2:1 drawn over 3:1
            for low, high in spans(readings, limit):
                parts.append(f'<rect class="{cls}" x="{x(low):.2f}" y="{TOP}" '
                             f'width="{max(1.0, x(high) - x(low)):.2f}" height="{BOTTOM - TOP}"/>')
    for swr in SWR_TICKS:
        y = _swr_y(swr)
        parts.append(f'<line class="grid" x1="{LEFT}" y1="{y:.2f}" x2="{RIGHT}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{y + 4:.2f}" text-anchor="end">{swr:g}</text>')
    y2 = _swr_y(2)
    parts.append(f'<line class="two-to-one" x1="{LEFT}" y1="{y2:.2f}" x2="{RIGHT}" y2="{y2:.2f}"/>')
    parts.append(f'<text class="note" x="{RIGHT - 4}" y="{y2 - 5:.2f}" text-anchor="end">2:1</text>')
    if not ham_bands:
        y3 = _swr_y(THREE_TO_ONE)
        parts.append(f'<line class="three-to-one" x1="{LEFT}" y1="{y3:.2f}" x2="{RIGHT}" y2="{y3:.2f}"/>')
        parts.append(f'<text class="note-3" x="{RIGHT - 4}" y="{y3 - 5:.2f}" text-anchor="end">3:1</text>')
    for hz, anchor in ((start, "start"), ((start + stop) / 2, "middle"), (stop, "end")):  # edge labels stay inside
        parts.append(f'<text x="{x(hz):.2f}" y="{BOTTOM + 18}" text-anchor="{anchor}">{hz / 1e6:.3f}</text>')
    if target_hz is not None:
        tx = x(target_hz)
        parts.append(f'<line class="target" x1="{tx:.2f}" y1="{TOP}" x2="{tx:.2f}" y2="{BOTTOM}"/>')
        # The label goes on whichever side of the line has more room.
        side, anchor = (tx + 4, "start") if tx < (LEFT + RIGHT) / 2 else (tx - 4, "end")
        parts.append(f'<text class="target-label" x="{side:.2f}" y="{TOP + 14}" text-anchor="{anchor}">'
                     f'target {target_hz / 1e6:.3f}</text>')
    parts.append(_polyline("swr", pts))
    bx, by = pts[best]
    parts.append(f'<circle class="best" cx="{bx:.2f}" cy="{by:.2f}" r="4"/>')
    what = "SWR (MHz), ham bands shaded" if ham_bands else "SWR across the band (MHz)"
    parts.append(f'<text x="{LEFT}" y="{TOP - 10}">{escape(band)}: {what}</text>')
    return _svg(W, H, parts, standalone)


ANTENNA_KEY = ("Center: a perfect match. Red dot: best match.",
               "Inside the dashed circle: SWR under 2.",
               "Solid circle through the center: R = 50 ohms.")
# A cable with an open or shorted end: its echo's phase turns a full lap for every extra half
# wavelength of cable, and loss pulls the trace in from the edge as the frequency rises.
CABLE_KEY = ("Center: a perfect match. Edge: all comes back.",
             "An open or shorted cable laps near the edge,",
             "a lap per half wave; loss pulls it inward.")


def smith_svg(readings: list[Reading], standalone: bool = True, cable: bool = False) -> str:
    """`cable`: a cable's trace, with no best-match dot and a key about its laps."""
    _need_two(readings)
    pts = [_smith_xy(r.s11) for r in readings]
    best = min(range(len(readings)), key=lambda i: readings[i].swr)
    bx, by = pts[best]
    parts = [
        f'<circle class="edge" cx="{CX}" cy="{CY}" r="{R}"/>',  # |S11| = 1: everything comes back
        f'<circle class="r-50" cx="{CX + R / 2}" cy="{CY}" r="{R / 2}"/>',  # every impedance with R = 50 ohms
        f'<line class="axis" x1="{CX - R}" y1="{CY}" x2="{CX + R}" y2="{CY}"/>',  # pure resistance, X = 0
        f'<circle class="swr-2" cx="{CX}" cy="{CY}" r="{R / 3:.4f}"/>',  # inside: SWR under 2
        _polyline("trace", pts),
        *([] if cable else [f'<circle class="best" cx="{bx:.4f}" cy="{by:.4f}" r="4"/>']),
        f'<text x="{CX - R}" y="{CY - 6}" text-anchor="start">short</text>',
        f'<text x="{CX + R}" y="{CY - 6}" text-anchor="end">open</text>',
        f'<text x="{CX}" y="{CY - R - 8}" text-anchor="middle">+jX (inductive)</text>',
        f'<text x="{CX}" y="{CY + R + 18}" text-anchor="middle">-jX (capacitive)</text>',
        *(f'<text x="10" y="{SIZE + 16 + 18 * i}">{line}</text>'
          for i, line in enumerate(CABLE_KEY if cable else ANTENNA_KEY)),
    ]
    return _svg(SIZE, SIZE + KEY, parts, standalone)


def _swr_y(swr: float) -> float:
    capped = min(swr, SWR_TOP)  # infinite and off-scale SWR sit at the top
    return BOTTOM - math.log10(capped) / math.log10(SWR_TOP) * (BOTTOM - TOP)


def _smith_xy(s11: complex) -> tuple[float, float]:
    """The Smith chart is S11 itself: right is +real, up is +imaginary (SVG y grows down)."""
    size = abs(s11)
    if size > 1:  # measurement noise just past the edge: draw it on the edge
        s11 /= size
    return CX + R * s11.real, CY - R * s11.imag


def _polyline(cls: str, pts: list[tuple[float, float]]) -> str:
    return f'<polyline class="{cls}" points="{" ".join(f"{x:.4f},{y:.4f}" for x, y in pts)}"/>'


def _svg(width: int, height: int, parts: list[str], standalone: bool) -> str:
    body = "\n  ".join(parts)
    own_colors = f'  <style>{STYLE}</style>\n  <rect width="100%" height="100%" fill="#fff"/>\n' if standalone else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">\n'
            f'{own_colors}  {body}\n</svg>\n')


def _need_two(readings: list[Reading]) -> None:
    if len(readings) < 2:
        raise ValueError("A plot needs at least 2 readings")
