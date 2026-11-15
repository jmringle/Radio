# PyInstaller build. Run from this folder's parent: pyinstaller --noconfirm packaging/dipstick.spec
# A folder, not one file: it starts faster, and one-file builds trip more antivirus tools.
import os
import sys

# SPECPATH (this folder), so it works from any folder and without dipstick installed, as in CI.
src = os.path.join(SPECPATH, "..", "src")
ui = os.path.join(src, "dipstick", "ui")
analysis = Analysis(
    ["app_entry.py"],
    pathex=[src],
    # Named one by one, so nothing else in the project (output/ with your sweeps) can come along.
    datas=[(f"{ui}/index.html", "dipstick/ui"), (f"{ui}/app.css", "dipstick/ui"), (f"{ui}/app.js", "dipstick/ui")],
    excludes=["pytest", "playwright", "pip_audit", "PyInstaller"],
)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="dipstick", console=False)
collected = COLLECT(executable, analysis.binaries, analysis.datas, name="dipstick")
if sys.platform == "darwin":
    app = BUNDLE(collected, name="dipstick.app", bundle_identifier="io.github.jmringle.dipstick",
                 info_plist={"CFBundleShortVersionString": "0.1.0", "NSHighResolutionCapable": True})
