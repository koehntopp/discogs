#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "pandas",
#   "mutagen",
#   "rich",
# ]
# ///

import argparse
import os
from pathlib import PurePosixPath

import pandas as pd
from mutagen.flac import FLAC

from disc_layout import album_flacs, is_album_dir, is_disc_dir
from log import logger
from scan_progress import scan_progress


def flactag(tags: dict, key: str) -> str:
	val = tags.get(key, [''])
	return str(val[0]).strip() if val else ''


def process_album_directory(directory: str, write_mode: bool) -> dict | None:
	flacs = album_flacs(directory)
	if not flacs:
		return None

	first_flac = str(PurePosixPath(flacs[0]))
	try:
		audio = FLAC(first_flac)
		tags = {k.upper(): [str(x) for x in v] for k, v in audio.tags.items()} if audio.tags else {}
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not read first track in {directory}: {e}')
		return None

	old_album = flactag(tags, 'ALBUM')
	subtitle = flactag(tags, 'SUBTITLE')
	album_format = flactag(tags, 'ALBUM_FORMAT') or subtitle or 'CD'
	album_edition = flactag(tags, 'ALBUM_EDITION')

	title_source = (
		flactag(tags, 'ALBUM_TITLE_OVERRIDE')
		or flactag(tags, 'ALBUM_MASTER_TITLE')
		or flactag(tags, 'ORIGINAL_TITLE')
		or (old_album.split(' [')[0].strip() if '[' in old_album else old_album)
	)

	release_year = (
		flactag(tags, 'ALBUM_RELEASE_YEAR') or flactag(tags, 'DATE') or flactag(tags, 'RELEASEDATE')
	)

	ed_str = f' ({album_edition})' if album_edition else ''
	yr_str = f'{release_year}' if release_year else ''
	fmt_str = f' {album_format}' if album_format else ''
	version_tag = f'{yr_str}{fmt_str}{ed_str}'.strip()
	clean_album = title_source

	record = {
		'Directory': directory,
		'Old_Album': old_album,
		'Clean_Album': clean_album,
		'Version': version_tag,
	}

	if write_mode:
		for fpath in map(PurePosixPath, flacs):
			fpath = str(fpath)
			try:
				tf = FLAC(fpath)
				if not tf.tags:
					tf.add_tags()

				tf['ALBUM'] = [clean_album]
				tf['VERSION'] = [version_tag]

				tf.save()
				try:
					os.utime(fpath, None)
				except Exception as e:  # noqa: BLE001
					logger.warning(f'Could not touch file mtime for {fpath}: {e}')
			except Exception as e:  # noqa: BLE001
				logger.warning(f'Error updating tags in {fpath}: {e}')

	return record


def scan_and_migrate(root_dir: str, write_mode: bool, output_csv: str) -> None:
	logger.info(f'Scanning FLAC library at: {root_dir}')
	album_dirs = []
	for root, _dirs, files in os.walk(root_dir):
		if is_album_dir(_dirs, files):
			album_dirs.append(root)
			_dirs[:] = [d for d in _dirs if not is_disc_dir(d)]  # discs belong to this album

	total_dirs = len(album_dirs)
	logger.info(f'Found {total_dirs} album directories.')

	records = []
	with scan_progress(total_dirs, 'Migrating ALBUM & VERSION tags') as tick:
		for album_dir in album_dirs:
			res = process_album_directory(album_dir, write_mode=write_mode)
			if res:
				records.append(res)
			tick()

	df = pd.DataFrame(records)
	df.to_csv(output_csv, index=False)
	logger.info(f'Migration summary saved to {output_csv}')


def main() -> None:
	parser = argparse.ArgumentParser(
		description='Migrate FLAC tags (ALBUM & VERSION) and generate summary CSV.'
	)
	parser.add_argument('directory', nargs='?', default='.', help='Library root directory')
	parser.add_argument(
		'--write', action='store_true', help='Write updated ALBUM & VERSION tags back to FLAC files'
	)
	parser.add_argument(
		'--output',
		default='migration_dry_run.csv',
		help='Output CSV file path (default: migration_dry_run.csv)',
	)
	args = parser.parse_args()

	scan_and_migrate(args.directory, write_mode=args.write, output_csv=args.output)


if __name__ == '__main__':
	main()
