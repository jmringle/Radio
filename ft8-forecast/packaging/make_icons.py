"""Renders packaging/icon.svg into the app icons the builds use: Skipcast.icns (macOS) and
Skipcast.ico (Windows app and installer). Run on a Mac after changing the SVG, then commit all three:
    .venv/bin/python packaging/make_icons.py
Uses Playwright's Chromium (already a test dependency) to draw the SVG, and macOS's own iconutil
for the .icns, so the builds need nothing new. The .ico holds PNG images, which Windows has read
since Vista."""

import base64
import struct
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]  # iconutil wants each at 1x and, from 32 up, as 2x
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(sizes: set[int]) -> dict[int, bytes]:
    src = "data:image/svg+xml;base64," + base64.b64encode((HERE / "icon.svg").read_bytes()).decode()
    pngs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in sorted(sizes):
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(f"<body style='margin:0'><img src='{src}' width='{size}' height='{size}'>")
            page.wait_for_function("document.images[0].complete")
            pngs[size] = page.screenshot(omit_background=True)
            page.close()
        browser.close()
    return pngs


def ico(pngs: dict[int, bytes]) -> bytes:
    """An .ico file: a header, one 16-byte entry per image (0 means 256), then the PNGs."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset, entries, data = 6 + 16 * len(pngs), b"", b""
    for size, png in pngs.items():
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    return header + entries + data


def main():
    pngs = render(set(ICNS_SIZES) | set(ICO_SIZES))
    (HERE / "Skipcast.ico").write_bytes(ico({s: pngs[s] for s in ICO_SIZES}))
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Skipcast.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES[:-1]:
            (iconset / f"icon_{size}x{size}.png").write_bytes(pngs[size])
            (iconset / f"icon_{size}x{size}@2x.png").write_bytes(pngs[size * 2])
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "Skipcast.icns")], check=True)


if __name__ == "__main__":
    main()
