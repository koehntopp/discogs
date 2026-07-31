#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "requests",
#   "rich",
# ]
# ///

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
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

from log import _console_handler, logger

LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')  # valid: [MM:SS.xx]
LRC_BAD_TS = re.compile(r'\[\d{3,}:\d{2}:\d{2}\.\d{2}\]')  # invalid: [HH:MM:SS.xx]
LRC_HEADER_LINE = re.compile(r'^\[(ar|ti|al|by|length|offset):.*\]\s*$', re.IGNORECASE)
MAX_WORKERS = 8


def _is_lrc(text: str) -> bool:
	return bool(LRC_TIMESTAMP.search(text))


def _is_invalid_lrc(text: str) -> bool:
	return bool(LRC_BAD_TS.search(text))


def _make_headers(artist: str, title: str, album: str, length_secs: float) -> str:
	mins, secs = divmod(int(length_secs), 60)
	return f'[ar:{artist}]\n[ti:{title}]\n[al:{album}]\n[length:{mins:02d}:{secs:02d}]\n'


def _strip_headers(lrc: str) -> str:
	"""Remove existing metadata header lines, keep timestamp lines."""
	return '\n'.join(line for line in lrc.splitlines() if not LRC_HEADER_LINE.match(line)).strip()


def _apply_headers(lrc: str, artist: str, title: str, album: str, length_secs: float) -> str:
	return _make_headers(artist, title, album, length_secs) + _strip_headers(lrc)


def flactag(song: taglib.File, tag: str) -> str:
	try:
		return song.tags.get(tag, [''])[0]
	except (KeyError, IndexError):
		return ''


def _fetch_one(
	flac_path: str, album_name: str, session: requests.Session
) -> tuple[str, str, str, str, str, str, str, str]:
	"""Read tags, fetch/upgrade lyrics, apply LRC metadata headers from FLAC tags.

	Returns (flac_path, artist, title, lyrics, lyric_type, action, discogs_id, track) where
	action is 'new', 'header', 'upgrade', 'clear', 'keep', or 'none'.
	"""
	try:
		tags = taglib.File(flac_path)
	except OSError as e:
		logger.warning(f'Skipping unreadable file {flac_path}: {e}')
		return flac_path, '', '', '', 'none', 'none', '', '00'

	artist = (
		flactag(tags, 'ARTIST')
		or flactag(tags, 'ALBUM_ARTIST_OVERRIDE')
		or flactag(tags, 'ALBUMARTIST')
	)
	title = flactag(tags, 'TITLE')
	length = tags.length
	existing = flactag(tags, 'LYRICS').strip()
	discogs_id = flactag(tags, 'DISCOGS_RELEASE_ID').strip()
	track = flactag(tags, 'TRACKNUMBER').split('/')[0].zfill(2)

	had_invalid_lrc = bool(existing and _is_invalid_lrc(existing))
	if had_invalid_lrc:
		logger.warning(f'Invalid LRC timestamps in file, clearing: {title} ({artist})')
		existing = ''

	existing_is_lrc = _is_lrc(existing)

	# For existing LRC: rebuild headers from FLAC tags and check if anything changed
	if existing_is_lrc:
		with_headers = _apply_headers(existing, artist, title, album_name, length)
		if with_headers != existing:
			return flac_path, artist, title, with_headers, 'lrc', 'header', discogs_id, track
		return flac_path, artist, title, existing, 'lrc', 'keep', discogs_id, track

	clean_album = (
		flactag(tags, 'ALBUM_MASTER_TITLE').strip()
		or flactag(tags, 'ORIGINAL_TITLE').strip()
		or flactag(tags, 'ALBUM_TITLE_OVERRIDE').strip()
		or flactag(tags, 'ORIGINAL FILENAME').strip()
		or flactag(tags, 'ORIGINAL_FILENAME').strip()
		or album_name.split(' [')[0].strip()
	)

	# No LRC yet — fetch from lrclib
	params = {
		'artist_name': artist,
		'track_name': title,
		'album_name': clean_album,
		'duration': str(round(length)),
	}
	data = {}
	max_retries = 5
	backoff = 2.0
	for attempt in range(max_retries + 1):
		try:
			response = session.get(
				'https://lrclib.net/api/get',
				params=params,
				headers={'User-Agent': 'Mozilla/5.0'},
				timeout=10,
			)
			if response.status_code == 200:
				data = response.json()
				break
			elif response.status_code == 404:
				# If album_name exact match was not found on lrclib, fallback to artist + title + duration
				if 'album_name' in params:
					params.pop('album_name')
					continue
				break
			elif response.status_code == 429:
				if attempt < max_retries:
					sleep_time = backoff * (2**attempt)
					time.sleep(sleep_time)
				else:
					logger.warning(
						f"Rate limited (429) fetching lyrics for '{title}', retries exhausted"
					)
			else:
				if attempt < max_retries:
					sleep_time = backoff * (2**attempt)
					time.sleep(sleep_time)
				else:
					logger.warning(
						f"Server error ({response.status_code}) fetching lyrics for '{title}', retries exhausted"
					)
		except Exception as e:
			if attempt < max_retries:
				sleep_time = backoff * (2**attempt)
				time.sleep(sleep_time)
			else:
				logger.warning(
					f"Request error ({type(e).__name__}) fetching lyrics for '{title}', retries exhausted"
				)

	if data.get('syncedLyrics'):
		lrc = re.sub(r'\[(\d{2}:\d{2}\.\d{2})\d\]', r'[\1]', data['syncedLyrics'])
		if _is_invalid_lrc(lrc):
			logger.warning(f'Invalid LRC timestamps from lrclib, skipping: {title} ({artist})')
		else:
			lrc = _apply_headers(lrc, artist, title, album_name, length)
			return flac_path, artist, title, lrc, 'lrc', 'new', discogs_id, track
	if data.get('plainLyrics') and not existing:
		return flac_path, artist, title, data['plainLyrics'], 'txt', 'new', discogs_id, track

	if had_invalid_lrc:
		return flac_path, artist, title, '', 'none', 'clear', discogs_id, track
	return (
		flac_path,
		artist,
		title,
		existing,
		('txt' if existing else 'none'),
		'keep',
		discogs_id,
		track,
	)


def _collect_tracks(flacdir: str) -> list[tuple[str, str]]:
	"""Return (flac_path, album_name) for every FLAC that has a DISCOGS_RELEASE_ID."""
	tracks = []
	for root, _, files in os.walk(flacdir):
		flacs = sorted(f for f in files if f.endswith('.flac'))
		if not flacs:
			continue
		first = os.path.join(root, flacs[0])
		try:
			tags = taglib.File(first)
		except OSError:
			continue
		try:
			int(flactag(tags, 'DISCOGS_RELEASE_ID'))
		except ValueError:
			continue
		album_name = (
			flactag(tags, 'ALBUM_TITLE_OVERRIDE').strip()
			or flactag(tags, 'ORIGINAL FILENAME').strip()
			or flactag(tags, 'ORIGINAL_FILENAME').strip()
			or flactag(tags, 'ALBUM_MASTER_TITLE').strip()
			or flactag(tags, 'ORIGINAL_TITLE').strip()
			or flactag(tags, 'ALBUM').strip()
		)
		for f in flacs:
			tracks.append((os.path.join(root, f), album_name))
	return tracks


def main() -> None:
	if len(sys.argv) != 2:
		from config import nzbdir as flacdir
	else:
		flacdir = sys.argv[1]

	logger.info(f'Scanning tracks in {flacdir}')
	tracks = _collect_tracks(flacdir)
	total = len(tracks)
	logger.info(f'Fetching lyrics for {total} tracks with up to {MAX_WORKERS} parallel requests')

	stats = {'lrc': 0, 'txt': 0, 'none': 0, 'new': 0}
	done = 0
	last_report = time.monotonic()
	is_tty = sys.stderr.isatty()

	data_dir = Path(
		os.environ.get('CONFIG_DIR') or getattr(__import__('config'), 'config_dir', '.')
	)
	lyrics_dir = data_dir / 'lyrics'
	lyrics_dir.mkdir(parents=True, exist_ok=True)

	session = requests.Session()
	adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
	session.mount('https://', adapter)

	console = Console(stderr=True)
	progress = Progress(
		SpinnerColumn(),
		TextColumn('[bold blue]Progress:'),
		BarColumn(),
		MofNCompleteColumn(),
		TextColumn('• [cyan]LRC:[/cyan] {task.fields[lrc]}'),
		TextColumn('[green]TXT:[/green] {task.fields[txt]}'),
		TextColumn('[bright_black]None:[/bright_black] {task.fields[none]}'),
		TextColumn('[magenta]New:[/magenta] {task.fields[new]}'),
		TimeRemainingColumn(),
		console=console,
		disable=not is_tty,
	)

	orig_stream = _console_handler.stream
	with progress:
		if is_tty:
			_console_handler.stream = sys.stderr
		try:
			task_id = progress.add_task('Fetching', total=total, **stats)
			with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
				futures = {
					executor.submit(_fetch_one, path, album, session): path
					for path, album in tracks
				}
				for future in as_completed(futures):
					try:
						flac_path, artist, title, lyrics, lyric_type, action, discogs_id, track = (
							future.result()
						)
					except Exception as e:
						logger.error(f'Fetch error: {e}')
						done += 1
						progress.update(task_id, advance=1, **stats)
						continue

					done += 1
					if lyric_type == 'lrc':
						stats['lrc'] += 1
					elif lyric_type == 'txt':
						stats['txt'] += 1
					else:
						stats['none'] += 1

					if action in ('new', 'header', 'clear'):
						stats['new'] += 1
						try:
							t = taglib.File(flac_path)
							if action == 'clear':
								t.tags.pop('LYRICS', None)
								t.save()
								try:
									os.utime(flac_path, None)
								except Exception as e:
									logger.warning(
										f'Could not touch file mtime for {flac_path}: {e}'
									)
								logger.warning(
									f'Invalid LRC cleared (no replacement found): {title} ({artist})'
								)
							else:
								t.tags['LYRICS'] = [lyrics]
								t.save()
								try:
									os.utime(flac_path, None)
								except Exception as e:
									logger.warning(
										f'Could not touch file mtime for {flac_path}: {e}'
									)
								if action == 'header':
									logger.info(f'LRC headers updated: {title} ({artist})')
								else:
									kind = 'LRC' if lyric_type == 'lrc' else 'TXT'
									logger.info(f'{kind} lyrics added: {title} ({artist})')
						except OSError as e:
							logger.error(f'Could not save lyrics for {flac_path}: {e}')

					if discogs_id:
						lrc_file = lyrics_dir / f'{discogs_id}_{track}.lrc'
						txt_file = lyrics_dir / f'{discogs_id}_{track}.txt'
						if action == 'clear' or not lyrics:
							lrc_file.unlink(missing_ok=True)
							txt_file.unlink(missing_ok=True)
						elif lyrics:
							ext = 'lrc' if lyric_type == 'lrc' or lyrics.startswith('[') else 'txt'
							target_file = lyrics_dir / f'{discogs_id}_{track}.{ext}'
							other_file = txt_file if ext == 'lrc' else lrc_file
							other_file.unlink(missing_ok=True)
							target_file.write_text(lyrics, encoding='utf-8')

					progress.update(task_id, advance=1, **stats)

					if not is_tty and time.monotonic() - last_report >= 5:
						logger.info(
							f'Progress: {done}/{total} tracks — '
							f'LRC: {stats["lrc"]} TXT: {stats["txt"]} '
							f'None: {stats["none"]} New/updated: {stats["new"]}'
						)
						last_report = time.monotonic()
		finally:
			if is_tty:
				_console_handler.stream = orig_stream

	logger.info(
		f'Done — LRC: {stats["lrc"]} TXT: {stats["txt"]} '
		f'None: {stats["none"]} New/updated: {stats["new"]}'
	)


if __name__ == '__main__':
	main()
