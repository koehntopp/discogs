#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
#   "openpyxl",
# ]
# ///

"""lrc_count.py — Report lyrics coverage per album artist across a FLAC library.

For each album artist, aggregates track counts across their whole discography by
lyric status and outputs a CSV row with:
    album_artist, lrc, txt, instrumental, no_lyrics

Rows are sorted by highest TXT count first (artists most in need of an LRC upgrade
pass, e.g. via lrc_fix.py).

With --tracks, outputs one row per track instead, with columns:
    album_artist, album, song, lyrics_type
`album` is the decorated album title (ALBUM + VERSION, as bliss.py uses for its
directory names). Rows are sorted by album, then disc/track number.

With --suspects, lists the tracks whose synced LRC shows signs of a failed alignment
(see lrc_format.lrc_suspect_reasons: one_timestamp, shared_timestamps, ends_early,
junk_glyphs), one row per track, with columns:
    album_artist, album, song, reasons, lines, last_timestamp, length, directory
Rows with the most reasons come first. Report only: no tag is written. `directory`
can be passed to lrc_fix.py. ends_early and junk_glyphs are hints, not proof (a long
instrumental outro is legitimate).

Usage:
    uv run lrc_count.py [<flacdir>] [--output <file.csv>] [--tracks | --suspects]

If <flacdir> is omitted, config.flacroot is used.
If --output is omitted, the CSV is written to stdout (no .xlsx is written).
If --output is given, an .xlsx workbook with the same rows/columns is written
alongside the CSV (same path, .xlsx extension).
"""

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

from mutagen.flac import FLAC
from openpyxl import Workbook

from log import logger
from lrc_format import INSTRUMENTAL_MARKER, LRC_TIMESTAMP, lrc_body, lrc_suspect_reasons


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


def _decorated_album(song: FLAC, directory: str) -> str:
	"""Return 'ALBUM VERSION' (bliss.py's directory-naming convention), or the
	directory's basename if ALBUM is empty (untagged album)."""
	album = _flactag(song, 'ALBUM')
	version = _flactag(song, 'VERSION')
	decorated = f'{album} {version}'.strip()
	return decorated or os.path.basename(os.path.normpath(directory))


def scan_album_tracks(directory: str) -> list[dict]:
	"""Scan one album directory and return one row per track.

	Each row has 'album_artist', 'album', 'song', 'lyrics_type', plus internal
	'_disc'/'_track' sort keys (not meant for CSV output).
	"""
	flacs = sorted(f for f in os.listdir(directory) if f.lower().endswith('.flac'))
	if not flacs:
		return []

	rows = []
	album_artist = ''
	for filename in flacs:
		track_path = os.path.join(directory, filename)
		try:
			song = FLAC(track_path)
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read {track_path}: {e}')
			continue

		if not album_artist:
			album_artist = _flactag(song, 'ALBUMARTIST') or _flactag(song, 'ARTIST')

		disc, track = _disc_track(song)

		rows.append(
			{
				'album_artist': album_artist,
				'album': _decorated_album(song, directory),
				'song': _flactag(song, 'TITLE') or filename,
				'lyrics_type': _lyric_status(song),
				'_disc': disc,
				'_track': track,
			}
		)
	return rows


def _mmss(seconds: float) -> str:
	return f'{int(seconds) // 60:02d}:{int(seconds) % 60:02d}'


def _disc_track(song: FLAC) -> tuple[int, int]:
	"""(disc, track) sort key from DISCNUMBER/TRACKNUMBER, tolerating 'n/total' and junk."""
	disc_str = _flactag(song, 'DISCNUMBER').split('/')[0]
	track_str = _flactag(song, 'TRACKNUMBER').split('/')[0]
	try:
		disc = int(disc_str)
	except ValueError:
		disc = 1
	try:
		track = int(track_str)
	except ValueError:
		track = 999
	return disc, track


def scan_album_suspects(directory: str) -> list[dict]:
	"""Rows for the tracks of one album whose synced LRC looks like a failed alignment.

	Each row has the CSV columns plus internal '_n'/'_disc'/'_track' sort keys.
	"""
	rows = []
	for filename in sorted(f for f in os.listdir(directory) if f.lower().endswith('.flac')):
		track_path = os.path.join(directory, filename)
		try:
			song = FLAC(track_path)
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read {track_path}: {e}')
			continue
		if _lyric_status(song) != 'lrc':
			continue
		lyrics = _flactag(song, 'LYRICS')
		length = float(song.info.length) if song.info else 0.0
		reasons = lrc_suspect_reasons(lyrics, length)
		if not reasons:
			continue
		times, _ = lrc_body(lyrics)
		disc, track = _disc_track(song)
		rows.append(
			{
				'album_artist': _flactag(song, 'ALBUMARTIST') or _flactag(song, 'ARTIST'),
				'album': _decorated_album(song, directory),
				'song': _flactag(song, 'TITLE') or filename,
				'reasons': '; '.join(reasons),
				'lines': len(times),
				'last_timestamp': _mmss(times[-1]),
				'length': _mmss(length),
				'directory': directory,
				'_n': len(reasons),
				'_disc': disc,
				'_track': track,
			}
		)
	return rows


def scan_library_suspects(flacdir: str) -> list[dict]:
	"""Walk the library root, returning the suspect-LRC rows of every album."""
	rows: list[dict] = []
	for root, dirs, files in os.walk(flacdir):
		dirs.sort()  # deterministic traversal order
		if any(f.lower().endswith('.flac') for f in files):
			rows.extend(scan_album_suspects(root))
			dirs.clear()  # don't descend further into an album directory
	return rows


def scan_library_tracks(flacdir: str) -> list[dict]:
	"""Walk the library root, returning one row per track across all albums."""
	rows: list[dict] = []
	for root, dirs, files in os.walk(flacdir):
		dirs.sort()  # deterministic traversal order
		if any(f.lower().endswith('.flac') for f in files):
			rows.extend(scan_album_tracks(root))
			dirs.clear()  # don't descend further into an album directory
	return rows


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


def write_csv(rows: list[dict], fieldnames: list[str], output_path: str | None) -> None:
	"""Write results as CSV to a file or stdout."""
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


def write_xlsx(rows: list[dict], fieldnames: list[str], output_path: str) -> str:
	"""Write results as a single-sheet .xlsx workbook next to output_path.

	Returns the .xlsx path written.
	"""
	xlsx_path = str(Path(output_path).with_suffix('.xlsx'))
	wb = Workbook()
	ws = wb.active
	ws.append(fieldnames)
	for row in rows:
		ws.append([row[f] for f in fieldnames])
	wb.save(xlsx_path)
	return xlsx_path


def main() -> None:
	args = sys.argv[1:]
	flacdir: str | None = None
	output_path: str | None = None
	tracks_mode = False
	suspects_mode = False

	# Simple arg parsing: [flacdir] [--output file] [--tracks | --suspects]
	i = 0
	while i < len(args):
		if args[i] == '--output' and i + 1 < len(args):
			output_path = args[i + 1]
			i += 2
		elif args[i] == '--tracks':
			tracks_mode = True
			i += 1
		elif args[i] == '--suspects':
			suspects_mode = True
			i += 1
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

	if suspects_mode:
		suspect_rows = scan_library_suspects(flacdir)
		logger.info(f'Found {len(suspect_rows)} tracks with a suspect LRC')
		suspect_rows.sort(key=lambda r: (-r['_n'], r['album'].lower(), r['_disc'], r['_track']))
		fieldnames = [
			'album_artist',
			'album',
			'song',
			'reasons',
			'lines',
			'last_timestamp',
			'length',
			'directory',
		]
		rows = [{k: r[k] for k in fieldnames} for r in suspect_rows]
		write_csv(rows, fieldnames, output_path)
	elif tracks_mode:
		track_rows = scan_library_tracks(flacdir)
		logger.info(f'Found {len(track_rows)} tracks')
		track_rows.sort(key=lambda r: (r['album'].lower(), r['_disc'], r['_track']))
		rows = [
			{
				'album_artist': r['album_artist'],
				'album': r['album'],
				'song': r['song'],
				'lyrics_type': r['lyrics_type'],
			}
			for r in track_rows
		]
		fieldnames = ['album_artist', 'album', 'song', 'lyrics_type']
		write_csv(rows, fieldnames, output_path)
	else:
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
		fieldnames = ['album_artist', 'lrc', 'txt', 'instrumental', 'no_lyrics']
		write_csv(rows, fieldnames, output_path)

	if output_path:
		logger.info(f'CSV written to {output_path}')
		xlsx_path = write_xlsx(rows, fieldnames, output_path)
		logger.info(f'XLSX written to {xlsx_path}')


if __name__ == '__main__':
	main()
