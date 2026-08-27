#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "rich",
#   "structlog",
# ]
# ///

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from rich.console import Console
from rich.progress import (
	BarColumn,
	MofNCompleteColumn,
	Progress,
	SpinnerColumn,
	TextColumn,
	TimeRemainingColumn,
)

import config
from log import _console_handler, logger, success

AUDIOPHILE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
	('SHM-SACD', 'SHM-SACD', re.compile(r'\b(SHM[- ]?SACD|SACD[- ]?SHM)\b', re.IGNORECASE)),
	('SACD', 'Super Audio CD', re.compile(r'\b(SACD|Super Audio CD|Hybrid SACD)\b', re.IGNORECASE)),
	(
		'MFSL / MoFi',
		'Mobile Fidelity Sound Lab',
		re.compile(r'\b(MFSL|Mobile Fidelity|MoFi|UDCD|UltraDisc|UltraDisc II)\b', re.IGNORECASE),
	),
	('UHQCD', 'Ultimate High Quality CD', re.compile(r'\bUHQCD\b', re.IGNORECASE)),
	('SHM-CD', 'Super High Material CD', re.compile(r'\b(SHM[- ]?CD|SHM)\b', re.IGNORECASE)),
	(
		'Gold CD',
		'24k Gold Edition',
		re.compile(r'\b(24k|24kt|24k[- ]Gold|24-Karat Gold|Gold[- ]?CD)\b', re.IGNORECASE),
	),
	(
		'XRCD / K2 HD',
		'Extended Resolution CD / K2 HD',
		re.compile(r'\b(XRCD|XRCD24|XRCD2|K2 HD|K2HD)\b', re.IGNORECASE),
	),
	('Blu-spec CD', 'Blu-spec CD', re.compile(r'\b(Blu[- ]spec|BSCD|BSCD2)\b', re.IGNORECASE)),
	(
		'HDCD / HQCD',
		'High Definition / High Quality CD',
		re.compile(r'\b(HDCD|HQCD)\b', re.IGNORECASE),
	),
	(
		'Hi-Res / Pure Audio',
		'DVD-Audio / Blu-ray Audio',
		re.compile(r'\b(DVD[- ]Audio|DVD[- ]A|Blu[- ]ray Audio|HFPA|Pure Audio)\b', re.IGNORECASE),
	),
]


class DiscogsCachedClient:
	"""Rate-limited and persistently cached Discogs API client."""

	def __init__(self, api_key: str, cache_path: Path, offline: bool = False):
		self.api_key = api_key
		self.cache_path = cache_path
		self.offline = offline
		self.min_interval = 1.1
		self.last_request_time = 0.0
		self.session = requests.Session()
		self.session.headers.update({'User-Agent': 'AudiophileUpgradeFinder/1.0'})
		if self.api_key:
			self.session.headers.update({'Authorization': f'Discogs token={self.api_key}'})
		self.cache: dict[str, Any] = self._load_cache()

	def _load_cache(self) -> dict[str, Any]:
		if self.cache_path.exists():
			try:
				with open(self.cache_path, 'r', encoding='utf-8') as f:
					return json.load(f)
			except Exception as e:  # noqa: BLE001
				logger.warning(f'Failed to load cache from {self.cache_path}: {e}')
		return {'releases': {}, 'masters': {}, 'master_versions': {}, 'searches': {}}

	def save_cache(self) -> None:
		try:
			self.cache_path.parent.mkdir(parents=True, exist_ok=True)
			tmp_file = self.cache_path.with_suffix('.tmp')
			with open(tmp_file, 'w', encoding='utf-8') as f:
				json.dump(self.cache, f, indent=2, ensure_ascii=False)
			tmp_file.replace(self.cache_path)
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Failed to save cache to {self.cache_path}: {e}')

	def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
		if self.offline:
			return None

		elapsed = time.time() - self.last_request_time
		if elapsed < self.min_interval:
			time.sleep(self.min_interval - elapsed)

		retries = 3
		backoff = 60.0
		for attempt in range(retries + 1):
			try:
				resp = self.session.get(url, params=params, timeout=15)
				self.last_request_time = time.time()

				remaining = resp.headers.get('X-Discogs-Ratelimit-Remaining')
				if remaining is not None and int(remaining) < 3:
					time.sleep(5.0)

				if resp.status_code == 429:
					if attempt < retries:
						logger.warning(
							f'Rate limit (429) hit, sleeping {backoff}s (attempt {attempt + 1}/{retries})'
						)
						time.sleep(backoff)
						continue
					else:
						logger.error('Exhausted retries on 429 rate limit.')
						return None

				if resp.status_code == 404:
					return None

				resp.raise_for_status()
				return resp.json()
			except (requests.RequestException, ValueError) as e:
				if attempt < retries:
					logger.warning(
						f'Discogs API error ({e}), retrying in 5s (attempt {attempt + 1}/{retries})'
					)
					time.sleep(5.0)
				else:
					logger.error(f'Failed to fetch {url}: {e}')
					return None
		return None

	def get_release(self, release_id: str | int) -> dict[str, Any] | None:
		key = str(release_id)
		if key in self.cache['releases']:
			return self.cache['releases'][key]

		url = f'https://api.discogs.com/releases/{key}'
		data = self._get(url)
		if data is not None:
			self.cache['releases'][key] = data
		return data

	def get_master_versions(self, master_id: str | int) -> list[dict[str, Any]]:
		key = str(master_id)
		if key in self.cache['master_versions']:
			return self.cache['master_versions'][key]

		url = f'https://api.discogs.com/masters/{key}/versions'
		versions: list[dict[str, Any]] = []
		page = 1
		per_page = 100

		while True:
			data = self._get(url, params={'page': page, 'per_page': per_page})
			if not data or 'versions' not in data:
				break
			versions.extend(data['versions'])
			pagination = data.get('pagination', {})
			if page >= pagination.get('pages', 1) or page >= 3:
				break
			page += 1

		self.cache['master_versions'][key] = versions
		return versions

	def search_master(self, artist: str, album: str) -> str | None:
		search_key = f'{artist.strip().lower()}|{album.strip().lower()}'
		if search_key in self.cache['searches']:
			return self.cache['searches'][search_key]

		url = 'https://api.discogs.com/database/search'
		params = {'artist': artist, 'release_title': album, 'type': 'master', 'per_page': 5}
		data = self._get(url, params=params)
		master_id = None
		if data and 'results' in data and data['results']:
			master_id = str(data['results'][0].get('id', ''))

		self.cache['searches'][search_key] = master_id
		return master_id


def detect_audiophile_format(version: dict[str, Any]) -> tuple[str, str] | None:
	"""Inspect a Discogs release version dict for audiophile indicators."""
	text_sources: list[str] = []

	title = version.get('title', '')
	if title:
		text_sources.append(title)

	fmt = version.get('format', '')
	if isinstance(fmt, str) and fmt:
		text_sources.append(fmt)

	major_formats = version.get('major_formats', [])
	if isinstance(major_formats, list):
		text_sources.extend([str(m) for m in major_formats])

	descriptions = version.get('descriptions', [])
	if isinstance(descriptions, list):
		text_sources.extend([str(d) for d in descriptions])

	formats = version.get('formats', [])
	if isinstance(formats, list):
		for f_item in formats:
			if isinstance(f_item, dict):
				text_sources.append(f_item.get('name', ''))
				text_sources.extend(f_item.get('descriptions', []))
				text_sources.append(f_item.get('text', ''))

	combined_text = ' '.join(filter(None, text_sources))

	for cat_name, desc, pattern in AUDIOPHILE_PATTERNS:
		if pattern.search(combined_text):
			return cat_name, desc

	return None


def normalize_str(s: str) -> str:
	return re.sub(r'\W+', '', s).lower()


def find_audiophile_upgrades(
	input_csv: Path,
	output_csv: Path,
	cache_json: Path,
	limit: int | None = None,
	offline: bool = False,
) -> None:
	if not input_csv.exists():
		logger.error(f'Input CSV file does not exist: {input_csv}')
		sys.exit(1)

	api_key = getattr(config, 'discogs_api_key', getattr(config, 'api_key', ''))
	if not api_key and not offline:
		logger.warning('discogs_api_key not found in config.py. Requests may be rate-limited.')

	client = DiscogsCachedClient(api_key=api_key, cache_path=cache_json, offline=offline)

	library_rows: list[dict[str, str]] = []
	existing_release_ids: set[str] = set()
	existing_formats_by_album: dict[tuple[str, str], set[str]] = {}

	with open(input_csv, 'r', encoding='utf-8-sig') as f:
		reader = csv.DictReader(f)
		for row in reader:
			library_rows.append(row)
			discogs_id = row.get('Discogs Release ID', '').strip()
			if discogs_id and discogs_id.isdigit():
				existing_release_ids.add(discogs_id)

			artist = row.get('Album Artist', '').strip()
			album = row.get('Album', '').strip()
			fmt = row.get('Format', '').strip()
			key = (normalize_str(artist), normalize_str(album))
			if key not in existing_formats_by_album:
				existing_formats_by_album[key] = set()
			if fmt:
				existing_formats_by_album[key].add(fmt.upper())
				for cat_name, _, pattern in AUDIOPHILE_PATTERNS:
					if pattern.search(fmt) or pattern.search(row.get('Edition', '')):
						existing_formats_by_album[key].add(cat_name.upper())

	target_rows: list[dict[str, str]] = []
	for row in library_rows:
		fmt = row.get('Format', '').strip().upper()
		if fmt in ('CD', 'QOBUZ'):
			target_rows.append(row)

	logger.info(
		f'Loaded {len(library_rows)} total library albums. Found {len(target_rows)} target CD/Qobuz albums.'
	)

	if limit is not None and limit > 0:
		target_rows = target_rows[:limit]
		logger.info(f'Limiting search to first {limit} target albums.')

	recommendations: list[dict[str, str]] = []
	processed_masters: set[str] = set()

	is_tty = sys.stderr.isatty()
	console = Console(stderr=True)
	progress = Progress(
		SpinnerColumn(),
		TextColumn('[progress.description]{task.description}'),
		BarColumn(),
		MofNCompleteColumn(),
		TimeRemainingColumn(),
		console=console,
		disable=not is_tty,
	)

	orig_stream = _console_handler.stream
	with progress:
		if is_tty:
			_console_handler.stream = sys.stderr
		try:
			task_id = progress.add_task('Searching audiophile upgrades', total=len(target_rows))

			for row in target_rows:
				artist = row.get('Album Artist', '').strip()
				album = row.get('Album', '').strip()
				current_fmt = row.get('Format', '').strip()
				current_ver = row.get('Version', '').strip()
				current_discogs_id = row.get('Discogs Release ID', '').strip()

				progress.update(
					task_id, description=f'Processing [bold]{artist} - {album}[/bold]', advance=1
				)

				album_key = (normalize_str(artist), normalize_str(album))
				master_id: str | None = None

				if current_discogs_id and current_discogs_id.isdigit():
					rel_data = client.get_release(current_discogs_id)
					if rel_data:
						master_id_val = rel_data.get('master_id')
						if master_id_val:
							master_id = str(master_id_val)

				if not master_id:
					master_id = client.search_master(artist, album)

				if not master_id or master_id in processed_masters:
					continue

				processed_masters.add(master_id)
				versions = client.get_master_versions(master_id)

				seen_formats_for_album: set[str] = set()

				for ver in versions:
					ver_id = str(ver.get('id', ''))
					if ver_id in existing_release_ids:
						continue

					detection = detect_audiophile_format(ver)
					if not detection:
						continue

					cat_name, _cat_desc = detection

					if cat_name.upper() in existing_formats_by_album.get(album_key, set()):
						continue

					if cat_name in seen_formats_for_album:
						continue

					seen_formats_for_album.add(cat_name)

					ver_title = ver.get('title', album)
					ver_year = str(ver.get('released', ver.get('year', '')))
					ver_country = str(ver.get('country', ''))
					ver_catno = str(ver.get('catno', ''))

					recommendations.append(
						{
							'Artist': artist,
							'Album': album,
							'Current Format': current_fmt,
							'Current Version': current_ver,
							'Current Discogs ID': current_discogs_id,
							'Audiophile Format': cat_name,
							'Audiophile Title/Version': ver_title,
							'Release Year': ver_year,
							'Country': ver_country,
							'Catalog Number': ver_catno,
							'Discogs Release ID': ver_id,
							'Discogs Link': f'https://www.discogs.com/release/{ver_id}',
						}
					)

				client.save_cache()

		finally:
			if is_tty:
				_console_handler.stream = orig_stream

	client.save_cache()

	output_csv.parent.mkdir(parents=True, exist_ok=True)
	fieldnames = [
		'Artist',
		'Album',
		'Current Format',
		'Current Version',
		'Current Discogs ID',
		'Audiophile Format',
		'Audiophile Title/Version',
		'Release Year',
		'Country',
		'Catalog Number',
		'Discogs Release ID',
		'Discogs Link',
	]

	with open(output_csv, 'w', encoding='utf-8', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(recommendations)

	success(
		f'Successfully found {len(recommendations)} audiophile upgrade recommendations. Written to {output_csv}'
	)


def main() -> None:
	config_dir = Path(getattr(config, 'config_dir', '.'))

	parser = argparse.ArgumentParser(
		description='Find audiophile album upgrades on Discogs for CD/Qobuz library albums.'
	)
	parser.add_argument(
		'--input',
		'-i',
		type=Path,
		default=config_dir / 'albums.csv',
		help='Path to input albums.csv (default: config_dir/albums.csv)',
	)
	parser.add_argument(
		'--output',
		'-o',
		type=Path,
		default=config_dir / 'audiophile_upgrades.csv',
		help='Path to output CSV (default: config_dir/audiophile_upgrades.csv)',
	)
	parser.add_argument(
		'--cache',
		'-c',
		type=Path,
		default=config_dir / 'audiophile_cache.json',
		help='Path to JSON cache file (default: config_dir/audiophile_cache.json)',
	)
	parser.add_argument(
		'--limit',
		'-l',
		type=int,
		default=None,
		help='Limit the number of target CD/Qobuz albums processed',
	)
	parser.add_argument(
		'--offline',
		action='store_true',
		help='Use only cached Discogs data without making online API requests',
	)

	args = parser.parse_args()

	find_audiophile_upgrades(
		input_csv=args.input,
		output_csv=args.output,
		cache_json=args.cache,
		limit=args.limit,
		offline=args.offline,
	)


if __name__ == '__main__':
	main()
