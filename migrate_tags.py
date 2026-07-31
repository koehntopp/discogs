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
import re
import sys
from pathlib import Path, PurePosixPath

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


def extract_edition_from_parens(old_album: str) -> tuple[str, str]:
	"""Extract edition text inside () brackets from decorated album title."""
	if not old_album:
		return '', ''

	title_part = old_album.split(' [')[0].strip()

	m = re.search(r'\(([^)]+)\)', title_part)
	if m:
		edition = m.group(1).strip()
		clean_title = (title_part[: m.start()] + title_part[m.end() :]).strip()
		return clean_title, edition

	if '[' in old_album and ']' in old_album:
		bracket_content = old_album[old_album.find('[') + 1 : old_album.rfind(']')].strip()
		m_bracket = re.search(r'\(([^)]+)\)', bracket_content)
		if m_bracket:
			edition = m_bracket.group(1).strip()
			return title_part, edition

	return title_part, ''


def process_album_directory(directory: str, write_mode: bool) -> dict | None:
	flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
	if not flacs:
		return None

	# 1. Find max sample rate across all tracks
	max_rate_hz = 0
	for fname in flacs:
		fpath = str(PurePosixPath(directory) / fname)
		try:
			audio = FLAC(fpath)
			if audio.info:
				max_rate_hz = max(max_rate_hz, audio.info.sample_rate)
		except Exception:  # noqa: BLE001, S110
			pass
	max_res_str = (
		f'{max_rate_hz / 1000:.1f}kHz'.replace('.0kHz', 'kHz') if max_rate_hz > 0 else '44.1kHz'
	)

	# 2. Read first track metadata
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

	clean_title, parens_edition = extract_edition_from_parens(old_album)
	album_edition = flactag(tags, 'ALBUM_EDITION') or parens_edition

	title_source = (
		flactag(tags, 'ALBUM_TITLE_OVERRIDE')
		or flactag(tags, 'ALBUM_MASTER_TITLE')
		or flactag(tags, 'ORIGINAL_TITLE')
		or clean_title
	)

	release_year = (
		flactag(tags, 'ALBUM_RELEASE_YEAR') or flactag(tags, 'DATE') or flactag(tags, 'RELEASEDATE')
	)
	master_year = (
		flactag(tags, 'ALBUM_MASTER_YEAR')
		or flactag(tags, 'ORIGINALDATE')
		or flactag(tags, 'ORIGINALRELEASEDATE')
		or release_year
	)

	dr_score = flactag(tags, 'ALBUM_DR') or flactag(tags, 'ALBUM DYNAMIC RANGE')

	# Construct clean ALBUM tag and plain text VERSION tag (no square brackets)
	ed_str = f' ({album_edition})' if album_edition else ''
	yr_str = f'{release_year}' if release_year else ''
	fmt_str = f' {album_format}' if album_format else ''
	version_tag = f'{yr_str}{fmt_str}{ed_str}'.strip()
	new_album = title_source

	record = {
		'Directory': directory,
		'Old_Album': old_album,
		'New_Album': new_album,
		'Version': version_tag,
		'Extracted_Format': album_format,
		'Extracted_Edition': album_edition,
		'Max_Resolution': max_res_str,
		'DR_Score': dr_score,
	}

	if write_mode:
		album_updates = {
			'ALBUM_MASTER_TITLE': [title_source],
			'ALBUM_FORMAT': [album_format],
			'ALBUM_MAX_RESOLUTION': [max_res_str],
			'ALBUM': [new_album],
			'VERSION': [version_tag],
		}
		if master_year:
			album_updates['ALBUM_MASTER_YEAR'] = [master_year]
		if release_year:
			album_updates['ALBUM_RELEASE_YEAR'] = [release_year]
		if album_edition:
			album_updates['ALBUM_EDITION'] = [album_edition]
		if dr_score:
			album_updates['ALBUM_DR'] = [dr_score]

		for fname in flacs:
			fpath = str(PurePosixPath(directory) / fname)
			try:
				tf = FLAC(fpath)
				if not tf.tags:
					tf.add_tags()

				# Track-level space key migrations
				if 'DYNAMIC RANGE' in tf.tags:
					val = tf.tags.pop('DYNAMIC RANGE')
					tf['DYNAMIC_RANGE'] = val
				if 'ACOUSTID FINGERPRINT' in tf.tags:
					val = tf.tags.pop('ACOUSTID FINGERPRINT')
					tf['ACOUSTID_FINGERPRINT'] = val
				if 'ALBUM DYNAMIC RANGE' in tf.tags:
					if 'ALBUM_DR' not in tf.tags:
						tf['ALBUM_DR'] = tf.tags['ALBUM DYNAMIC RANGE']
					tf.tags.pop('ALBUM DYNAMIC RANGE', None)

				# Legacy mapping copies
				if 'DATE' in tf.tags and 'RELEASEDATE' not in tf.tags:
					tf['RELEASEDATE'] = tf.tags['DATE']
				if 'ORIGINALDATE' in tf.tags and 'ORIGINALRELEASEDATE' not in tf.tags:
					tf['ORIGINALRELEASEDATE'] = tf.tags['ORIGINALDATE']

				for k, v in album_updates.items():
					if v:
						tf[k] = v

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
	use_tty = _is_tty()
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
		task = progress.add_task('Migrating tags...', total=total_dirs)
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
		description='Migrate FLAC tags to discrete schema and generate summary CSV.'
	)
	parser.add_argument('directory', nargs='?', default='.', help='Library root directory')
	parser.add_argument(
		'--write', action='store_true', help='Write updated tags back to FLAC files'
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
