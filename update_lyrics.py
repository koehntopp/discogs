# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "requests",
# ]
# ///

from log import logger, success
import sys
import os
import re
import time
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import taglib

LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')       # valid: [MM:SS.xx]
LRC_BAD_TS    = re.compile(r'\[\d{3,}:\d{2}:\d{2}\.\d{2}\]') # invalid: [HH:MM:SS.xx]
LRC_HEADER    = re.compile(r'^\[(ar|ti|al|by|length|offset):', re.MULTILINE | re.IGNORECASE)
MAX_WORKERS = 32


def _is_lrc(text: str) -> bool:
	return bool(LRC_TIMESTAMP.search(text))


def _is_invalid_lrc(text: str) -> bool:
	"""Detect malformed LRC with 3-part timestamps like [100:40:39.00]."""
	return bool(LRC_BAD_TS.search(text))


def _has_lrc_headers(text: str) -> bool:
	return bool(LRC_HEADER.search(text))


def flactag(song: taglib.File, tag: str) -> str:
	try:
		return song.tags.get(tag, [''])[0]
	except (KeyError, IndexError):
		return ''


def _fetch_one(flac_path: str, album_name: str) -> tuple[str, str, str, str, str, str]:
	"""Read tags, skip if LRC already present, otherwise fetch from lrclib.net.

	Returns (flac_path, artist, title, lyrics, lyric_type, action) where
	action is 'new', 'upgrade', 'keep', or 'none'.
	"""
	try:
		tags = taglib.File(flac_path)
	except OSError as e:
		logger.warning(f'Skipping unreadable file {flac_path}: {e}')
		return flac_path, '', '', '', 'none', 'none'

	artist   = flactag(tags, 'ARTIST')
	title    = flactag(tags, 'TITLE')
	existing = flactag(tags, 'LYRICS').strip()

	# Existing lyrics are malformed — clear them and re-fetch
	had_invalid_lrc = bool(existing and _is_invalid_lrc(existing))
	if had_invalid_lrc:
		logger.warning(f'Invalid LRC timestamps in file, clearing: {title} ({artist})')
		existing = ''

	existing_is_lrc      = _is_lrc(existing)
	existing_has_headers = existing_is_lrc and _has_lrc_headers(existing)

	# Already have LRC with headers — nothing to improve
	if existing_has_headers:
		return flac_path, artist, title, existing, 'lrc', 'keep'

	params = {
		'artist_name': artist,
		'track_name':  title,
		'album_name':  album_name,
		'duration':    str(round(tags.length)),
	}
	try:
		data = requests.get(
			'https://lrclib.net/api/get',
			params=params,
			headers={'User-Agent': 'Mozilla/5.0'},
			timeout=10,
		).json()
		if data.get('syncedLyrics'):
			lrc = re.sub(r'\[(\d{2}:\d{2}\.\d{2})\d\]', r'[\1]', data['syncedLyrics'])
			if _is_invalid_lrc(lrc):
				logger.warning(f'Invalid LRC timestamps from lrclib, skipping: {title} ({artist})')
			else:
				fetched_has_headers = _has_lrc_headers(lrc)
				if existing_is_lrc and not existing_has_headers and fetched_has_headers:
					return flac_path, artist, title, lrc, 'lrc', 'upgrade'
				if not existing_is_lrc:
					return flac_path, artist, title, lrc, 'lrc', 'new'
				return flac_path, artist, title, existing, 'lrc', 'keep'
		if data.get('plainLyrics') and not existing:
			return flac_path, artist, title, data['plainLyrics'], 'txt', 'new'
	except Exception:
		pass

	if had_invalid_lrc:
		return flac_path, artist, title, '', 'none', 'clear'
	return flac_path, artist, title, existing, ('lrc' if existing_is_lrc else 'txt' if existing else 'none'), 'keep'


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
		album_name = flactag(tags, 'ORIGINAL_TITLE').strip() or flactag(tags, 'ALBUM')
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

	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
		futures = {executor.submit(_fetch_one, path, album): path for path, album in tracks}
		for future in as_completed(futures):
			try:
				flac_path, artist, title, lyrics, lyric_type, action = future.result()
			except Exception as e:
				logger.warning(f'Fetch error: {e}')
				done += 1
				continue

			done += 1
			if lyric_type == 'lrc':
				stats['lrc'] += 1
			elif lyric_type == 'txt':
				stats['txt'] += 1
			else:
				stats['none'] += 1

			if action in ('new', 'upgrade', 'clear'):
				stats['new'] += 1
				try:
					t = taglib.File(flac_path)
					if action == 'clear':
						t.tags.pop('LYRICS', None)
						t.save()
						logger.warning(f'Invalid LRC cleared (no replacement found): {title} ({artist})')
					else:
						t.tags['LYRICS'] = [lyrics]
						t.save()
						if action == 'upgrade':
							success(f'LRC upgraded with metadata for {title} ({artist})')
						else:
							success(f'{"LRC" if lyric_type == "lrc" else "TXT"} lyrics added for {title} ({artist})')
				except OSError as e:
					logger.warning(f'Could not save lyrics for {flac_path}: {e}')

			if time.monotonic() - last_report >= 10:
				logger.info(
					f'Progress: {done}/{total} tracks — '
					f'LRC: {stats["lrc"]} TXT: {stats["txt"]} '
					f'None: {stats["none"]} New: {stats["new"]}'
				)
				last_report = time.monotonic()

	logger.info(
		f'Done — LRC: {stats["lrc"]} TXT: {stats["txt"]} '
		f'None: {stats["none"]} New: {stats["new"]}'
	)


if __name__ == '__main__':
	main()
