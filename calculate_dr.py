#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
# ]
# ///

import shutil
import subprocess
import sys
from pathlib import Path

from mutagen import MutagenError
from mutagen.flac import FLAC

from disc_layout import album_root_of_file
from log import logger


def _album_is_current(files: list[Path]) -> bool:
    """True if every track has a non-zero DYNAMIC_RANGE and ALBUM_DR is their rounded mean."""
    scores: list[int] = []
    album_values: set[str] = set()
    for p in files:
        try:
            tags = FLAC(str(p)).tags or {}
        except (MutagenError, OSError):
            return False  # unreadable: let drcalc report it
        dr = (tags.get("DYNAMIC_RANGE") or [""])[0]
        if not dr.isdigit() or int(dr) == 0:
            return False
        scores.append(int(dr))
        album_values.add((tags.get("ALBUM_DR") or [""])[0])
    return album_values == {f"{round(sum(scores) / len(scores)):02d}"}


def calculate_dr(albumpath: str) -> bool:
    """Write DYNAMIC_RANGE and ALBUM_DR for every FLAC album under albumpath using drcalc.

    A `Disc N` folder belongs to its parent album (disc_layout), so ALBUM_DR is the mean over all
    discs. Albums whose tags are already complete and consistent are skipped, because drcalc
    re-analyses every file it is given.

    Returns False if drcalc is missing or reported a failure.
    """
    exe = shutil.which("drcalc")
    if not exe:
        logger.error("drcalc not found on PATH (https://github.com/koehntopp/drcalc/releases)")
        return False

    logger.info(f"Starting Dynamic Range calculation in {albumpath}")
    albums: dict[Path, list[Path]] = {}
    for p in Path(albumpath).rglob("*.flac"):
        albums.setdefault(Path(album_root_of_file(p)), []).append(p)

    if not albums:
        logger.error(f"No FLAC files found in {albumpath}")
        return False

    ok = True
    for album_dir, files in sorted(albums.items()):
        if _album_is_current(files):
            logger.info(f"DR tags up to date: {album_dir}")
            continue
        logger.info(f"Processing album in: {album_dir}")
        result = subprocess.run(
            [exe, "--write-tags", "--quiet", "--album", "folder", str(album_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stderr.splitlines():
            if line.strip():
                logger.info(f"drcalc: {line}")
        if result.returncode != 0:
            ok = False
            logger.error(f"drcalc exited with code {result.returncode} for {album_dir}")
            continue
        try:
            album_dr = (FLAC(str(sorted(files)[0])).tags or {}).get("ALBUM_DR") or ["none"]
        except (MutagenError, OSError):
            album_dr = ["unknown"]
        logger.success(f"Album DR {album_dr[0]} for {album_dir.name}")
    return ok


def main() -> None:
    """Command line interface for calculating Dynamic Range scores."""
    albumpath = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(0 if calculate_dr(albumpath) else 1)


if __name__ == "__main__":
    main()
