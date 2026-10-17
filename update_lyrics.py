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
import random
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
from lrclib_client import lrclib_headers

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
MAX_ATTEMPTS = 4  # per request; the shared Pacer spaces the attempts
MAX_RETRY_AFTER = 300.0
# Seconds between request starts (all workers together) when lrclib is happy: 0.5 s is 120
# requests/min, two thirds of the ~180/min allowed for a registered Lrclib-App-Id and inside the
# 200-500 ms between requests that lrclib recommends (see lrclib_client.py).
BASE_INTERVAL = 0.5
RETRY_BACKOFF = 1.0  # seconds before the 2nd attempt after a 5xx/network error; doubles each time
MAX_INTERVAL = 8.0
RELAX_AFTER = 10  # consecutive successes before the interval shrinks again
DOWN_AFTER = 5  # failures in a row, with no success for DOWN_WINDOW seconds, open the circuit
DOWN_WINDOW = 60.0
# (cool-down seconds, workers) for each pass over tracks that lrclib failed to answer
RETRY_ROUNDS = ((30, 2), (60, 2))


class Pacer:
	"""Shared request pacing: one request in flight, one request start per interval.

	lrclib asks clients to send requests sequentially. The interval doubles only when lrclib
	answers 429 (a real rate limit) and shrinks again after a run of successes, so it settles
	at whatever rate lrclib tolerates. 5xx and network errors do not change it.
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._slot = threading.Semaphore(1)
		self._interval = BASE_INTERVAL
		self._next_start = 0.0
		self._floor_until = 0.0  # Retry-After: no request may start before this
		self._raised_at = 0.0
		self._successes = 0
		self._fail_streak = 0
		self._last_success = time.monotonic()
		self._down_reported = False
		self._auth_failed = False
		self._auth_reported = False

	def acquire(self) -> float:
		"""Wait for the single request slot and for the next start time; return the start time.

		Every acquire() must be paired with a release() once the request has finished.
		"""
		self._slot.acquire()
		with self._lock:
			now = time.monotonic()
			start = max(now, self._next_start, self._floor_until)
			self._next_start = start + self._interval
		if start > now:
			time.sleep(start - now)
		return start

	def release(self) -> None:
		self._slot.release()

	def failure(
		self, started_at: float, retry_after: float | None = None, rate_limited: bool = False
	) -> tuple[float, bool]:
		"""Record a failed request; return (interval, whether this raised it).

		Only a rate limit (429) widens the interval; other failures just count towards the
		circuit breaker. A request that started before the last raise cannot escalate it again.
		"""
		with self._lock:
			now = time.monotonic()
			self._successes = 0
			self._fail_streak += 1
			raised = False
			if rate_limited and started_at > self._raised_at and self._interval < MAX_INTERVAL:
				self._interval = min(self._interval * 2, MAX_INTERVAL)
				self._raised_at = now
				self._next_start = max(self._next_start, now + self._interval)
				raised = True
			if retry_after is not None:
				self._floor_until = max(self._floor_until, now + min(retry_after, MAX_RETRY_AFTER))
			return self._interval, raised

	def success(self) -> tuple[float, bool]:
		"""Record a good answer; return (interval, whether this relaxed it)."""
		with self._lock:
			self._fail_streak = 0
			self._last_success = time.monotonic()
			self._successes += 1
			relaxed = False
			if self._successes >= RELAX_AFTER and self._interval > BASE_INTERVAL:
				self._interval = max(BASE_INTERVAL, self._interval * 0.75)
				self._successes = 0
				relaxed = True
			return self._interval, relaxed

	def is_down(self) -> bool:
		"""True after DOWN_AFTER failures in a row with no success for DOWN_WINDOW seconds,
		or once lrclib has rejected the app id (retrying cannot help)."""
		with self._lock:
			return self._auth_failed or (
				self._fail_streak >= DOWN_AFTER
				and time.monotonic() - self._last_success >= DOWN_WINDOW
			)

	def reject_credentials(self) -> bool:
		"""Record a 401; True only the first time, so the error is logged once."""
		with self._lock:
			first = not self._auth_reported
			self._auth_failed = True
			self._auth_reported = True
			return first

	def report_down_once(self) -> bool:
		"""True the first time it is called while the circuit is open (for one log line)."""
		if not self.is_down():
			return False
		with self._lock:
			first = not self._down_reported
			self._down_reported = True
			return first

	def close_circuit(self) -> None:
		"""Forget the failure streak before a retry round; keep the learned interval."""
		with self._lock:
			self._fail_streak = 0
			self._last_success = time.monotonic()
			self._down_reported = False
			self._auth_failed = False  # a retry round probes once more
			self._floor_until = 0.0


def _lrclib_get(session: requests.Session, pacer: Pacer, params: dict, title: str) -> dict | None:
	"""One lrclib lookup: the JSON body on 200, {} on 404, None if lrclib kept failing."""
	reason = ''
	if pacer.is_down():
		return None  # circuit open: defer to the retry rounds instead of waiting again
	for attempt in range(MAX_ATTEMPTS):
		started_at = pacer.acquire()
		retry_after = None
		rate_limited = False
		try:
			try:
				response = session.get(
					LRCLIB_GET_URL, params=params, headers=lrclib_headers(), timeout=10
				)
				if response.status_code == 401:
					if pacer.reject_credentials():
						logger.error(
							'lrclib rejected the Lrclib-App-Id header (401); see lrclib_client.py'
						)
					return None
				if response.status_code in (200, 404):
					body = response.json() if response.status_code == 200 else {}
					interval, relaxed = pacer.success()
					if relaxed:
						logger.info(f'lrclib is answering again; one request per {interval:.1f} s')
					return body
				reason = f'HTTP {response.status_code}'
				rate_limited = response.status_code == 429
				header = response.headers.get('Retry-After')
				if (
					response.status_code in (429, 503)
					and header
					and header.replace('.', '', 1).isdigit()
				):
					# lrclib requires honoring Retry-After plus up to 30% random jitter
					retry_after = float(header) * (1 + random.uniform(0, 0.3))
			except requests.RequestException as e:
				reason = type(e).__name__
		finally:
			pacer.release()
		interval, raised = pacer.failure(started_at, retry_after, rate_limited)
		if raised:
			logger.warning(
				f'lrclib rate limit hit ({reason}); slowing to one request per {interval:.1f} s'
			)
		if pacer.report_down_once():
			logger.warning('lrclib looks down; deferring the remaining tracks to the retry rounds')
		if pacer.is_down():
			break
		if not rate_limited and retry_after is None and attempt < MAX_ATTEMPTS - 1:
			# 5xx / network error: plain backoff, the pacing interval stays as it is
			time.sleep(RETRY_BACKOFF * 2**attempt * (1 + random.uniform(0, 0.3)))
	return None


def _fetch_one(
	flac_path: str, session: requests.Session, pacer: Pacer | None = None
) -> tuple[str, str, str, str, str, str, str, str]:
	"""Read tags, fetch/upgrade lyrics, apply LRC metadata headers from FLAC tags.

	Returns:
	    (flac_path, artist, title, lyrics_text, lyrics_type, status, discogs_id, track)
	"""
	pacer = pacer or Pacer()
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
		body = _lrclib_get(session, pacer, params, title)
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

	logger.warning(
		f"No lyrics found at lrclib: '{title}' (artist searched: '{artist}', album: '{album}')"
	)
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
	paths: list[str], workers: int, session: requests.Session, pacer: Pacer, handle, on_interrupt
) -> list[str]:
	"""Fetch lyrics for paths on a thread pool; pass each result to handle().

	handle() receives the result tuple, or None if the worker raised. Returns the paths
	lrclib failed to answer, so the caller can retry them later.
	"""
	failed = []
	with ThreadPoolExecutor(max_workers=workers) as executor:
		futures = {executor.submit(_fetch_one, path, session, pacer): path for path in paths}
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
	logger.info(
		f'Fetching lyrics for {total} tracks with {MAX_WORKERS} workers (lrclib requests go one at a time)'
	)

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
	pacer = Pacer()

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
				tracks, MAX_WORKERS, session, pacer, lambda r: handle(r, True), on_interrupt
			)
			for cooldown, workers in RETRY_ROUNDS:
				if not failed:
					break
				logger.warning(
					f'{len(failed)} tracks got no answer from lrclib; '
					f'retrying in {cooldown} s with {workers} workers'
				)
				time.sleep(cooldown)
				pacer.close_circuit()
				failed = _run_pass(
					failed, workers, session, pacer, lambda r: handle(r, False), on_interrupt
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
