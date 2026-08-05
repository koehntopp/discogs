#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "mutagen",
#   "requests",
#   "rich",
#   "click",
#   "structlog",
# ]
# ///
"""
lrclib_submitter.py — Submit FLAC lyrics to LRCLIB API with automated Proof-of-Work.

Extracts track metadata (TITLE, ARTIST/ALBUMARTIST, ALBUM, audio duration) and the LYRICS
tag from a target .flac file, solves the LRCLIB SHA-256 Proof-of-Work challenge, and submits
the synced or plain lyrics to LRCLIB (lrclib.net).

Usage:
    uv run lrclib_submitter.py /path/to/song.flac [--dry-run]
"""

import hashlib
import re
import sys
from pathlib import Path

import click
import requests
from mutagen.flac import FLAC
from rich.console import Console

from log import logger

USER_AGENT = 'DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)'
API_URL = 'https://lrclib.net/api'
LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')

console = Console(stderr=True)


def flactag(song: FLAC | dict, tag: str) -> str:
	"""Retrieve tag value from FLAC tag mapping."""
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


def solve_challenge(prefix: str, target: str) -> str:
	"""
	Solve the LRCLIB Proof-of-Work challenge by finding a nonce such that
	SHA256(prefix + nonce) < target.
	Returns the publish token string '{prefix}:{nonce}'.
	"""
	nonce = 0
	target_int = int(target, 16)
	while True:
		candidate = f'{prefix}{nonce}'.encode()
		digest = hashlib.sha256(candidate).hexdigest()
		if int(digest, 16) < target_int:
			return f'{prefix}:{nonce}'
		nonce += 1


def submit_to_lrclib(
	*,
	track_name: str,
	artist_name: str,
	album_name: str,
	duration: float,
	lyrics: str,
	dry_run: bool = False,
) -> bool:
	"""
	Solve PoW challenge and submit lyrics to LRCLIB API.
	"""
	is_synced = bool(LRC_TIMESTAMP.search(lyrics))
	payload = {
		'trackName': track_name,
		'artistName': artist_name,
		'albumName': album_name,
		'duration': round(duration),
		'syncedLyrics': lyrics if is_synced else None,
		'plainLyrics': None if is_synced else lyrics,
	}

	headers = {'User-Agent': USER_AGENT}

	if dry_run:
		console.print(
			'[bold yellow]Dry-run mode:[/bold yellow] skipping PoW solver and publication.'
		)
		console.print(f'  Track: [cyan]{track_name}[/cyan]')
		console.print(f'  Artist: [cyan]{artist_name}[/cyan]')
		console.print(f'  Album: [cyan]{album_name}[/cyan]')
		console.print(f'  Duration: [cyan]{round(duration)}s[/cyan]')
		console.print(
			f'  Format: [magenta]{"Synced (LRC)" if is_synced else "Plain TXT"}[/magenta]'
		)
		return True

	# 1. Request Challenge
	with console.status('Requesting LRCLIB challenge…'):
		resp = requests.post(f'{API_URL}/request-challenge', headers=headers, timeout=10)
		resp.raise_for_status()
		challenge_data = resp.json()
		prefix = challenge_data['prefix']
		target = challenge_data['target']

	# 2. Solve PoW Challenge
	with console.status('Solving LRCLIB Proof-of-Work challenge…'):
		publish_token = solve_challenge(prefix, target)

	# 3. Publish Lyrics
	headers['X-Publish-Token'] = publish_token
	with console.status('Publishing lyrics to LRCLIB…'):
		pub_resp = requests.post(f'{API_URL}/publish', json=payload, headers=headers, timeout=15)

	if pub_resp.status_code in (200, 201):
		logger.info(
			'lyrics_published',
			track=track_name,
			artist=artist_name,
			album=album_name,
			is_synced=is_synced,
		)
		console.print(
			f'  [bold green]✓ Successfully published lyrics to LRCLIB![/bold green] '
			f'({track_name} - {artist_name})'
		)
		return True

	logger.error('lrclib_publish_failed', status_code=pub_resp.status_code, response=pub_resp.text)
	console.print(
		f'  [bold red]✗ LRCLIB publish failed ({pub_resp.status_code}):[/bold red] {pub_resp.text}'
	)
	return False


@click.command(help='Submit lyrics from a single FLAC file to LRCLIB (lrclib.net).')
@click.argument(
	'target', type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path)
)
@click.option(
	'--dry-run', is_flag=True, help='Preview payload and PoW step without publishing to LRCLIB.'
)
def main(target: Path, dry_run: bool) -> None:
	"""Extract metadata and LYRICS tag from FLAC file and publish to LRCLIB."""
	console.rule(f'[bold]{target.name}[/bold]')

	try:
		audio = FLAC(target)
	except Exception as err:  # noqa: BLE001
		console.print(f'  [bold red]Error reading FLAC file:[/bold red] {err}')
		sys.exit(1)

	lyrics = flactag(audio, 'LYRICS')
	if not lyrics.strip():
		console.print(
			'  [bold red]No LYRICS tag found in FLAC file — nothing to submit.[/bold red]'
		)
		sys.exit(1)

	artist = flactag(audio, 'ARTIST') or flactag(audio, 'ALBUMARTIST')
	title = flactag(audio, 'TITLE')
	album = flactag(audio, 'ALBUM')
	duration = audio.info.length if audio.info else 0.0

	if not title or not artist:
		console.print(
			'  [bold red]Missing required TITLE or ARTIST metadata tags in FLAC file.[/bold red]'
		)
		sys.exit(1)

	success = submit_to_lrclib(
		track_name=title,
		artist_name=artist,
		album_name=album,
		duration=duration,
		lyrics=lyrics,
		dry_run=dry_run,
	)

	if not success:
		sys.exit(1)


if __name__ == '__main__':
	main()
