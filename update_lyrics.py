#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
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

from log import _console_handler, logger
from lrc_format import (
	apply_headers,
	capitalize_lrc,
	capitalize_txt,
	has_manual_instrumental_marker,
	is_instrumental_marker,
	is_invalid_lrc,
	is_lrc,
	make_instrumental_lrc,
	resolve_artist,
)

USER_AGENT = 'DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)'
MAX_WORKERS = 8


def flactag(song: FLAC | dict, tag: str) -> str:
	tags = song.tags if isinstance(song, FLAC) and song.tags else song
	if not isinstance(tags, dict):
		try:
			tags = dict(tags)
		except (TypeError, ValueError):
			tags = {}
	for k in (tag, tag.upper(), tag.lower()):
		if tags.get(k):
			val = tags[k]
			return str(val[0]) if isinstance(val, (list, tuple)) else str(val)
	return ''


def _fetch_one(
	flac_path: str, session: requests.Session
) -> tuple[str, str, str, str, str, str, str, str]:
	"""Read tags, fetch/upgrade lyrics, apply LRC metadata headers from FLAC tags.

	Returns:
	    (flac_path, artist, title, lyrics_text, lyrics_type, status, discogs_id, track)
	"""
	if not os.path.isfile(flac_path):
		return flac_path, '', '', '', 'none', 'skip', '', ''

	discogs_id = ''
	track = ''
	artist = ''
	title = ''
	existing_lyrics = ''

	try:
		song = FLAC(flac_path)
		artist = resolve_artist(flactag(song, 'ALBUMARTIST'), flactag(song, 'ARTIST'))
		title = flactag(song, 'TITLE')
		discogs_id = flactag(song, 'DISCOGS_RELEASE_ID')
		track = flactag(song, 'TRACKNUMBER')
		album = flactag(song, 'ALBUM')
		existing_lyrics = flactag(song, 'LYRICS').strip()
		length = float(song.info.length) if song.info and hasattr(song.info, 'length') else 0.0
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not read FLAC tags for {flac_path}: {e}')
		return flac_path, '', '', '', 'none', 'error', '', ''

	if not artist or not title:
		logger.info(f'Missing ALBUMARTIST/ARTIST or TITLE tag in {flac_path}')
		return flac_path, artist, title, '', 'none', 'error', discogs_id, track

	# Check existing embedded FLAC lyrics
	if existing_lyrics and is_instrumental_marker(existing_lyrics):
		return flac_path, artist, title, existing_lyrics, 'instrumental', 'skip', discogs_id, track

	if existing_lyrics and has_manual_instrumental_marker(existing_lyrics):
		# User (or another tool) left an informal/incomplete instrumental marker —
		# normalize to the canonical block without hitting lrclib.net. This is a
		# syntax fix, not new information, so it's counted as 'fix' not 'new'.
		marker_lrc = make_instrumental_lrc(artist, title, album, length)
		return flac_path, artist, title, marker_lrc, 'instrumental', 'fix', discogs_id, track

	had_invalid_lrc = False
	if existing_lyrics:
		if is_invalid_lrc(existing_lyrics):
			logger.warning(
				f'Found invalid LRC timestamp in FLAC tags for {title}, attempting refetch'
			)
			had_invalid_lrc = True
		elif is_lrc(existing_lyrics):
			# Re-apply updated headers if missing/stale, and normalize line capitalization
			updated_lrc = apply_headers(existing_lyrics, artist, title, album, length)
			updated_lrc = capitalize_lrc(updated_lrc)
			if updated_lrc != existing_lyrics:
				return flac_path, artist, title, updated_lrc, 'lrc', 'fix', discogs_id, track
			return flac_path, artist, title, existing_lyrics, 'lrc', 'skip', discogs_id, track

	params = {
		'artist_name': artist,
		'track_name': title,
		'album_name': album,
		'duration': str(round(length)),
	}
	data = {}
	max_retries = 5
	backoff = 2.0
	for attempt in range(max_retries + 1):
		try:
			time.sleep(0.1)  # Smooth inter-request throttling delay
			response = session.get(
				'https://lrclib.net/api/get',
				params=params,
				headers={'User-Agent': USER_AGENT},
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
				retry_after = response.headers.get('Retry-After')
				if retry_after and retry_after.replace('.', '', 1).isdigit():
					sleep_time = float(retry_after) + 0.5
				else:
					sleep_time = backoff * (2**attempt)
				if attempt < max_retries:
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
		except requests.RequestException as e:
			if attempt < max_retries:
				sleep_time = backoff * (2**attempt)
				time.sleep(sleep_time)
			else:
				logger.warning(
					f"Request error ({type(e).__name__}) fetching lyrics for '{title}', retries exhausted"
				)

	if data.get('instrumental'):
		marker_lrc = make_instrumental_lrc(artist, title, album, length)
		if marker_lrc == existing_lyrics:
			return (
				flac_path,
				artist,
				title,
				existing_lyrics,
				'instrumental',
				'skip',
				discogs_id,
				track,
			)
		return flac_path, artist, title, marker_lrc, 'instrumental', 'new', discogs_id, track

	if data.get('syncedLyrics'):
		lrc = re.sub(r'\[(\d{2}:\d{2}\.\d{2})\d\]', r'[\1]', data['syncedLyrics'])
		if is_invalid_lrc(lrc):
			logger.warning(f'Invalid LRC timestamps from lrclib, skipping: {title} ({artist})')
		else:
			lrc = apply_headers(lrc, artist, title, album, length)
			lrc = capitalize_lrc(lrc)
			if lrc == existing_lyrics:
				return flac_path, artist, title, existing_lyrics, 'lrc', 'skip', discogs_id, track
			return flac_path, artist, title, lrc, 'lrc', 'new', discogs_id, track
	if data.get('plainLyrics') and not existing_lyrics:
		txt = capitalize_txt(data['plainLyrics'])
		return flac_path, artist, title, txt, 'txt', 'new', discogs_id, track

	if had_invalid_lrc:
		return flac_path, artist, title, '', 'none', 'clear', discogs_id, track

	# Nothing new fetched — fall back to what's on disk, normalizing capitalization if needed.
	if existing_lyrics:
		is_lrc_existing = is_lrc(existing_lyrics)
		fixed = (
			capitalize_lrc(existing_lyrics) if is_lrc_existing else capitalize_txt(existing_lyrics)
		)
		lyric_type = 'lrc' if is_lrc_existing else 'txt'
		if fixed != existing_lyrics:
			return flac_path, artist, title, fixed, lyric_type, 'fix', discogs_id, track
		return flac_path, artist, title, existing_lyrics, lyric_type, 'skip', discogs_id, track

	return flac_path, artist, title, '', 'none', 'skip', discogs_id, track


def _collect_tracks(flacdir: str) -> list[str]:
	"""Return the path of every FLAC that has a DISCOGS_RELEASE_ID."""
	tracks = []
	for root, _, files in os.walk(flacdir):
		flacs = sorted(f for f in files if f.endswith('.flac'))
		if not flacs:
			continue
		first = os.path.join(root, flacs[0])
		try:
			song = FLAC(first)
			discogs_id_str = flactag(song, 'DISCOGS_RELEASE_ID')
			int(discogs_id_str)
		except (ValueError, TypeError):
			continue
		for f in flacs:
			tracks.append(os.path.join(root, f))
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

	stats = {'lrc': 0, 'txt': 0, 'none': 0, 'instrumental': 0, 'new': 0, 'fixed': 0, 'cleared': 0}
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
		TextColumn('[yellow]Instrumental:[/yellow] {task.fields[instrumental]}'),
		TextColumn('[magenta]New:[/magenta] {task.fields[new]}'),
		TextColumn('[blue]Fixed:[/blue] {task.fields[fixed]}'),
		TextColumn('[red]Cleared:[/red] {task.fields[cleared]}'),
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
				futures = {executor.submit(_fetch_one, path, session): path for path in tracks}
				try:
					for future in as_completed(futures):
						try:
							(
								flac_path,
								artist,
								title,
								lyrics,
								lyric_type,
								action,
								discogs_id,
								track,
							) = future.result()
						except Exception as e:  # noqa: BLE001
							logger.error(f'Fetch error: {e}')
							done += 1
							progress.update(task_id, advance=1, **stats)
							continue

						done += 1
						if lyric_type == 'lrc':
							stats['lrc'] += 1
						elif lyric_type == 'txt':
							stats['txt'] += 1
						elif lyric_type == 'instrumental':
							stats['instrumental'] += 1
						else:
							stats['none'] += 1

						if action in ('new', 'fix', 'clear'):
							if action == 'new':
								stats['new'] += 1
							elif action == 'fix':
								stats['fixed'] += 1
							else:  # 'clear'
								stats['cleared'] += 1
							try:
								t = FLAC(flac_path)
								if not t.tags:
									t.add_tags()
								if action == 'clear':
									if 'LYRICS' in t.tags:
										del t.tags['LYRICS']
									t.save()
									try:
										os.utime(flac_path, None)
									except OSError as e:
										logger.warning(
											f'Could not touch file mtime for {flac_path}: {e}'
										)
									logger.warning(
										f'Invalid LRC cleared (no replacement found): {title} ({artist})'
									)
								else:
									t['LYRICS'] = [lyrics]
									t.save()
									try:
										os.utime(flac_path, None)
									except OSError as e:
										logger.warning(
											f'Could not touch file mtime for {flac_path}: {e}'
										)
									if lyric_type == 'instrumental':
										logger.success(
											f'Instrumental track marked: {title} ({artist})'
										)
									elif action == 'fix':
										logger.success(f'Lyrics fixed: {title} ({artist})')
									else:
										kind = 'LRC' if lyric_type == 'lrc' else 'TXT'
										logger.success(f'{kind} lyrics added: {title} ({artist})')
							except OSError as e:
								logger.error(f'Could not save lyrics for {flac_path}: {e}')

						if discogs_id:
							lrc_file = lyrics_dir / f'{discogs_id}_{track}.lrc'
							txt_file = lyrics_dir / f'{discogs_id}_{track}.txt'
							if action == 'clear' or not lyrics:
								lrc_file.unlink(missing_ok=True)
								txt_file.unlink(missing_ok=True)
							elif lyrics:
								ext = (
									'lrc'
									if lyric_type in ('lrc', 'instrumental')
									or lyrics.startswith('[')
									else 'txt'
								)
								target_file = lyrics_dir / f'{discogs_id}_{track}.{ext}'
								other_file = txt_file if ext == 'lrc' else lrc_file
								other_file.unlink(missing_ok=True)
								target_file.write_text(lyrics, encoding='utf-8')

						progress.update(task_id, advance=1, **stats)

						if not is_tty and time.monotonic() - last_report >= 5:
							logger.info(
								f'Progress: {done}/{total} tracks — '
								f'LRC: {stats["lrc"]} TXT: {stats["txt"]} '
								f'None: {stats["none"]} Instrumental: {stats["instrumental"]} '
								f'New: {stats["new"]} Fixed: {stats["fixed"]} '
								f'Cleared: {stats["cleared"]}'
							)
							last_report = time.monotonic()
				except KeyboardInterrupt:
					logger.warning('Interrupted by user (Ctrl+C). Exiting...')
					executor.shutdown(wait=False, cancel_futures=True)
					if is_tty:
						_console_handler.stream = orig_stream
					os._exit(130)
		finally:
			if is_tty:
				_console_handler.stream = orig_stream

	logger.info(
		f'Done — LRC: {stats["lrc"]} TXT: {stats["txt"]} '
		f'None: {stats["none"]} Instrumental: {stats["instrumental"]} '
		f'New: {stats["new"]} Fixed: {stats["fixed"]} Cleared: {stats["cleared"]}'
	)


if __name__ == '__main__':
	main()
