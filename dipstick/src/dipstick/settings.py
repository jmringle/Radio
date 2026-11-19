"""The app's saved choices: whether to show the "Check yourself" questions, whether a band report's
More detail is open, and the USB IDs of serial adapters the person said are their NanoVNA (a clone
with a generic chip, such as a CH340).

Kept in settings.json in the folder each system uses for app settings. The file is input like any
other (anyone with the account can edit it, and a crash can leave half of it), so anything odd in
it means the default, never an error.
"""

import json
import os
import re
import sys
from pathlib import Path

DEFAULTS = {"quiz": True, "detail": False, "ports": []}
MAX_PORTS = 8  # remembered USB IDs; ours is one or two
GENERIC_ST_ID = "0483:5740"  # the NanoVNA's USB ID, which is ST's generic one (tinySAs and more use it)
MAX_NAME = 64
# vendor:product, as 1A86:7523; or the generic ST ID followed by the device's name, as
# "0483:5740 ChibiOS/RT Virtual COM Port" (printable ASCII, no space at either end). A plain
# 0483:5740 isn't accepted: it would approve every STM32 gadget (T3).
_ID_ONLY = re.compile(r"[0-9A-F]{4}:[0-9A-F]{4}")
_ST_WITH_NAME = re.compile(GENERIC_ST_ID + r" [!-~](?:[ -~]{0,%d}[!-~])?" % (MAX_NAME - 2))
MAX_BYTES = 4096  # ours is a few dozen bytes; a bigger file isn't ours


def valid_approval(text) -> bool:
    """Whether `text` is a USB ID the app may remember (see the patterns above)."""
    if not isinstance(text, str):
        return False
    if _ID_ONLY.fullmatch(text):
        return text != GENERIC_ST_ID
    return bool(_ST_WITH_NAME.fullmatch(text))


def settings_file(platform=sys.platform, env=os.environ, home=Path.home) -> Path:
    if platform == "darwin":
        base = home() / "Library" / "Application Support"
    elif platform == "win32":
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home() / "AppData" / "Roaming"
    else:  # Linux and the like: the XDG spec, which says to ignore a relative XDG_CONFIG_HOME
        xdg = env.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg.startswith("/") else home() / ".config"
    return base / "dipstick" / "settings.json"


def load(path: Path | None) -> dict:
    """The saved choices, or the defaults for anything missing or odd. None: no file (the defaults)."""
    settings = {**DEFAULTS, "ports": []}
    if path is None:
        return settings
    try:
        if path.stat().st_size > MAX_BYTES:
            return settings
        saved = json.loads(path.read_bytes())
    except (OSError, ValueError):  # missing, unreadable, a folder, not JSON, not UTF-8
        return settings
    if isinstance(saved, dict) and isinstance(saved.get("quiz"), bool):
        settings["quiz"] = saved["quiz"]
    if isinstance(saved, dict) and isinstance(saved.get("detail"), bool):
        settings["detail"] = saved["detail"]
    ports = saved.get("ports") if isinstance(saved, dict) else None
    if isinstance(ports, list):  # anything that isn't a USB ID we'd have saved is dropped
        settings["ports"] = [i for i in dict.fromkeys(p for p in ports if isinstance(p, str)) if valid_approval(i)][:MAX_PORTS]
    return settings


def save(path: Path, settings: dict) -> None:
    """Writes beside the file, then swaps it in, so a crash midway leaves the old file whole. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(settings))
    os.replace(temporary, path)
