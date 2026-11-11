"""scan_progress.py — Shared progress display for programs that scan many directories.

The same display as update_lyrics.py (SPEC.md "Progress reporting for scanners"):
    terminal (stderr is a TTY)  rich bar on stderr: spinner, bar, M of N, own counters, ETA
    web app / non-TTY           no bar; logger.info('label: done/total ...') at most every
                                LOG_INTERVAL seconds, plus a final line

Usage:
    with scan_progress(count_albums(root), 'Scanning', hits=0) as tick:
        for album in albums:
            ...
            tick(hits=n)  # advances by one; keyword arguments update the counters

No CLI.
"""

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from disc_layout import is_album_dir
from log import _console_handler, logger

LOG_INTERVAL = 5  # seconds between progress lines in the web app log


def count_albums(root: str) -> int:
    """Number of album directories under root (a ``Disc N`` folder belongs to its album)."""
    n = 0
    for _, dirs, files in os.walk(root):
        if is_album_dir(dirs, files):
            n += 1
            dirs.clear()
    return n


@contextmanager
def scan_progress(total: int, label: str = "Scanning", **counters: int) -> Iterator:
    """Progress display for a scan of ``total`` items; yields ``tick(advance=1, **counters)``."""
    is_tty = sys.stderr.isatty()
    progress = Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]{label}:"),
        BarColumn(),
        MofNCompleteColumn(),
        *(TextColumn(f"{name}: {{task.fields[{name}]}}") for name in counters),
        TimeRemainingColumn(),
        console=Console(stderr=True),
        disable=not is_tty,
    )
    task_id = progress.add_task(label, total=total, **counters)
    stats = dict(counters)
    done = 0
    logged_at = -1  # `done` at the last log line, so the final line is not a repeat
    last_report = time.monotonic()

    def line() -> str:
        return f"{label}: {done}/{total}" + "".join(f" {k}: {v}" for k, v in stats.items())

    def tick(advance: int = 1, **fields: int) -> None:
        nonlocal done, last_report, logged_at
        done += advance
        stats.update(fields)
        progress.update(task_id, advance=advance, **stats)
        if not is_tty and time.monotonic() - last_report >= LOG_INTERVAL:
            logger.info(line())
            last_report = time.monotonic()
            logged_at = done

    orig_stream = _console_handler.stream
    with progress:
        if is_tty:
            _console_handler.stream = sys.stderr  # log lines print above the bar
        try:
            yield tick
        finally:
            if is_tty:
                _console_handler.stream = orig_stream
    if not is_tty and logged_at != done:
        logger.info(line())
