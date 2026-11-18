"""Talking to a NanoVNA over USB.

The NanoVNA's USB port is a serial port with a text shell. Every exchange looks like this
(recorded from a NanoVNA-H, firmware 1.2.43):

    you send:   version\\r
    it replies: version\\r\\n        <- your command, echoed
                1.2.43\\r\\n         <- the answer, one or more lines
                ch>                  <- the prompt: ready for the next command

A command it doesn't know gets "name?" as its answer.
"""

import errno
import math
import sys
import time

import serial

from dipstick.commands import command

PROMPT = b"ch> "
# STMicroelectronics' generic USB serial ID: the NanoVNA uses it, and so can any other STM32
# gadget, so the name must say NanoVNA too (T3).
USB_ID = (0x0483, 0x5740)
# The power switch cuts the NanoVNA-H off USB too (hand test 2026-11-16): the same error either way.
_DISCONNECTED = "The NanoVNA disconnected (unplugged or switched off). Reconnect it, switch it on, and try again."


class DeviceError(Exception):
    """Something went wrong talking to the NanoVNA; the message says what to do."""


def windows_usb_name(port) -> str:
    """The name a USB device gives itself, as Windows keeps it, or "" if there isn't one.

    Windows names the NanoVNA's port "USB Serial Device (COM6)" (its own usbser driver, maker
    "Microsoft"), and pyserial 3.5 leaves `product` empty there, so the name check never matched
    and Windows found no NanoVNA (hand test 2026-11-17, NanoVNA-H on COM6). The NanoVNA's own name,
    "NanoVNA-H", is in the device's bus-reported description: read it with cfgmgr32, by the
    instance ID Windows gives a USB device with a serial number (USB\\VID_0483&PID_5740\\400)."""
    if sys.platform != "win32" or not getattr(port, "serial_number", None) or port.vid is None:
        return ""
    import ctypes
    import uuid
    from ctypes import wintypes

    class DEVPROPKEY(ctypes.Structure):
        _fields_ = [("fmtid", ctypes.c_byte * 16), ("pid", wintypes.ULONG)]

    # DEVPKEY_Device_BusReportedDeviceDesc
    key = DEVPROPKEY((ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("540b947e-8b40-45bc-a8a2-6a0b894cbda2").bytes_le), 4)
    instance = f"USB\\VID_{port.vid:04X}&PID_{port.pid:04X}\\{port.serial_number}"
    try:
        cfgmgr32 = ctypes.WinDLL("cfgmgr32")
        node = wintypes.DWORD()
        if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node), ctypes.c_wchar_p(instance), 0) != 0:
            return ""
        kind, buffer = wintypes.ULONG(), ctypes.create_unicode_buffer(256)
        size = wintypes.ULONG(ctypes.sizeof(buffer))
        if cfgmgr32.CM_Get_DevNode_PropertyW(node, ctypes.byref(key), ctypes.byref(kind), buffer,
                                             ctypes.byref(size), 0) != 0:
            return ""
        return buffer.value
    except OSError:
        return ""


def device_name(port, usb_name=windows_usb_name) -> str:
    """What the USB device calls itself: on Windows only the bus-reported name, elsewhere pyserial's
    product, else its description; "" if none. On Windows the port's own label ("USB Serial Device
    (COM5)") never stands in: an approval saved with it would match any gadget that later lands on
    COM5 with the same USB ID (T3; code review 2026-11-18)."""
    candidates = (usb_name(port),) if sys.platform == "win32" else (usb_name(port), port.product, port.description)
    for text in candidates:
        if text and text.strip() not in ("", "n/a"):
            return text.strip()
    return ""


def nanovna_ports(ports, approved=(), usb_name=windows_usb_name) -> list[str]:
    """The ports in pyserial's list_ports.comports() that are NanoVNAs: the USB ID and the name, or
    a USB ID the person approved. Clones often use a generic chip, such as the CH340, whose ID says
    nothing about a NanoVNA; only the person can say that one is theirs (T3), and it's their say-so
    that counts, not the name. `approved`: (vendor, product) pairs, or (vendor, product, name) for
    the NanoVNA's own ID, which is ST's generic one: approving it alone would also approve a tinySA
    or any other STM32 gadget, so a plain (0483, 5740) approves nothing. `usb_name`: where else to
    look for the name (Windows keeps it apart from the port's; see windows_usb_name)."""
    def named_nanovna(p) -> bool:
        if "nanovna" in f"{p.product or ''} {p.description or ''}".lower():
            return True
        return "nanovna" in usb_name(p).lower()

    def is_approved(p) -> bool:
        for entry in approved:
            if p.vid is None or tuple(entry[:2]) != (p.vid, p.pid):
                continue
            if len(entry) == 3 and entry[2] == device_name(p, usb_name):
                return True
            if len(entry) == 2 and (p.vid, p.pid) != USB_ID:
                return True
        return False
    return [p.device for p in ports if ((p.vid, p.pid) == USB_ID and named_nanovna(p)) or is_approved(p)]


def original_firmware_ports(ports, usb_name=windows_usb_name) -> list[str]:
    """Ports that may be a NanoVNA running the original firmware (edy555/ttrftech): the NanoVNA's
    USB ID with ChibiOS's generic name, "ChibiOS/RT Virtual COM Port" (its usbcfg.c, read
    2026-11-17). Only for the not-found message: both are defaults other gadgets share, so these
    are never opened unless the person picks one (T3)."""
    def chibios(p) -> bool:
        return "chibios" in f"{p.product or ''} {p.description or ''} {usb_name(p)}".lower()
    return [p.device for p in ports if (p.vid, p.pid) == USB_ID and chibios(p)]


def original_firmware_hint(ports, port_option: bool, usb_name=windows_usb_name) -> str:
    """One sentence naming a port that may be a NanoVNA with the original firmware, or ""."""
    maybe = original_firmware_ports(ports, usb_name)
    if not maybe:
        return ""
    how = f"give it with --port {maybe[0]}" if port_option else "choose it under Is your NanoVNA one of these?"
    return (f" {maybe[0]} has the NanoVNA's USB ID but a generic name, as the original NanoVNA firmware "
            f"names it; if it's your NanoVNA, {how}.")


def find_port(ports, port_option: bool = True, approved=(), usb_name=windows_usb_name) -> str:
    """The NanoVNA's port, from pyserial's list_ports.comports(). Never guesses (T3): writing
    NanoVNA commands to the wrong port, such as a radio's CAT port, could change its settings.
    `port_option`: whether the person can give --port (the command can; the app can't)."""
    found = nanovna_ports(ports, approved, usb_name)
    if len(found) == 1:
        return found[0]
    if found:
        raise DeviceError(f"Found more than one NanoVNA ({', '.join(found)}); "
                          + ("choose one with --port" if port_option else "unplug one"))
    connected = ", ".join(p.device for p in ports) or "no USB serial ports are connected"
    hint = original_firmware_hint(ports, port_option, usb_name)
    raise DeviceError(f"No NanoVNA found. Is it plugged in and switched on? Serial ports: {connected}."
                      + (hint or (" If yours has another name, give its port with --port." if port_option else "")))


class NanoVNA:
    MAX_REPLY = 64 * 1024  # a 101-point sweep's data is under 3 KB

    def __init__(self, link, timeout_s: float = 5.0, read_timeout_s: float = 0.25, clock=time.monotonic):
        """`link` is an open serial port (or anything with write() and read() that returns b""
        when `read_timeout_s` passes with nothing to read). `clock` is for tests."""
        self.link = link
        self._clock = clock
        self.timeout_s = timeout_s
        self._read_timeout_s = read_timeout_s

    @classmethod
    def open(cls, port: str, read_timeout_s: float = 0.25) -> "NanoVNA":
        try:
            # exclusive: on macOS/Linux a second program (another Dipstick window, the dipstick
            # command) could otherwise open the port too and mix its commands with ours. It's an
            # advisory lock (flock), so it stops programs that ask for it; Windows ports are always
            # exclusive. QA 2026-11-16, F2.
            # DTR and RTS low before opening: pyserial raises both on open, and many radio interfaces
            # wire one to PTT, so a radio's cable opened by mistake could transmit before sync() finds
            # it isn't a NanoVNA (review 2026-11-16). No port given here, so nothing opens until open().
            link = serial.Serial(baudrate=115200, timeout=read_timeout_s, exclusive=True)  # USB ignores the speed
            link.dtr = link.rts = False
            link.port = port
            link.open()
        except serial.SerialException as error:
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN) or "Access is denied" in str(error):
                raise DeviceError(f"Another program is using the NanoVNA ({port}). Close it (another "
                                  "Dipstick window or the dipstick command) and try again.") from None
            raise DeviceError(f"Can't open {port}: {error}") from None
        nano = cls(link, read_timeout_s=read_timeout_s)
        nano.sync()
        return nano

    def close(self) -> None:
        self.link.close()

    def sync(self) -> None:
        """Get to a clean prompt: send an empty line and drain whatever was left in the buffer
        from an earlier, interrupted session."""
        self._write(b"\r")
        self._read_to_prompt("an empty line", self.timeout_s)
        # Leftovers after the prompt: drain to the first quiet read, but not forever. A NanoVNA
        # whose shell is stuck restarting never goes quiet (seen 2026-11-16: its banner and prompt
        # at about 450 KB/s), and an unbounded drain hung the app. Cap it like a reply (T4): the
        # timeout's worth of reads, and MAX_REPLY bytes.
        drained, reads = 0, math.ceil(self.timeout_s / self._read_timeout_s)
        for _ in range(reads):
            chunk = self._read()
            if not chunk:
                return
            drained += len(chunk)
            if drained > self.MAX_REPLY:
                break
        raise DeviceError("The NanoVNA keeps sending without stopping (its shell seems stuck); "
                          "switch it off and on, then try again.")

    def ask(self, name: str, *args: int | str, timeout_s: float | None = None) -> list[str]:
        """Send one allowed command and return its answer lines (without the echo and prompt).
        `timeout_s`: wait longer than usual for this one (a calibration step sweeps first)."""
        sent = command(name, *args)  # raises ValueError for anything off the allowlist (T1, T2)
        text = sent.decode("ascii").removesuffix("\r")
        self._write(sent)
        reply = self._read_to_prompt(text, timeout_s or self.timeout_s)
        try:
            decoded = reply.decode("ascii")
        except UnicodeDecodeError:
            raise DeviceError(f"The NanoVNA's reply to {text!r} is garbled (not plain text); "
                              "check the USB cable and try again") from None
        lines = decoded.removesuffix(PROMPT.decode()).split("\r\n")
        if lines and lines[-1] == "":
            lines.pop()
        if any(not line.isprintable() for line in lines):
            raise DeviceError(f"The NanoVNA's reply to {text!r} is garbled (control characters); "
                              "check the USB cable and try again")
        if not lines or lines[0] != text:
            raise DeviceError(f"The NanoVNA is out of step: sent {text!r} but the reply was for "
                              f"{lines[0] if lines else 'nothing'!r}. Unplug it and plug it back in.")
        answer = lines[1:]
        if answer == [f"{name}?"]:
            raise DeviceError(f"This NanoVNA's firmware doesn't know {name!r}")
        return answer

    # pyserial raises SerialException when the port vanishes mid-conversation (USB cable pulled, or the NanoVNA switched off);
    # say that plainly instead of letting it surface as an unexplained error.
    def _write(self, data: bytes) -> None:
        try:
            self.link.write(data)
        except serial.SerialException:
            raise DeviceError(_DISCONNECTED) from None

    def _read(self) -> bytes:
        try:
            return self.link.read(4096)
        except serial.SerialException:
            raise DeviceError(_DISCONNECTED) from None

    def _read_to_prompt(self, what: str, timeout_s: float) -> bytes:
        reply, silent, max_silent = b"", 0, math.ceil(timeout_s / self._read_timeout_s)
        # Quiet reads time a silence; the clock times the whole reply, so bytes that keep trickling
        # in without ever reaching a prompt can't keep it waiting either (QA 2026-11-16).
        deadline = self._clock() + timeout_s
        while not reply.endswith(PROMPT):
            if self._clock() > deadline:
                raise DeviceError(f"The NanoVNA's reply to {what!r} didn't finish within {timeout_s:g} s; "
                                  "switch it off and on, then try again.")
            chunk = self._read()
            if chunk:
                reply, silent = reply + chunk, 0
            else:
                silent += 1
                if silent >= max_silent:
                    raise DeviceError(f"The NanoVNA didn't answer {what!r} within {timeout_s:g} s; "
                                      "is it switched on and not in a menu?")
            if len(reply) > self.MAX_REPLY:
                raise DeviceError(f"The NanoVNA's reply to {what!r} is too long (over "
                                  f"{self.MAX_REPLY // 1024} KB); unplug it and plug it back in")
        return reply
