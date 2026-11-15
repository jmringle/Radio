"""Talking to the NanoVNA (README acceptance criteria: finding it, failure; threat model T3, T4).

The fake link plays back replies recorded byte for byte from a NanoVNA-H, firmware 1.2.43
(tests/fixtures/), so these run without hardware. test_hardware.py checks the real thing."""

from dataclasses import dataclass

import pytest
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

def test_unplugged_while_waiting_for_the_reply():
    nano = NanoVNA(UnpluggedLink({}, unplug_on=b"version"))
    with pytest.raises(DeviceError, match="The NanoVNA disconnected.*Plug it back in"):
        nano.ask("version")


def test_unplugged_before_sending():
    nano = NanoVNA(UnpluggedLink({}, unplug_on=b"version"))
    nano.link.gone = True  # already gone: the write itself fails
    with pytest.raises(DeviceError, match="The NanoVNA disconnected"):
        nano.ask("version")


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
