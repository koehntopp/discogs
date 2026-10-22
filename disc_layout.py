"""disc_layout.py — Shared helpers for the multi-disc album folder layout.

bliss.py puts the tracks of a multi-disc album (a Roon box set) into
``<Album_Version>/Disc <n>/`` subfolders (ADR 0005 section 1, ADR 0008 section 2). Every script
that treats a directory as "one album" uses these helpers so a ``Disc N`` folder counts as part
of its parent album instead of as an album of its own.

No CLI, no third-party dependencies.
"""

import os
import re
from pathlib import Path

DISC_DIR_RE = re.compile(r'^Disc (\d+)$')


def is_disc_dir(name: str) -> bool:
	"""True if a directory name is a disc subfolder (``Disc 2``)."""
	return DISC_DIR_RE.match(name) is not None


def album_root(path: str | Path) -> str:
	"""Album directory of a FLAC file or directory: the parent of a ``Disc N`` folder, else itself.

	For a file path pass the file's directory (``os.path.dirname``) or use ``album_root_of_file``.
	"""
	p = Path(path)
	return str(p.parent if is_disc_dir(p.name) else p)


def album_root_of_file(flac_path: str | Path) -> str:
	"""Album directory that holds a FLAC file, looking through a ``Disc N`` folder."""
	return album_root(Path(flac_path).parent)


def is_album_dir(dirs: list[str], files: list[str]) -> bool:
	"""os.walk helper: True if a directory has FLACs itself or in ``Disc N`` subfolders."""
	return any(f.lower().endswith('.flac') for f in files) or any(is_disc_dir(d) for d in dirs)


def album_flacs(directory: str) -> list[str]:
	"""FLAC paths of an album: its own files, then those of its ``Disc N`` subfolders in order."""
	names = os.listdir(directory)
	flacs = [os.path.join(directory, f) for f in sorted(names) if f.lower().endswith('.flac')]
	discs = sorted((int(m.group(1)), n) for n in names if (m := DISC_DIR_RE.match(n)))
	for _, n in discs:
		sub = os.path.join(directory, n)
		if os.path.isdir(sub):
			flacs += [
				os.path.join(sub, f) for f in sorted(os.listdir(sub)) if f.lower().endswith('.flac')
			]
	return flacs
