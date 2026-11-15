"""Building the text commands the NanoVNA's shell accepts (firmware 1.2.x, DiSlord-based).

Only commands that read or sweep are allowed (T1): dipstick must never erase or overwrite
your saved calibration (save, saveconfig, clearconfig), change the output level (power) or
restart the device (reset). The one exception is calibrating, which you start in the app: `cal`
with only the steps below. They change the calibration in the NanoVNA's memory, never in its
flash; switching it off and on loads the saved one again (hugen79/NanoVNA-H main.c: cmd_cal,
cal_collect and cal_done never call caldata_save, which only `save N` does; read 2026-11-15).
Arguments are whole numbers only (T2), apart from those fixed step names: a carriage return
inside an argument would end the command early and run whatever followed as a second command.
"""

ALLOWED = {
    "version",  # firmware version
    "info",  # board and build
    "sweep",  # with no arguments: the current start, stop and points (to put them back after a scan)
    "scan",  # scan START STOP POINTS OUTMASK: sweep once and send the results
    "frequencies",  # the frequencies of the last sweep
    "data",  # data 0: S11 of the last sweep
}
# cal STEP: forget the calibration in memory, measure one standard, or work out and apply the new one.
CAL_STEPS = ("reset", "open", "short", "load", "done")


def command(name: str, *args: int | str) -> bytes:
    if name == "cal":
        if len(args) != 1 or args[0] not in CAL_STEPS:
            raise ValueError(f"cal takes one of {', '.join(CAL_STEPS)}, got {args!r}")
        return f"cal {args[0]}".encode("ascii") + b"\r"
    if name not in ALLOWED:
        raise ValueError(f"NanoVNA command {name!r} is not allowed (allowed: {', '.join(sorted(ALLOWED | {'cal'}))})")
    for arg in args:
        if not isinstance(arg, int) or isinstance(arg, bool) or arg < 0:
            raise ValueError(f"NanoVNA command arguments must be whole numbers 0 or above, got {arg!r}")
    return " ".join([name, *map(str, args)]).encode("ascii") + b"\r"
