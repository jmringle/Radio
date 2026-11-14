# PyInstaller build. Run from this folder's parent: pyinstaller --noconfirm packaging/ft8forecast.spec
# A folder, not one file: it starts faster, and one-file builds trip more antivirus tools.
import os
import sys

# SPECPATH (this folder), so it works from any folder and without ft8_forecast installed, as in CI.
src = os.path.join(SPECPATH, "..", "src")
source = os.path.join(src, "ft8_forecast")
analysis = Analysis(
    ["app_entry.py"],
    pathex=[src],
    # Named one by one, so nothing else in the project (data/, .env) can come along.
    datas=[(f"{source}/templates/page.html", "ft8_forecast/templates"),
           (f"{source}/templates/land.svg", "ft8_forecast/templates"),
           (f"{source}/static/style.css", "ft8_forecast/static"),
           (f"{source}/static/busy.js", "ft8_forecast/static")],
    hiddenimports=["ft8_forecast.desktop"],
    excludes=["pytest", "playwright", "pip_audit", "PyInstaller"],
)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="FT8 Forecast", console=False)
collected = COLLECT(executable, analysis.binaries, analysis.datas, name="FT8 Forecast")
if sys.platform == "darwin":
    app = BUNDLE(collected, name="FT8 Forecast.app", bundle_identifier="io.github.jmringle.ft8forecast",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "NSHighResolutionCapable": True})
