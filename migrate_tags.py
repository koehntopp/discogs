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
from rich.console import Console
from rich.progress import (
	BarColumn,
	MofNCompleteColumn,
	Progress,
	SpinnerColumn,
	TextColumn,
	TimeRemainingColumn,
)

from log import _is_tty, logger


def flactag(tags: dict, key: str) -> str:
	val = tags.get(key, [''])
	return str(val[0]).strip() if val else ''


def process_album_directory(directory: str, write_mode: bool) -> dict | None:
	flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
	if not flacs:
		return None

	first_flac = str(PurePosixPath(directory) / flacs[0])
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
		for fname in flacs:
			fpath = str(PurePosixPath(directory) / fname)
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
		if any(f.endswith('.flac') for f in files):
			album_dirs.append(root)

	total_dirs = len(album_dirs)
	logger.info(f'Found {total_dirs} album directories.')

	records = []
	use_tty = _is_tty
	console = Console(stderr=True)

	progress = Progress(
		SpinnerColumn(),
		TextColumn('[progress.description]{task.description}'),
		BarColumn(),
		MofNCompleteColumn(),
		TimeRemainingColumn(),
		console=console,
		disable=not use_tty,
	)

	with progress:
		task = progress.add_task('Migrating ALBUM & VERSION tags...', total=total_dirs)
		for album_dir in album_dirs:
			res = process_album_directory(album_dir, write_mode=write_mode)
			if res:
				records.append(res)
			progress.update(task, advance=1)

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
