#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
# ]
# ///

"""lrc_count.py — Report LRC lyrics coverage per album across a FLAC library.

For each album directory that contains at least one FLAC file, outputs a CSV row with:
    artist, album, track_count, tracks_without_lrc, path

Usage:
    uv run lrc_count.py [<flacdir>] [--output <file.csv>]

If <flacdir> is omitted, config.flacroot is used.
If --output is omitted, the CSV is written to stdout.
"""

import csv
import os
import re
import sys
from pathlib import Path

from mutagen.flac import FLAC

from log import logger

LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')


def _flactag(song: FLAC, tag: str) -> str:
	"""Return the first value of a FLAC tag (case-insensitive), or empty string."""
	if not song.tags:
		return ''
	for k in (tag, tag.upper(), tag.lower()):
		val = song.tags.get(k)
		if val:
			return str(val[0]) if isinstance(val, (list, tuple)) else str(val)
	return ''


def _has_lrc(song: FLAC) -> bool:
	"""Return True if the LYRICS tag contains at least one valid LRC timestamp."""
	lyrics = _flactag(song, 'LYRICS').strip()
	return bool(lyrics and LRC_TIMESTAMP.search(lyrics))


def scan_album(directory: str) -> dict | None:
	"""Scan one album directory and return coverage stats, or None if no FLACs found."""
	flacs = sorted(f for f in os.listdir(directory) if f.lower().endswith('.flac'))
	if not flacs:
		return None

	# Read artist / album from the first track
	first_path = os.path.join(directory, flacs[0])
	try:
		first = FLAC(first_path)
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not read {first_path}: {e}')
		return None

	artist = _flactag(first, 'ALBUMARTIST') or _flactag(first, 'ARTIST')
	album = (
		_flactag(first, 'ALBUM_TITLE_OVERRIDE')
		or _flactag(first, 'ORIGINAL_TITLE')
		or _flactag(first, 'ALBUM')
		or Path(directory).name
	)

	track_count = 0
	missing_lrc = 0
	missing_paths: list[str] = []

	for filename in flacs:
		track_path = os.path.join(directory, filename)
		track_count += 1
		try:
			song = FLAC(track_path)
			if not _has_lrc(song):
				missing_lrc += 1
				missing_paths.append(track_path)
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read {track_path}: {e}')
			missing_lrc += 1
			missing_paths.append(track_path)

	return {
		'artist': artist,
		'album': album,
		'track_count': track_count,
		'tracks_without_lrc': missing_lrc,
		'path': directory,
	}


def scan_library(flacdir: str) -> list[dict]:
	"""Walk the library root and collect per-album stats."""
	results: list[dict] = []
	for root, dirs, files in os.walk(flacdir):
		dirs.sort()  # deterministic traversal order
		if any(f.lower().endswith('.flac') for f in files):
			row = scan_album(root)
			if row is not None:
				results.append(row)
			dirs.clear()  # don't descend further into an album directory
	return results


def write_csv(rows: list[dict], output_path: str | None) -> None:
	"""Write results as CSV to a file or stdout."""
	fieldnames = ['artist', 'album', 'track_count', 'tracks_without_lrc', 'path']
	if output_path:
		fp = open(output_path, 'w', newline='', encoding='utf-8')  # noqa: SIM115
		close_after = True
	else:
		fp = sys.stdout
		close_after = False

	try:
		writer = csv.DictWriter(fp, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
		writer.writeheader()
		writer.writerows(rows)
	finally:
		if close_after:
			fp.close()


def main() -> None:
	args = sys.argv[1:]
	flacdir: str | None = None
	output_path: str | None = None

	# Simple arg parsing: [flacdir] [--output file]
	i = 0
	while i < len(args):
		if args[i] == '--output' and i + 1 < len(args):
			output_path = args[i + 1]
			i += 2
		elif not args[i].startswith('--'):
			flacdir = args[i]
			i += 1
		else:
			logger.warning(f'Unknown argument: {args[i]}')
			i += 1

	if flacdir is None:
		try:
			from config import flacroot as flacdir  # type: ignore[no-redef]
		except ImportError:
			logger.error('No directory specified and config.flacroot not found.')
			sys.exit(1)

	if not os.path.isdir(flacdir):
		logger.error(f'Directory not found: {flacdir}')
		sys.exit(1)

	logger.info(f'Scanning FLAC library: {flacdir}')
	rows = scan_library(flacdir)
	logger.info(f'Found {len(rows)} albums')

	rows.sort(key=lambda r: r['tracks_without_lrc'], reverse=True)
	write_csv(rows, output_path)

	if output_path:
		logger.info(f'CSV written to {output_path}')


if __name__ == '__main__':
	main()
