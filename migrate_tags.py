#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
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
import taglib
from rich.console import Console
from rich.progress import (
	BarColumn,
	MofNCompleteColumn,
	Progress,
	SpinnerColumn,
	TextColumn,
	TimeRemainingColumn,
)

from log import _console_handler, _is_tty, logger


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
			with taglib.File(fpath) as tf:
				max_rate_hz = max(max_rate_hz, tf.sampleRate)
		except Exception:  # noqa: BLE001, S110
			pass
	max_res_str = (
		f'{max_rate_hz / 1000:.1f}kHz'.replace('.0kHz', 'kHz') if max_rate_hz > 0 else '44.1kHz'
	)

	# 2. Read first track metadata
	first_flac = str(PurePosixPath(directory) / flacs[0])
	try:
		with taglib.File(first_flac) as tf:
			tags = tf.tags
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

	# Construct new decorated ALBUM tag
	ed_str = f' ({album_edition})' if album_edition else ''
	yr_str = f' {release_year}' if release_year else ''
	fmt_str = f' {album_format}' if album_format else ''
	new_album = f'{title_source} [{yr_str.strip()}{fmt_str}{ed_str}]'

	record = {
		'Directory': directory,
		'Old_Album': old_album,
		'New_Album': new_album,
		'Extracted_Format': album_format,
		'Extracted_Edition': album_edition,
		'Max_Resolution': max_res_str,
		'DR_Score': dr_score,
	}

	if write_mode:
		album_updates = {
			'ALBUM_MASTER_TITLE': [title_source],
			'ALBUM_MASTER_YEAR': [master_year] if master_year else [],
			'ALBUM_RELEASE_YEAR': [release_year] if release_year else [],
			'ALBUM_FORMAT': [album_format],
			'ALBUM_MAX_RESOLUTION': [max_res_str],
			'ALBUM': [new_album],
		}
		if album_edition:
			album_updates['ALBUM_EDITION'] = [album_edition]
		if dr_score:
			album_updates['ALBUM_DR'] = [dr_score]

		for fname in flacs:
			fpath = str(PurePosixPath(directory) / fname)
			try:
				with taglib.File(fpath) as tf:
					file_tags = tf.tags

					# Track-level space key migrations
					if 'DYNAMIC RANGE' in file_tags:
						file_tags['DYNAMIC_RANGE'] = file_tags.pop('DYNAMIC RANGE')
					if 'ACOUSTID FINGERPRINT' in file_tags:
						file_tags['ACOUSTID_FINGERPRINT'] = file_tags.pop('ACOUSTID FINGERPRINT')
					if 'ALBUM DYNAMIC RANGE' in file_tags:
						if not flactag(file_tags, 'ALBUM_DR'):
							file_tags['ALBUM_DR'] = file_tags['ALBUM DYNAMIC RANGE']
						file_tags.pop('ALBUM DYNAMIC RANGE', None)

					# Legacy mapping copies
					if 'ORIGINAL_TITLE' in file_tags and 'ALBUM_MASTER_TITLE' not in file_tags:
						file_tags['ALBUM_MASTER_TITLE'] = file_tags['ORIGINAL_TITLE']

					# Apply album-level updates
					for k, v in album_updates.items():
						if v:
							file_tags[k] = v

					tf.save()
					try:
						os.utime(fpath, None)
					except Exception:  # noqa: BLE001, S110
						pass
			except Exception as e:  # noqa: BLE001
				logger.error(f'Error updating {fpath}: {e}')

	return record


def main():
	parser = argparse.ArgumentParser(
		description='Migrate FLAC tags to structured underscore schema.'
	)
	parser.add_argument('directory', nargs='?', help='Directory to process')
	parser.add_argument(
		'--write', action='store_true', help='Apply changes to FLAC files (default is --dry-run)'
	)
	args = parser.parse_args()

	root_dir = args.directory or getattr(__import__('config'), 'flacroot', '.')
	write_mode = args.write

	mode_str = 'WRITE' if write_mode else 'DRY-RUN'
	logger.info(f'Starting tag migration ({mode_str} mode) in {root_dir}')

	flac_dirs = []
	for dirpath, _, files in os.walk(root_dir):
		if any(f.endswith('.flac') for f in files):
			flac_dirs.append(dirpath)

	logger.info(f'Found {len(flac_dirs)} album directories to process')

	console = Console(stderr=True)
	progress = Progress(
		SpinnerColumn(),
		TextColumn('[bold blue]Migrating tags:'),
		BarColumn(),
		MofNCompleteColumn(),
		TimeRemainingColumn(),
		console=console,
		disable=not _is_tty,
	)

	results = []
	orig_stream = _console_handler.stream
	with progress:
		if _is_tty:
			_console_handler.stream = sys.stderr
		try:
			task_id = progress.add_task('Migrating', total=len(flac_dirs))
			for d in flac_dirs:
				rec = process_album_directory(d, write_mode)
				if rec:
					results.append(rec)
				progress.update(task_id, advance=1)
		finally:
			if _is_tty:
				_console_handler.stream = orig_stream

	df = pd.DataFrame(results)
	if not write_mode:
		out_csv = Path('migration_dry_run.csv')
		df.to_csv(out_csv, index=False)
		logger.info(f'Dry-run complete. Results written to {out_csv.resolve()}')
	else:
		logger.info(f'Migration complete. Updated {len(results)} album directories.')


if __name__ == '__main__':
	main()
