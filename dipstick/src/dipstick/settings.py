"""The app's saved choices: whether to show the "Check yourself" questions, and the USB IDs of
serial adapters the person said are their NanoVNA (a clone with a generic chip, such as a CH340).

Kept in settings.json in the folder each system uses for app settings. The file is input like any
other (anyone with the account can edit it, and a crash can leave half of it), so anything odd in
it means the default, never an error.
"""

import json
import os
import re
import sys
from pathlib import Path

DEFAULTS = {"quiz": True, "ports": []}
MAX_PORTS = 8  # remembered USB IDs; ours is one or two
USB_ID_TEXT = re.compile(r"[0-9A-F]{4}:[0-9A-F]{4}")  # vendor:product, as 1A86:7523
MAX_BYTES = 4096  # ours is about 15 bytes; a bigger file isn't ours


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
    ports = saved.get("ports") if isinstance(saved, dict) else None
    if isinstance(ports, list):  # anything that isn't a plain vendor:product ID is dropped
        settings["ports"] = [i for i in dict.fromkeys(ports) if isinstance(i, str) and USB_ID_TEXT.fullmatch(i)][:MAX_PORTS]
    return settings


def save(path: Path, settings: dict) -> None:
    """Writes beside the file, then swaps it in, so a crash midway leaves the old file whole. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(settings))
    os.replace(temporary, path)
