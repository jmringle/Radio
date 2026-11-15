"""Talking to a NanoVNA over USB.

The NanoVNA's USB port is a serial port with a text shell. Every exchange looks like this
(recorded from a NanoVNA-H, firmware 1.2.43):

    you send:   version\\r
    it replies: version\\r\\n        <- your command, echoed
                1.2.43\\r\\n         <- the answer, one or more lines
                ch>                  <- the prompt: ready for the next command

A command it doesn't know gets "name?" as its answer.
"""

import math

import serial

from dipstick.commands import command

PROMPT = b"ch> "
# STMicroelectronics' generic USB serial ID: the NanoVNA uses it, and so can any other STM32
# gadget, so the name must say NanoVNA too (T3).
USB_ID = (0x0483, 0x5740)


class DeviceError(Exception):
    """Something went wrong talking to the NanoVNA; the message says what to do."""


def find_port(ports) -> str:
    """The NanoVNA's port, from pyserial's list_ports.comports(). Never guesses (T3): writing
    NanoVNA commands to the wrong port, such as a radio's CAT port, could change its settings."""
    found = [p.device for p in ports
             if (p.vid, p.pid) == USB_ID and "nanovna" in f"{p.product or ''} {p.description or ''}".lower()]
    if len(found) == 1:
        return found[0]
    if found:
        raise DeviceError(f"Found more than one NanoVNA ({', '.join(found)}); choose one with --port")
    connected = ", ".join(p.device for p in ports) or "no USB serial ports are connected"
    raise DeviceError(f"No NanoVNA found. Is it plugged in and switched on? Serial ports: {connected}. "
                      "If yours has another name, give its port with --port.")


class NanoVNA:
    MAX_REPLY = 64 * 1024  # a 101-point sweep's data is under 3 KB

    def __init__(self, link, timeout_s: float = 5.0, read_timeout_s: float = 0.25):
        """`link` is an open serial port (or anything with write() and read() that returns b""
        when `read_timeout_s` passes with nothing to read)."""
        self.link = link
        self.timeout_s = timeout_s
        self._max_silent_reads = math.ceil(timeout_s / read_timeout_s)

    @classmethod
    def open(cls, port: str, read_timeout_s: float = 0.25) -> "NanoVNA":
        try:
            link = serial.Serial(port, 115200, timeout=read_timeout_s)  # USB ignores the speed
        except serial.SerialException as error:
            raise DeviceError(f"Can't open {port}: {error}") from None
        nano = cls(link, read_timeout_s=read_timeout_s)
        nano.sync()
        return nano

    def close(self) -> None:
        self.link.close()

    def sync(self) -> None:
        """Get to a clean prompt: send an empty line and drain whatever was left in the buffer
        from an earlier, interrupted session."""
        self.link.write(b"\r")
        self._read_to_prompt("an empty line")
        while self.link.read(4096):  # leftovers after the prompt; stops at the first quiet read
            pass

    def ask(self, name: str, *args: int) -> list[str]:
        """Send one allowed command and return its answer lines (without the echo and prompt)."""
        sent = command(name, *args)  # raises ValueError for anything off the allowlist (T1, T2)
        text = sent.decode("ascii").removesuffix("\r")
        self.link.write(sent)
        reply = self._read_to_prompt(text)
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

    def _read_to_prompt(self, what: str) -> bytes:
        reply, silent = b"", 0
        while not reply.endswith(PROMPT):
            chunk = self.link.read(4096)
            if chunk:
                reply, silent = reply + chunk, 0
            else:
                silent += 1
                if silent >= self._max_silent_reads:
                    raise DeviceError(f"The NanoVNA didn't answer {what!r} within {self.timeout_s:g} s; "
                                      "is it switched on and not in a menu?")
            if len(reply) > self.MAX_REPLY:
                raise DeviceError(f"The NanoVNA's reply to {what!r} is too long (over "
                                  f"{self.MAX_REPLY // 1024} KB); unplug it and plug it back in")
        return reply
