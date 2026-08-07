#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
# ]
# ///

"""lrc_count.py — Report lyrics coverage per album artist across a FLAC library.

For each album artist, aggregates track counts across their whole discography by
lyric status and outputs a CSV row with:
    album_artist, lrc, txt, instrumental, no_lyrics

Rows are sorted by highest TXT count first (artists most in need of an LRC upgrade
pass, e.g. via align_lyrics.py).

Usage:
    uv run lrc_count.py [<flacdir>] [--output <file.csv>]

If <flacdir> is omitted, config.flacroot is used.
If --output is omitted, the CSV is written to stdout.
"""

import csv
import os
import re
import sys
from collections import defaultdict

from mutagen.flac import FLAC

from log import logger

LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')
INSTRUMENTAL_MARKER = '[instrumental:true]'


def _flactag(song: FLAC, tag: str) -> str:
	"""Return the first value of a FLAC tag (case-insensitive), or empty string."""
	if not song.tags:
		return ''
	for k in (tag, tag.upper(), tag.lower()):
		val = song.tags.get(k)
		if val:
			return str(val[0]) if isinstance(val, (list, tuple)) else str(val)
	return ''


def _lyric_status(song: FLAC) -> str:
	"""Classify a track's LYRICS tag as 'instrumental', 'lrc', 'txt', or 'none'."""
	lyrics = _flactag(song, 'LYRICS').strip()
	if not lyrics:
		return 'none'
	if INSTRUMENTAL_MARKER in lyrics:
		return 'instrumental'
	return 'lrc' if LRC_TIMESTAMP.search(lyrics) else 'txt'


def scan_album(directory: str) -> tuple[str, dict[str, int]] | None:
	"""Scan one album directory and return (album_artist, status_counts), or None."""
	flacs = sorted(f for f in os.listdir(directory) if f.lower().endswith('.flac'))
	if not flacs:
		return None

	# Read artist from the first track
	first_path = os.path.join(directory, flacs[0])
	try:
		first = FLAC(first_path)
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not read {first_path}: {e}')
		return None

	artist = _flactag(first, 'ALBUMARTIST') or _flactag(first, 'ARTIST')

	counts = {'lrc': 0, 'txt': 0, 'none': 0, 'instrumental': 0}
	for filename in flacs:
		track_path = os.path.join(directory, filename)
		try:
			song = FLAC(track_path)
			counts[_lyric_status(song)] += 1
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read {track_path}: {e}')
			counts['none'] += 1

	return artist, counts


def scan_library(flacdir: str) -> tuple[dict[str, dict[str, int]], int]:
	"""Walk the library root, aggregating lyric-status counts per album artist.

	Returns (artist_counts, album_count).
	"""
	artist_counts: dict[str, dict[str, int]] = defaultdict(
		lambda: {'lrc': 0, 'txt': 0, 'none': 0, 'instrumental': 0}
	)
	album_count = 0
	for root, dirs, files in os.walk(flacdir):
		dirs.sort()  # deterministic traversal order
		if any(f.lower().endswith('.flac') for f in files):
			result = scan_album(root)
			if result is not None:
				artist, counts = result
				for status, n in counts.items():
					artist_counts[artist][status] += n
				album_count += 1
			dirs.clear()  # don't descend further into an album directory
	return artist_counts, album_count


def write_csv(rows: list[dict], output_path: str | None) -> None:
	"""Write results as CSV to a file or stdout."""
	fieldnames = ['album_artist', 'lrc', 'txt', 'instrumental', 'no_lyrics']
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
	artist_counts, album_count = scan_library(flacdir)
	logger.info(f'Found {album_count} albums across {len(artist_counts)} artists')

	rows = [
		{
			'album_artist': artist,
			'lrc': counts['lrc'],
			'txt': counts['txt'],
			'instrumental': counts['instrumental'],
			'no_lyrics': counts['none'],
		}
		for artist, counts in artist_counts.items()
	]
	rows.sort(key=lambda r: (-r['txt'], r['album_artist']))
	write_csv(rows, output_path)

	if output_path:
		logger.info(f'CSV written to {output_path}')


if __name__ == '__main__':
	main()
