"""Building the text commands the NanoVNA's shell accepts (firmware 1.2.x, DiSlord-based).

Only commands that read or sweep are allowed (T1): dipstick must never erase or overwrite
your calibration (cal, saveconfig, clearconfig), change the output level (power) or restart
the device (reset). Arguments are whole numbers only (T2): a carriage return inside an
argument would end the command early and run whatever followed as a second command.
"""

ALLOWED = {
    "version",  # firmware version
    "info",  # board and build
    "sweep",  # with no arguments: the current start, stop and points (to put them back after a scan)
    "scan",  # scan START STOP POINTS OUTMASK: sweep once and send the results
    "frequencies",  # the frequencies of the last sweep
    "data",  # data 0: S11 of the last sweep
}


def command(name: str, *args: int) -> bytes:
    if name not in ALLOWED:
        raise ValueError(f"NanoVNA command {name!r} is not allowed (allowed: {', '.join(sorted(ALLOWED))})")
    for arg in args:
        if not isinstance(arg, int) or isinstance(arg, bool) or arg < 0:
            raise ValueError(f"NanoVNA command arguments must be whole numbers 0 or above, got {arg!r}")
    return " ".join([name, *map(str, args)]).encode("ascii") + b"\r"
