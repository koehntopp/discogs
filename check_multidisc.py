#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
# ]
# ///

"""check_multidisc.py — Report albums that classify as multi disc.

An album matches if any of these holds (read only, nothing is written to the library):
    disc      more than one disc: highest DISCNUMBER / DISCTOTAL / TOTALDISCS / disc total in
              "1/2", more than one distinct DISCNUMBER, or `Disc N` subfolders
    subtitle  more than one distinct non-empty SET SUBTITLE across the tracks
    format    more than one distinct sample rate or bit depth (bits per sample) across the tracks

Writes a CSV with columns:
    directory, discs, set_subtitles, formats, reasons, yate_link

Usage:
    uv run check_multidisc.py [<flacdir>] [--csv <file.csv>] [--reason disc|subtitle|format]

If <flacdir> is omitted, config.flacroot_local is used. --csv defaults to multidisc.csv.
`yate_link` opens the album in Yate (config tagger_scheme, flacroot rebased onto flacroot_local).
"""

import argparse
import csv
import os
import re
from pathlib import Path

from mutagen import MutagenError
from mutagen.flac import FLAC

from disc_layout import album_flacs, is_album_dir, is_disc_dir
from log import logger

REASONS = ('disc', 'subtitle', 'format')
FIELDS = ['directory', 'discs', 'set_subtitles', 'formats', 'reasons', 'yate_link']
INT_RE = re.compile(r'\d+')


def tagger_url(directory: str) -> str:
	"""Yate deep link for an album directory, mirroring webui.py's _tagger_url()."""
	try:
		import config
	except ImportError:
		return ''
	scheme = getattr(config, 'tagger_scheme', '')
	flacroot = getattr(config, 'flacroot', '')
	flacroot_local = getattr(config, 'flacroot_local', flacroot)
	if not scheme or not directory or not flacroot:
		return ''
	rel = (
		Path(directory).relative_to(flacroot) if directory.startswith(flacroot) else Path(directory)
	)
	return f'{scheme}{Path(flacroot_local) / rel}'


def _first_int(value: str) -> int:
	m = INT_RE.search(value)
	return int(m.group()) if m else 0


def scan_album(directory: str) -> dict | None:
	"""Classify one album directory; None if it is not multi disc."""
	disc_numbers: set[int] = set()
	disc_count = 0
	subtitles: set[str] = set()
	formats: set[tuple[int, int]] = set()
	for path in album_flacs(directory):
		try:
			flac = FLAC(path)
		except MutagenError as e:
			logger.warning('unreadable', path=path, error=str(e))
			continue
		formats.add((flac.info.sample_rate, flac.info.bits_per_sample))
		tags = flac.tags or {}
		for value in tags.get('DISCNUMBER', []):
			parts = value.split('/')
			n = _first_int(parts[0])
			if n:
				disc_numbers.add(n)
			if len(parts) > 1:
				disc_count = max(disc_count, _first_int(parts[1]))
		for key in ('DISCTOTAL', 'TOTALDISCS'):
			for value in tags.get(key, []):
				disc_count = max(disc_count, _first_int(value))
		for value in tags.get('SET SUBTITLE', []):
			if value.strip():
				subtitles.add(value.strip())

	disc_dirs = [d for d in os.listdir(directory) if is_disc_dir(d)]
	discs = max(disc_count, max(disc_numbers, default=0), len(disc_numbers), len(disc_dirs), 1)
	reasons = []
	if discs > 1:
		reasons.append('disc')
	if len(subtitles) > 1:
		reasons.append('subtitle')
	if len({f[0] for f in formats}) > 1 or len({f[1] for f in formats}) > 1:
		reasons.append('format')
	if not reasons:
		return None
	return {
		'directory': directory,
		'discs': discs,
		'set_subtitles': ' | '.join(sorted(subtitles)),
		'formats': ' | '.join(f'{r / 1000:g}kHz/{b}' for r, b in sorted(formats)),
		'reasons': ','.join(reasons),
		'yate_link': tagger_url(directory),
	}


def scan_library(flacdir: str) -> list[dict]:
	rows = []
	for root, dirs, files in os.walk(flacdir):
		dirs.sort()
		if is_album_dir(dirs, files):
			row = scan_album(root)
			if row:
				rows.append(row)
			dirs.clear()  # an album's Disc N folders belong to it
	return rows


def main() -> None:
	parser = argparse.ArgumentParser(description='Report albums that classify as multi disc.')
	parser.add_argument('flacdir', nargs='?', help='library root (default: config.flacroot_local)')
	parser.add_argument(
		'--csv', default='multidisc.csv', help='output CSV (default: multidisc.csv)'
	)
	parser.add_argument('--reason', choices=REASONS, help='only albums matching this criterion')
	args = parser.parse_args()

	flacdir = args.flacdir
	if not flacdir:
		import config

		flacdir = getattr(config, 'flacroot_local', None) or config.flacroot
	rows = scan_library(flacdir)
	if args.reason:
		rows = [r for r in rows if args.reason in r['reasons'].split(',')]

	with open(args.csv, 'w', newline='', encoding='utf-8') as fp:
		writer = csv.DictWriter(fp, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
		writer.writeheader()
		writer.writerows(rows)
	for reason in REASONS:
		logger.info('multidisc', reason=reason, albums=sum(reason in r['reasons'] for r in rows))
	logger.info('done', albums=len(rows), csv=args.csv)


if __name__ == '__main__':
	main()
