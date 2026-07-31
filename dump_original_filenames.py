#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
# 	"pytaglib",
# 	"structlog",
# ]
# ///

import argparse
import csv
import os
from pathlib import Path

import taglib

from log import logger

try:
	from config import flacroot
except ImportError:
	flacroot = '.'


def flactag(tags: dict[str, list[str]], tag_name: str) -> str:
	"""Safely extract the first string value of a tag from taglib tags dict."""
	val = tags.get(tag_name, [''])
	return val[0] if val and val[0] else ''


def find_flac_dirs(root: str) -> list[str]:
	"""Walk directory tree and return directories containing at least one FLAC file."""
	flac_dirs = []
	for dirpath, _, files in os.walk(root):
		if any(f.endswith('.flac') for f in files):
			flac_dirs.append(dirpath)
	return sorted(flac_dirs)


def dump_original_filenames(root_dir: str, output_csv: str) -> int:
	"""Scan FLAC albums and write albums with ORIGINAL FILENAME tag to a CSV."""
	logger.info(f'Scanning directory: {root_dir}')
	flac_dirs = find_flac_dirs(root_dir)
	logger.info(f'Found {len(flac_dirs)} album directories')

	rows = []
	for directory in flac_dirs:
		flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
		if not flacs:
			continue
		flac_path = os.path.join(directory, flacs[0])
		try:
			with taglib.File(flac_path) as f:
				tags = f.tags
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read FLAC file {flac_path}: {e}')
			continue

		orig_filename = (
			flactag(tags, 'ORIGINAL FILENAME').strip() or flactag(tags, 'ORIGINAL_FILENAME').strip()
		)
		if not orig_filename:
			continue

		album_name = flactag(tags, 'ALBUM').strip()
		discogs_title = (
			flactag(tags, 'ORIGINAL_TITLE').strip()
			or flactag(tags, 'ALBUM_MASTER_TITLE').strip()
			or flactag(tags, 'ALBUM_RELEASE_TITLE').strip()
		)

		rows.append(
			{
				'file_path': directory,
				'discogs_album_title': discogs_title,
				'ORIGINAL FILENAME': orig_filename,
			}
		)

	fieldnames = ['file_path', 'discogs_album_title', 'ORIGINAL FILENAME']
	output_path = Path(output_csv)
	with output_path.open('w', newline='', encoding='utf-8') as csvfile:
		writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(rows)

	logger.info(f'Successfully wrote {len(rows)} matching albums to {output_path.resolve()}')
	return len(rows)


def main():
	parser = argparse.ArgumentParser(
		description='Dump albums with ORIGINAL FILENAME tag to a CSV file.'
	)
	parser.add_argument(
		'root_dir',
		nargs='?',
		default=flacroot,
		help=f'Root directory to scan for FLAC files (default: {flacroot})',
	)
	parser.add_argument(
		'-o',
		'--output',
		default='albums_original_filename.csv',
		help='Output CSV file path (default: albums_original_filename.csv)',
	)
	args = parser.parse_args()

	dump_original_filenames(args.root_dir, args.output)


if __name__ == '__main__':
	main()
