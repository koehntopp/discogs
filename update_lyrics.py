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
import threading
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
TRAILING_BRACKET_RE = re.compile(r'\s*[\(\[][^()\[\]]*[\)\]]\s*$')


def strip_trailing_bracket(title: str) -> str:
	"""Strip one trailing (...)/[...] group, e.g. '(Live at Wembley)'."""
	return TRAILING_BRACKET_RE.sub('', title).strip()


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


LRCLIB_GET_URL = 'https://lrclib.net/api/get'
MAX_ATTEMPTS = 4  # per request; the shared Throttle does the real pacing
MAX_RETRY_AFTER = 300.0
DOWN_AFTER = 5  # consecutive escalating pauses before lrclib is treated as down
# (cool-down seconds, workers) for each pass over tracks that lrclib failed to answer
RETRY_ROUNDS = ((30, 2), (60, 2))


class Throttle:
	"""Shared back-off: a 429/5xx/network error on any worker pauses every worker."""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._not_before = 0.0
		self._episode_failures = 0

	def wait(self) -> None:
		while True:
			with self._lock:
				delay = self._not_before - time.monotonic()
			if delay <= 0:
				return
			time.sleep(delay)

	def penalize(self, retry_after: float | None = None) -> tuple[float, bool]:
		"""Pause all workers; return (pause seconds, whether this started a new pause).

		Failures that land while a pause is already running belong to the same episode and
		do not escalate it, so eight workers failing together count once.
		"""
		with self._lock:
			now = time.monotonic()
			new_episode = now >= self._not_before
			if new_episode:
				self._episode_failures += 1
			if retry_after is not None:
				delay = min(retry_after, MAX_RETRY_AFTER)
			else:
				delay = min(2.0 * 2 ** (self._episode_failures - 1), 60.0)
			self._not_before = max(self._not_before, now + delay)
		return delay, new_episode

	def success(self) -> None:
		with self._lock:
			self._episode_failures = 0

	def is_down(self) -> bool:
		"""True after DOWN_AFTER pauses in a row with no success in between."""
		with self._lock:
			return self._episode_failures >= DOWN_AFTER

	def reset(self) -> None:
		with self._lock:
			self._not_before = 0.0
			self._episode_failures = 0


def _lrclib_get(
	session: requests.Session, throttle: Throttle, params: dict, title: str
) -> dict | None:
	"""One lrclib lookup: the JSON body on 200, {} on 404, None if lrclib kept failing."""
	reason = ''
	if throttle.is_down():
		return None  # circuit open: defer to the retry rounds instead of waiting again
	for _ in range(MAX_ATTEMPTS):
		throttle.wait()
		time.sleep(0.1)  # smooth inter-request spacing
		retry_after = None
		try:
			response = session.get(
				LRCLIB_GET_URL, params=params, headers={'User-Agent': USER_AGENT}, timeout=10
			)
			if response.status_code == 200:
				body = response.json()
				throttle.success()
				return body
			if response.status_code == 404:
				throttle.success()
				return {}
			reason = f'HTTP {response.status_code}'
			header = response.headers.get('Retry-After')
			if response.status_code == 429 and header and header.replace('.', '', 1).isdigit():
				retry_after = float(header) + 0.5
		except requests.RequestException as e:
			reason = type(e).__name__
		delay, new_episode = throttle.penalize(retry_after)
		if throttle.is_down():
			if new_episode:
				logger.warning(
					f'lrclib looks down ({reason}); deferring the remaining tracks to the retry rounds'
				)
			break
		if new_episode:
			logger.warning(
				f'lrclib is limiting requests ({reason}); pausing all workers for {delay:.0f} s'
			)
	logger.warning(f"lrclib unavailable ({reason}) for '{title}', will retry later")
	return None


def _fetch_one(
	flac_path: str, session: requests.Session, throttle: Throttle | None = None
) -> tuple[str, str, str, str, str, str, str, str]:
	"""Read tags, fetch/upgrade lyrics, apply LRC metadata headers from FLAC tags.

	Returns:
	    (flac_path, artist, title, lyrics_text, lyrics_type, status, discogs_id, track)
	"""
	throttle = throttle or Throttle()
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

	stripped_title = strip_trailing_bracket(title)
	track_names = [title] if stripped_title == title else [title, stripped_title]
	duration = str(round(length))

	# Try each track_name (full title, then stripped) with album_name, then without.
	variants = [
		v
		for track_name in track_names
		for v in (
			{
				'artist_name': artist,
				'track_name': track_name,
				'album_name': album,
				'duration': duration,
			},
			{'artist_name': artist, 'track_name': track_name, 'duration': duration},
		)
	]

	data = {}
	found_via_stripped = False
	for params in variants:
		body = _lrclib_get(session, throttle, params, title)
		if body is None:
			# lrclib is throttling or down, which is not the same as "not found": stop probing
			# further variants and never write or clear anything for this track.
			return flac_path, artist, title, '', 'none', 'failed', discogs_id, track
		if body:
			data = body
			found_via_stripped = params['track_name'] != title
			break

	if found_via_stripped:
		logger.info(f"Lyrics found via stripped title '{stripped_title}' (original: '{title}')")

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


def _apply_result(result: tuple, stats: dict, lyrics_dir: Path) -> None:
	"""Count one finished track and write its lyrics to the FLAC tag and the lyrics cache."""
	flac_path, artist, title, lyrics, lyric_type, action, discogs_id, track = result
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
					logger.warning(f'Could not touch file mtime for {flac_path}: {e}')
				logger.warning(f'Invalid LRC cleared (no replacement found): {title} ({artist})')
			else:
				t['LYRICS'] = [lyrics]
				t.save()
				try:
					os.utime(flac_path, None)
				except OSError as e:
					logger.warning(f'Could not touch file mtime for {flac_path}: {e}')
				if lyric_type == 'instrumental':
					logger.success(f'Instrumental track marked: {title} ({artist})')
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
				'lrc' if lyric_type in ('lrc', 'instrumental') or lyrics.startswith('[') else 'txt'
			)
			target_file = lyrics_dir / f'{discogs_id}_{track}.{ext}'
			other_file = txt_file if ext == 'lrc' else lrc_file
			other_file.unlink(missing_ok=True)
			target_file.write_text(lyrics, encoding='utf-8')


def _run_pass(
	paths: list[str],
	workers: int,
	session: requests.Session,
	throttle: Throttle,
	handle,
	on_interrupt,
) -> list[str]:
	"""Fetch lyrics for paths on a thread pool; pass each result to handle().

	handle() receives the result tuple, or None if the worker raised. Returns the paths
	lrclib failed to answer, so the caller can retry them later.
	"""
	failed = []
	with ThreadPoolExecutor(max_workers=workers) as executor:
		futures = {executor.submit(_fetch_one, path, session, throttle): path for path in paths}
		try:
			for future in as_completed(futures):
				try:
					result = future.result()
				except Exception as e:  # noqa: BLE001
					logger.error(f'Fetch error: {e}')
					handle(None)
					continue
				if result[5] == 'failed':
					failed.append(futures[future])
				handle(result)
		except KeyboardInterrupt:
			logger.warning('Interrupted by user (Ctrl+C). Exiting...')
			executor.shutdown(wait=False, cancel_futures=True)
			on_interrupt()
	return failed


def main() -> None:
	if len(sys.argv) != 2:
		from config import nzbdir as flacdir
	else:
		flacdir = sys.argv[1]

	logger.info(f'Scanning tracks in {flacdir}')
	tracks = _collect_tracks(flacdir)
	total = len(tracks)
	logger.info(f'Fetching lyrics for {total} tracks with up to {MAX_WORKERS} parallel requests')

	stats = {
		'lrc': 0,
		'txt': 0,
		'none': 0,
		'instrumental': 0,
		'new': 0,
		'fixed': 0,
		'cleared': 0,
		'failed': 0,
	}
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
	throttle = Throttle()

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
		TextColumn('[bold red]Failed:[/bold red] {task.fields[failed]}'),
		TimeRemainingColumn(),
		console=console,
		disable=not is_tty,
	)
	task_id = progress.add_task('Fetching', total=total, **stats)

	orig_stream = _console_handler.stream
	failed_info: dict[str, tuple[str, str]] = {}

	def on_interrupt() -> None:
		if is_tty:
			_console_handler.stream = orig_stream
		os._exit(130)

	def handle(result: tuple | None, first_pass: bool) -> None:
		nonlocal done, last_report
		if result is not None:
			path, artist, title, action = result[0], result[1], result[2], result[5]
			if action == 'failed':
				# lrclib did not answer: nothing is written or cleared for this track.
				if first_pass:
					stats['failed'] += 1
				failed_info[path] = (artist, title)
			else:
				if not first_pass:
					stats['failed'] -= 1  # recovered in a retry pass
				failed_info.pop(path, None)
				_apply_result(result, stats, lyrics_dir)
		if not first_pass:
			progress.update(task_id, advance=0, **stats)
			return
		done += 1
		progress.update(task_id, advance=1, **stats)
		if not is_tty and time.monotonic() - last_report >= 5:
			logger.info(
				f'Progress: {done}/{total} tracks — '
				f'LRC: {stats["lrc"]} TXT: {stats["txt"]} '
				f'None: {stats["none"]} Instrumental: {stats["instrumental"]} '
				f'New: {stats["new"]} Fixed: {stats["fixed"]} '
				f'Cleared: {stats["cleared"]} Failed: {stats["failed"]}'
			)
			last_report = time.monotonic()

	failed: list[str] = []
	with progress:
		if is_tty:
			_console_handler.stream = sys.stderr
		try:
			failed = _run_pass(
				tracks, MAX_WORKERS, session, throttle, lambda r: handle(r, True), on_interrupt
			)
			for cooldown, workers in RETRY_ROUNDS:
				if not failed:
					break
				logger.warning(
					f'{len(failed)} tracks got no answer from lrclib; '
					f'retrying in {cooldown} s with {workers} workers'
				)
				time.sleep(cooldown)
				throttle.reset()
				failed = _run_pass(
					failed, workers, session, throttle, lambda r: handle(r, False), on_interrupt
				)
		except KeyboardInterrupt:
			logger.warning('Interrupted by user (Ctrl+C). Exiting...')
			on_interrupt()
		finally:
			if is_tty:
				_console_handler.stream = orig_stream

	for path in failed:
		artist, title = failed_info.get(path, ('', ''))
		logger.warning(f'Lyrics not fetched, lrclib unavailable: {artist} - {title} ({path})')

	logger.info(
		f'Done — LRC: {stats["lrc"]} TXT: {stats["txt"]} '
		f'None: {stats["none"]} Instrumental: {stats["instrumental"]} '
		f'New: {stats["new"]} Fixed: {stats["fixed"]} Cleared: {stats["cleared"]} '
		f'Failed: {stats["failed"]}'
	)


if __name__ == '__main__':
	main()
