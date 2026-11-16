"""Talking to the NanoVNA (README acceptance criteria: finding it, failure; threat model T3, T4).

The fake link plays back replies recorded byte for byte from a NanoVNA-H, firmware 1.2.43
(tests/fixtures/), so these run without hardware. test_hardware.py checks the real thing."""

import errno
from dataclasses import dataclass

import pytest
import serial
from fakes import FakeLink, UnpluggedLink, recorded

from dipstick.device import DeviceError, NanoVNA, find_port

def device(replies, **kwargs):
    return NanoVNA(FakeLink(replies, **kwargs))


# --- asking: the happy path, with recorded replies -------------------------------------------

def test_version():
    assert device({b"version": recorded("version")}).ask("version") == ["1.2.43"]


def test_info_has_the_board():
    lines = device({b"info": recorded("info")}).ask("info")
    assert lines[0] == "Board: NanoVNA-H" and len(lines) == 8


def test_the_current_sweep_settings():
    assert device({b"sweep": recorded("sweep")}).ask("sweep") == ["1500000 30000000 101"]


def test_a_long_reply_arrives_whole():
    link_replies = {b"frequencies": recorded("frequencies"), b"data 0": recorded("data_0")}
    nano = device(link_replies, chunk=64)
    assert len(nano.ask("frequencies")) == 101
    data = nano.ask("data", 0)
    assert len(data) == 101 and data[0] == "1.000189185 -0.000175317"


def test_one_byte_at_a_time_still_works():
    assert device({b"version": recorded("version")}, chunk=1).ask("version") == ["1.2.43"]


def test_the_command_sent_is_the_framed_command():
    nano = device({b"data 0": recorded("data_0")})
    nano.ask("data", 0)
    assert nano.link.written == [b"data 0\r"]


def test_sync_clears_leftovers_before_the_first_command():
    # Leftover bytes from an earlier, interrupted session sit in the buffer. One byte per read,
    # so reading stops at the first prompt and the rest has to be drained.
    nano = device({b"": b"half a line from before\r\nch> \r\nch> ", b"version": recorded("version")}, chunk=1)
    nano.sync()
    assert nano.ask("version") == ["1.2.43"]


class StreamingLink:
    """A NanoVNA whose shell is stuck restarting (seen on the real one, 2026-11-16, after test
    processes were killed mid-conversation): it answers with a prompt, then never goes quiet, about
    450 KB/s of its banner and prompt. `per_read` bytes per read; 1 is a slow trickle."""
    LOOP = b"\r\nNanoVNA Shell\r\nch> ch> "

    def __init__(self, per_read=4096):
        self.per_read, self.reads, self.written, self.sent = per_read, 0, [], 0

    def write(self, data):
        self.written.append(data)
        return len(data)

    def read(self, size=1):  # carries on where the last read stopped, like a real stream
        self.reads += 1
        n, start = min(size, self.per_read), self.sent % len(self.LOOP)
        self.sent += n
        return (self.LOOP * (n // len(self.LOOP) + 2))[start:start + n]


@pytest.mark.parametrize("per_read", [len(StreamingLink.LOOP) * 160, 1], ids=["flood", "trickle"])
def test_sync_gives_up_on_a_nanovna_that_never_goes_quiet(per_read):
    # Before: sync drained leftovers "until the first quiet read", which never came, so the app's
    # sweep hung for good. Now it stops within the timeout's worth of reads (5 s / 0.25 s = 20) and
    # says what to do. A trickle needs about 21 one-byte reads to reach the first prompt.
    link = StreamingLink(per_read)
    nano = NanoVNA(link, timeout_s=5.0, read_timeout_s=0.25)
    with pytest.raises(DeviceError, match="keeps sending.*switch it off and on"):
        nano.sync()
    assert link.reads <= 50


class SlowClock:
    """Each look at the clock is `step` seconds later: a trickle where every byte takes 0.2 s."""
    def __init__(self, step=0.2):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class TrickleLink(FakeLink):
    """Answers `version` with bytes that keep coming, one per read, and never reach a prompt."""
    def read(self, size=1):
        return b"9"


def test_a_reply_that_trickles_on_without_a_prompt_gives_up_on_time():
    # Before: only quiet reads counted towards the timeout, so a never-ending trickle waited for
    # 64 KB of reads (hours at a few bytes a second). Now the whole reply has the timeout (T4).
    link = TrickleLink({b"version": b""})
    nano = NanoVNA(link, timeout_s=5.0, read_timeout_s=0.25, clock=SlowClock(0.2))
    with pytest.raises(DeviceError, match="didn't finish within 5 s"):
        nano.ask("version")


def test_a_slow_step_still_gets_its_longer_time():
    link = TrickleLink({b"version": b""})
    clock = SlowClock(0.2)
    with pytest.raises(DeviceError, match="within 20 s"):
        NanoVNA(link, timeout_s=5.0, read_timeout_s=0.25, clock=clock).ask("version", timeout_s=20.0)
    assert 20.0 <= clock.now <= 21.0


# --- asking: what goes wrong ------------------------------------------------------------------

def test_the_allowlist_still_applies():
    with pytest.raises(ValueError, match="not allowed"):
        device({}).ask("clearconfig")


def test_silence_times_out():
    nano = device({b"version": b""})
    with pytest.raises(DeviceError, match="didn't answer"):
        nano.ask("version")


def test_it_gives_up_after_the_timeout_not_later():
    # Each quiet read is one read timeout long: 1 s / 0.25 s = 4 quiet reads, then give up.
    nano = NanoVNA(FakeLink({b"version": b""}), timeout_s=1.0, read_timeout_s=0.25)
    with pytest.raises(DeviceError, match="within 1 s"):
        nano.ask("version")
    assert nano.link.empty_reads == 4


def test_one_command_can_wait_longer():
    # A calibration step sweeps once at a narrow bandwidth before it answers.
    nano = NanoVNA(FakeLink({b"version": b""}), timeout_s=1.0, read_timeout_s=0.25)
    with pytest.raises(DeviceError, match="within 3 s"):
        nano.ask("version", timeout_s=3.0)
    assert nano.link.empty_reads == 12


def test_a_reply_that_stops_halfway_times_out():
    nano = device({b"version": b"version\r\n1.2."})
    with pytest.raises(DeviceError, match="didn't answer"):
        nano.ask("version")


def test_an_endless_reply_is_cut_off():
    # A reply that never ends with the prompt must not grow without limit (T4).
    nano = device({b"version": b"version\r\n" + b"9" * (NanoVNA.MAX_REPLY + 10)}, chunk=4096)
    with pytest.raises(DeviceError, match="too long"):
        nano.ask("version")


def test_an_unknown_command_reply_is_an_error():
    # "info" is allowed, but give it the reply the firmware sends for a command it doesn't know.
    nano = device({b"info": b"info\r\ninfo?\r\nch> "})
    with pytest.raises(DeviceError, match="doesn't know 'info'"):
        nano.ask("info")


def test_a_wrong_echo_means_out_of_step():
    # The reply belongs to some other command: never use it as this one's answer.
    nano = device({b"version": recorded("sweep")})
    with pytest.raises(DeviceError, match="out of step"):
        nano.ask("version")


@pytest.mark.parametrize("junk", [b"version\r\n\xff\xfe\r\nch> ", b"version\r\n1.2\x1b[2J43\r\nch> "])
def test_garbled_bytes_are_refused(junk):
    # Not plain printable ASCII: noise on the line, or something that isn't the NanoVNA (T4).
    with pytest.raises(DeviceError, match="garbled"):
        device({b"version": junk}).ask("version")


# --- unplugged mid-conversation (pyserial raises its own SerialException) --------------------

# The power switch cuts the NanoVNA-H off USB too (hand test 2026-11-16), so the same error means
# unplugged or switched off; the message names both, without the system's "[Errno 6] Device not
# configured", which tells the person nothing.
DISCONNECTED = "The NanoVNA disconnected (unplugged or switched off). Reconnect it, switch it on, and try again."


def test_unplugged_while_waiting_for_the_reply():
    nano = NanoVNA(UnpluggedLink({}, unplug_on=b"version"))
    with pytest.raises(DeviceError) as raised:
        nano.ask("version")
    assert str(raised.value) == DISCONNECTED


def test_unplugged_before_sending():
    nano = NanoVNA(UnpluggedLink({}, unplug_on=b"version"))
    nano.link.gone = True  # already gone: the write itself fails
    with pytest.raises(DeviceError) as raised:
        nano.ask("version")
    assert str(raised.value) == DISCONNECTED


# --- opening the port: one program at a time (QA 2026-11-16, F2) ---------------------------------
# On macOS two programs could open the port at once; their commands mixed and the loser was told to
# plug the NanoVNA back in. Opening with a lock refuses the second program instead.

class BusySerial:
    """Stands in for serial.Serial when another program already holds the port. The messages are
    pyserial 3.5's: serialposix.py's flock failure (errno EWOULDBLOCK) and serialwin32.py's
    CreateFile failure (Windows ports are always exclusive)."""
    def __init__(self, error):
        self.error = error

    def __call__(self, port, *args, **kwargs):
        raise self.error


def test_the_port_is_opened_with_a_lock(monkeypatch):
    seen = {}
    def fake_serial(port, *args, **kwargs):
        seen.update(kwargs)
        raise serial.SerialException("stop here")
    monkeypatch.setattr(serial, "Serial", fake_serial)
    with pytest.raises(DeviceError):
        NanoVNA.open("/dev/cu.usbmodem-test")
    assert seen.get("exclusive") is True


@pytest.mark.parametrize("error", [
    serial.SerialException(errno.EWOULDBLOCK, "Could not exclusively lock port /dev/cu.usbmodem-test: "
                           "[Errno 35] Resource temporarily unavailable"),
    serial.SerialException("could not open port 'COM3': PermissionError(13, 'Access is denied.', None, 5)"),
], ids=["mac-linux", "windows"])
def test_a_port_in_use_says_another_program_has_it(monkeypatch, error):
    monkeypatch.setattr(serial, "Serial", BusySerial(error))
    with pytest.raises(DeviceError) as raised:
        NanoVNA.open("/dev/cu.usbmodem-test")
    message = str(raised.value)
    assert "Another program is using the NanoVNA" in message
    assert "Plug it back in" not in message


def test_other_open_failures_keep_their_reason(monkeypatch):
    monkeypatch.setattr(serial, "Serial", BusySerial(serial.SerialException(errno.ENOENT, "No such file")))
    with pytest.raises(DeviceError, match="Can't open /dev/cu.usbmodem-test: .*No such file"):
        NanoVNA.open("/dev/cu.usbmodem-test")


# --- finding the NanoVNA ----------------------------------------------------------------------

@dataclass
class Port:  # the fields of pyserial's ListPortInfo that find_port reads
    device: str
    vid: int | None = None
    pid: int | None = None
    product: str | None = None
    description: str = "n/a"


NANO = Port("/dev/cu.usbmodem4001", 0x0483, 0x5740, "NanoVNA-H", "NanoVNA-H")  # as pyserial reports yours


def test_finds_the_nanovna_among_other_ports():
    ports = [Port("/dev/cu.Bluetooth-Incoming-Port"), NANO, Port("/dev/cu.debug-console")]
    assert find_port(ports) == "/dev/cu.usbmodem4001"


@pytest.mark.parametrize("name", ["NanoVNA", "NanoVNA-H4", "NanoVNA-F"])
def test_other_nanovna_models(name):
    assert find_port([Port("/dev/cu.usbmodem1", 0x0483, 0x5740, name)]) == "/dev/cu.usbmodem1"


def test_windows_names_it_in_the_description():
    port = Port("COM3", 0x0483, 0x5740, None, "NanoVNA-H (COM3)")
    assert find_port([port]) == "COM3"


@pytest.mark.parametrize("port", [
    Port("/dev/cu.usbmodem2", 0x0483, 0x5740, "STM32 Virtual ComPort"),  # same generic ST USB ID, not a NanoVNA
    Port("/dev/cu.usbserial-1", 0x10C4, 0xEA60, "CP2102 USB to UART"),   # a typical radio CAT cable
    Port("/dev/cu.usbmodem3", 0x1234, 0x5740, "NanoVNA-H"),             # right name, wrong vendor
])
def test_never_picks_something_that_isnt_a_nanovna(port):
    # Writing NanoVNA commands into a radio's CAT port could change the radio's settings (T3).
    with pytest.raises(DeviceError, match="No NanoVNA found"):
        find_port([port])


def test_none_found_lists_what_is_connected():
    with pytest.raises(DeviceError, match=r"/dev/cu.usbserial-1.*give its port with --port"):
        find_port([Port("/dev/cu.usbserial-1", 0x10C4, 0xEA60, "CP2102 USB to UART")])


def test_two_nanovnas_ask_which():
    other = Port("/dev/cu.usbmodem5001", 0x0483, 0x5740, "NanoVNA-H4")
    with pytest.raises(DeviceError, match=r"more than one.*--port"):
        find_port([NANO, other])


def test_no_serial_ports_at_all():
    with pytest.raises(DeviceError, match="No NanoVNA found.*no USB serial ports"):
        find_port([])
