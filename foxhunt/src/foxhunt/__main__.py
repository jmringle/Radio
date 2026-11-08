"""`foxhunt --freq 146.565 [--source sim|rtl]`: starts the meter page on http://127.0.0.1:PORT."""
import argparse
import sys
from pathlib import Path

from foxhunt.meter import Meter, parse_settings

DEFAULT_PORT = 8075
DATA_DIR = Path(__file__).resolve().parents[2] / "data"  # foxhunt/data, gitignored


def _port(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a port number") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be 1024-65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foxhunt", description="Live signal meter for fox hunting.")
    parser.add_argument("--freq", required=True, help="the fox's frequency in MHz, e.g. 146.565")
    parser.add_argument("--source", choices=["sim", "rtl"], default="sim", help="sim (default) or rtl (RTL-SDR)")
    parser.add_argument("--gain", default="20", help="fixed tuner gain in dB, 0-50 (default 20)")
    parser.add_argument("--att", default="0", help="your attenuator's setting in dB, 0-120 (default 0)")
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        settings = parse_settings(args.freq, args.gain, args.att)
    except ValueError as error:
        print(f"foxhunt: {error}", file=sys.stderr)
        return 2

    import uvicorn  # loaded only when actually serving

    from foxhunt.server import create_app
    from foxhunt.sources import RtlSource, SimSource

    source = RtlSource() if args.source == "rtl" else SimSource(realtime=True)
    app = create_app(source, Meter(settings, DATA_DIR), args.port)
    print(f"foxhunt: open http://127.0.0.1:{args.port} (Ctrl+C stops)")
    # 127.0.0.1 only: nothing else on the network can reach it (threat model T1).
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
