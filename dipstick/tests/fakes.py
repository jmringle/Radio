"""Test helpers: a fake serial port and the replies recorded from a real NanoVNA-H (firmware 1.2.43)."""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name):
    return (FIXTURES / f"{name}.bin").read_bytes()


class FakeLink:
    """Stands in for the serial port. Each command written gets its scripted reply, handed out
    a few bytes per read, as USB delivers it; b"" means the read timed out (nothing arrived)."""

    def __init__(self, replies, chunk=7):
        self.replies = replies  # command bytes (without \r) -> reply bytes
        self.chunk = chunk
        self.pending = b""
        self.written = []
        self.empty_reads = 0
        self.closed = False

    def write(self, data):
        self.written.append(data)
        self.pending += self.replies[data.removesuffix(b"\r")]
        return len(data)

    def read(self, size=1):
        n = min(size, self.chunk)
        out, self.pending = self.pending[:n], self.pending[n:]
        self.empty_reads += not out
        return out

    def close(self):
        self.closed = True
