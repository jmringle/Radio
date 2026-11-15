"""SVG plots of a sweep: SWR across the band, and the Smith chart.

Drawn by hand (no plotting library), so the command's saved files and the future app's
window show the same drawings. Colors are fixed for saved files; elements carry classes so
the app can restyle them.
"""

import math
from xml.sax.saxutils import escape

from dipstick.s11 import Reading

# SWR plot: plot area in SVG units. SWR runs 1 to 10 on a log scale: the part that matters
# (1 to 3) gets most of the height, and anything worse sits at the top.
W, H = 640, 320
LEFT, TOP, RIGHT, BOTTOM = 56, 28, 620, 280
SWR_TOP = 10.0
SWR_TICKS = (1, 1.5, 2, 3, 5, 10)

# Smith chart, with a two-line key underneath.
SIZE = 340
KEY = 44
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
"""


def swr_svg(readings: list[Reading], band: str) -> str:
    _need_two(readings)
    start, stop = readings[0].hz, readings[-1].hz

    def x(hz: float) -> float:
        return LEFT + (hz - start) / (stop - start) * (RIGHT - LEFT)

    pts = [(x(r.hz), _swr_y(r.swr)) for r in readings]
    best = min(range(len(readings)), key=lambda i: readings[i].swr)
    parts = [f'<rect class="plot-area" x="{LEFT}" y="{TOP}" width="{RIGHT - LEFT}" height="{BOTTOM - TOP}"/>']
    for swr in SWR_TICKS:
        y = _swr_y(swr)
        parts.append(f'<line class="grid" x1="{LEFT}" y1="{y:.2f}" x2="{RIGHT}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{y + 4:.2f}" text-anchor="end">{swr:g}</text>')
    y2 = _swr_y(2)
    parts.append(f'<line class="two-to-one" x1="{LEFT}" y1="{y2:.2f}" x2="{RIGHT}" y2="{y2:.2f}"/>')
    parts.append(f'<text class="note" x="{RIGHT - 4}" y="{y2 - 5:.2f}" text-anchor="end">2:1</text>')
    for hz, anchor in ((start, "start"), ((start + stop) / 2, "middle"), (stop, "end")):  # edge labels stay inside
        parts.append(f'<text x="{x(hz):.2f}" y="{BOTTOM + 18}" text-anchor="{anchor}">{hz / 1e6:.3f}</text>')
    parts.append(_polyline("swr", pts))
    bx, by = pts[best]
    parts.append(f'<circle class="best" cx="{bx:.2f}" cy="{by:.2f}" r="4"/>')
    parts.append(f'<text x="{LEFT}" y="{TOP - 10}">{escape(band)}: SWR across the band (MHz)</text>')
    return _svg(W, H, parts)


def smith_svg(readings: list[Reading]) -> str:
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
        f'<circle class="best" cx="{bx:.4f}" cy="{by:.4f}" r="4"/>',
        f'<text x="{CX - R}" y="{CY - 6}" text-anchor="start">short</text>',
        f'<text x="{CX + R}" y="{CY - 6}" text-anchor="end">open</text>',
        f'<text x="{CX}" y="{CY - R - 8}" text-anchor="middle">+jX (inductive)</text>',
        f'<text x="{CX}" y="{CY + R + 18}" text-anchor="middle">-jX (capacitive)</text>',
        f'<text x="10" y="{SIZE + 16}">Center: a perfect match. Inside the dashed circle: SWR under 2.</text>',
        f'<text x="10" y="{SIZE + 34}">Solid circle through the center: R = 50 ohms. Red dot: best match.</text>',
    ]
    return _svg(SIZE, SIZE + KEY, parts)


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


def _svg(width: int, height: int, parts: list[str]) -> str:
    body = "\n  ".join(parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">\n'
            f'  <style>{STYLE}</style>\n  <rect width="100%" height="100%" fill="#fff"/>\n  {body}\n</svg>\n')


def _need_two(readings: list[Reading]) -> None:
    if len(readings) < 2:
        raise ValueError("A plot needs at least 2 readings")
