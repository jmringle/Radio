"""Logs from a folder (LOG_DIR in .env, or --dir): find them, import them once, or watch them.

The folder is only read, never written. Only ALL.TXT and .adi/.adif files directly in it
are used; symlinks are skipped, since one could point anywhere on disk.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ft8_forecast.alltxt import parse_all_txt
from ft8_forecast.logs import Log, TooLarge, read_log, save_log
from ft8_forecast.store import save_decodes

ALL_TXT = "all.txt"  # compared case-insensitively
ADIF_SUFFIXES = (".adi", ".adif")


class FolderError(Exception):
    """The folder can't be used: missing, not a folder, or unreadable."""


def find_logs(folder: Path) -> list[Path]:
    """The log files directly in `folder`, by name. FolderError if it isn't a readable folder."""
    try:
        entries = sorted(folder.iterdir(), key=lambda path: path.name.lower())
    except NotADirectoryError:
        raise FolderError(f"{folder} isn't a folder") from None
    except FileNotFoundError:
        raise FolderError(f"{folder} isn't a folder (not found; is the share mounted?)") from None
    except OSError as error:
        raise FolderError(f"{folder}: {error.strerror}") from None
    return [path for path in entries
            if (path.name.lower() == ALL_TXT or path.suffix.lower() in ADIF_SUFFIXES)
            and not path.is_symlink() and path.is_file()]


@dataclass(frozen=True)
class FileResult:
    path: Path
    log: Log | None  # None when the file couldn't be imported
    new: int
    error: str | None


def import_folder(conn: sqlite3.Connection, folder: Path) -> list[FileResult]:
    """Import every log in the folder, as `ft8cast import` would each file. A file that fails
    is reported and the rest still import. FolderError if there's no folder or no logs."""
    paths = find_logs(folder)
    if not paths:
        raise FolderError(f"no ALL.TXT or .adi files in {folder}")
    return [import_file(conn, path) for path in paths]


def import_file(conn: sqlite3.Connection, path: Path) -> FileResult:
    try:
        with path.open("rb") as file:
            log = read_log(file)
    except TooLarge as error:
        return FileResult(path, None, 0, str(error))
    except OSError as error:
        return FileResult(path, None, 0, error.strerror or str(error))
    if not log.records:
        return FileResult(path, log, 0, f"no FT8 records found (read as {log.kind})")
    return FileResult(path, log, save_log(conn, log), None)


SHOW_PROBLEMS = 10  # per file per check, like `ft8cast import`


@dataclass
class _Seen:
    stat: tuple[int, int, int]  # inode, size, mtime: any change means look again
    offset: int = 0  # ALL.TXT: bytes already read (always at a line end)
    lines: int = 0  # ALL.TXT: lines already read, so problems get the file's line numbers


class Watcher:
    """`ft8cast watch`: each check() imports what changed since the last one.

    ALL.TXT only grows while WSJT-X runs, so only its new complete lines are read; a
    half-written last line waits for the next check. A smaller or replaced file (new
    inode) is read from the start; de-duplication makes that safe. ADIF files are small
    and read whole when they change.
    """

    def __init__(self, folder: Path):
        self.folder = folder
        self.seen: dict[Path, _Seen] = {}
        self.reachable = True

    def check(self, conn: sqlite3.Connection) -> list[str]:
        """One look at the folder; returns what to print (nothing when nothing changed)."""
        messages = []
        try:
            paths = find_logs(self.folder)
        except FolderError as error:
            if not self.reachable:
                return []
            self.reachable = False
            return [f"folder not reachable ({error}); still checking"]
        if not self.reachable:
            self.reachable = True
            messages.append("folder is reachable again")
        for gone in set(self.seen) - set(paths):
            del self.seen[gone]
        for path in paths:
            try:
                messages += self._check_file(conn, path)
            except OSError as error:
                messages.append(f"{path.name}: can't read ({error.strerror or error}); trying again next check")
        return messages

    def _check_file(self, conn: sqlite3.Connection, path: Path) -> list[str]:
        info = path.stat()
        stat = (info.st_ino, info.st_size, info.st_mtime_ns)
        old = self.seen.get(path)
        if old is not None and old.stat == stat:
            return []
        if path.name.lower() != ALL_TXT:
            # An OSError here propagates: check() reports it and the file is tried again.
            # Anything else wrong with the file is reported once, until it changes.
            with path.open("rb") as file:
                try:
                    log = read_log(file)
                except TooLarge as error:
                    self.seen[path] = _Seen(stat)
                    return [f"{path.name}: {error}"]
            self.seen[path] = _Seen(stat)
            if not log.records:
                return [f"{path.name}: no FT8 records found (read as {log.kind})"]
            return _report(path.name, save_log(conn, log), [(p.line, p.message) for p in log.problems])

        # Start over if the file is new, was replaced, or got smaller.
        if old is None or old.stat[0] != stat[0] or stat[1] < old.offset:
            old = _Seen(stat)
        with path.open("rb") as file:
            file.seek(old.offset)
            read = [0, 0]  # bytes, lines of complete lines handed to the parser

            def complete_lines():
                for raw in file:
                    if not raw.endswith(b"\n"):
                        return  # mid-write: next check
                    read[0] += len(raw)
                    read[1] += 1
                    yield raw

            result = parse_all_txt(complete_lines())
        new = save_decodes(conn, result.decodes)
        self.seen[path] = _Seen(stat, old.offset + read[0], old.lines + read[1])
        return _report(path.name, new, [(old.lines + p.line, p.message) for p in result.problems])


def _report(name: str, new: int, problems: list[tuple[int, str]]) -> list[str]:
    lines = [f"{name}: {new:,} new"] if new else []
    lines += [f"{name} line {line}: {message}" for line, message in problems[:SHOW_PROBLEMS]]
    if len(problems) > SHOW_PROBLEMS:
        lines.append(f"{name}: ... and {len(problems) - SHOW_PROBLEMS:,} more problems")
    return lines
