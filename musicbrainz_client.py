"""musicbrainz_client.py - Per-track lyrics languages from MusicBrainz (no CLI).

Used by fixtags.py to write the LYRICS_LANGUAGE tag. MusicBrainz stores the sung language on the
"work" a recording is a performance of, as ISO 639-3 codes (`eng`, `deu`, `ksh`, `gle`; `mul`, `und`
and `zxx` for several / undetermined / no linguistic content). One release lookup returns all tracks
of an album; it needs `recording-level-rels` besides `work-rels`, or the work languages silently
do not appear.

Client rules (https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting): an identifying
User-Agent, at most one request per second. Answers are cached per release id so a run over the
whole library is offline after the first pass.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import requests

from log import logger

USER_AGENT = 'DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)'
RELEASE_URL = 'https://musicbrainz.org/ws/2/release/'
MIN_INTERVAL = 1.0  # seconds between requests
CACHE_DAYS = 30
TITLE_MATCH = 0.6  # similarity needed when a file is matched by position instead of by id
ATTEMPTS = 3

_last_request = 0.0


def _pace() -> None:
	"""Keep at least MIN_INTERVAL between two requests of this process."""
	global _last_request
	wait = _last_request + MIN_INTERVAL - time.monotonic()
	if wait > 0:
		time.sleep(wait)
	_last_request = time.monotonic()


def fetch_release(mbid: str) -> dict | None:
	"""The raw release JSON, or None when MusicBrainz could not be asked (never 'no language')."""
	params = {'inc': 'recordings+recording-level-rels+work-rels', 'fmt': 'json'}
	for attempt in range(ATTEMPTS):
		_pace()
		try:
			response = requests.get(
				RELEASE_URL + mbid, params=params, headers={'User-Agent': USER_AGENT}, timeout=30
			)
		except requests.RequestException as exc:
			logger.warning(f'MusicBrainz request failed for {mbid}: {type(exc).__name__}')
		else:
			if response.status_code == 200:
				return response.json()
			if response.status_code not in (429, 502, 503, 504):
				logger.warning(f'MusicBrainz answered {response.status_code} for release {mbid}')
				return None
			retry_after = response.headers.get('Retry-After', '')
			if retry_after.isdigit():
				time.sleep(min(int(retry_after), 30))
		time.sleep(2 * 2**attempt)
	return None


def work_languages(recording: dict) -> list[str]:
	"""The sung languages of a recording: the union over its linked works, in order, no duplicates."""
	out: list[str] = []
	for rel in recording.get('relations', []):
		work = rel.get('work')
		if not work:
			continue
		langs = work.get('languages') or ([work['language']] if work.get('language') else [])
		for lang in langs:
			if lang not in out:
				out.append(lang)
	return out


def parse_release(data: dict) -> dict:
	"""The part of a release lookup this tool needs: one entry per track."""
	tracks = []
	for medium in data.get('media', []):
		for track in medium.get('tracks', []):
			tracks.append(
				{
					'id': track.get('id', ''),
					'disc': medium.get('position', 1),
					'position': track.get('position', 0),
					'title': track.get('title', ''),
					'languages': work_languages(track.get('recording') or {}),
				}
			)
	return {
		'release_language': (data.get('text-representation') or {}).get('language'),
		'tracks': tracks,
	}


def release_languages(mbid: str, cache_dir: Path, refresh: bool = False) -> dict | None:
	"""Parsed release (see parse_release), from the cache when fresh; None if it cannot be had."""
	cache = cache_dir / f'{mbid}.json'
	if cache.exists() and not refresh:
		try:
			entry = json.loads(cache.read_text(encoding='utf-8'))
			fetched = datetime.fromisoformat(entry['fetched'])
			if datetime.now() - fetched < timedelta(days=CACHE_DAYS):
				return entry['release']
		except (OSError, ValueError, KeyError):
			pass  # unreadable cache: ask again
	data = fetch_release(mbid)
	if data is None:
		return None
	release = parse_release(data)
	cache_dir.mkdir(parents=True, exist_ok=True)
	cache.write_text(
		json.dumps({'fetched': datetime.now().isoformat(), 'release': release}, ensure_ascii=False),
		encoding='utf-8',
	)
	return release


def _norm(title: str) -> str:
	return re.sub(r'\W+', ' ', title.casefold()).strip()


def find_track(
	release: dict, release_track_id: str, disc: int, track: int, title: str
) -> dict | None:
	"""The release track a file is: by MUSICBRAINZ_RELEASETRACKID, else by disc/track number when
	the title agrees (a different edition of the album has the same positions, other songs)."""
	if release_track_id:
		for t in release['tracks']:
			if t['id'] == release_track_id:
				return t
	for t in release['tracks']:
		if t['disc'] == disc and t['position'] == track:
			if SequenceMatcher(a=_norm(t['title']), b=_norm(title)).ratio() >= TITLE_MATCH:
				return t
			return None
	return None
