#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "pandas",
#   "matplotlib",
#   "mutagen",
# ]
# ///

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import matplotlib

from log import logger

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from mutagen.flac import FLAC

ALBUM_TAGS = [
	'ALBUMARTIST',
	'ALBUM',
	'VERSION',
	'ALBUM_DR',
	'ALBUM_FORMAT',
	'ALBUM_EDITION',
	'ORIGINAL_TITLE',
	'ORIGINAL FILENAME',
	'ORIGINALDATE',
	'RELEASEDATE',
	'CATALOGNUMBER',
	'DISCOGS_RELEASE_ID',
	'MUSICBRAINZ_ALBUMID',
	'SUBTITLE',
]

DISPLAY_NAMES = {
	'ALBUMARTIST': 'Album Artist',
	'ALBUM': 'Album',
	'VERSION': 'Version',
	'ALBUM_DR': 'DR',
	'ALBUM_FORMAT': 'Format',
	'ALBUM_EDITION': 'Edition',
	'ORIGINAL_TITLE': 'Original Title',
	'ORIGINAL FILENAME': 'Original Filename',
	'ORIGINALDATE': 'Original Date',
	'RELEASEDATE': 'Release Date',
	'CATALOGNUMBER': 'Catalog Number',
	'DISCOGS_RELEASE_ID': 'Discogs Release ID',
	'MUSICBRAINZ_ALBUMID': 'MusicBrainz Album ID',
	'SUBTITLE': 'Subtitle',
	'COVER_ART': 'Cover Art',
}

SCRIPTS_DIR = Path(__file__).parent


def cover_art_dimensions(flac_path: str) -> str:
	"""Read embedded FLAC cover art and return 'WIDTHxHEIGHT' or empty string."""
	try:
		audio = FLAC(flac_path)
		if audio.pictures:
			pic = audio.pictures[0]
			return f'{pic.width}x{pic.height}'
	except Exception:  # noqa: BLE001
		pass
	return ''


def read_album(directory: str) -> dict[str, str] | None:
	"""Read first FLAC in directory and return dict of album tags + COVER_ART + _DIRECTORY_PATH."""
	flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
	if not flacs:
		return None
	flac_path = os.path.join(directory, flacs[0])
	try:
		audio = FLAC(flac_path)
		tags = {k.upper(): [str(x) for x in v] for k, v in audio.tags.items()} if audio.tags else {}
	except Exception:
		return None

	album_result = {tag: (tags.get(tag, [''])[0] or '') for tag in ALBUM_TAGS}
	artist_override = tags.get('ALBUM_ARTIST_OVERRIDE', [''])[0]
	if artist_override:
		album_result['ALBUMARTIST'] = artist_override
	title_override = tags.get('ALBUM_TITLE_OVERRIDE', [''])[0]
	master_title = tags.get('ALBUM_MASTER_TITLE', [''])[0]
	orig_title = tags.get('ORIGINAL_TITLE', [''])[0]
	if title_override:
		album_result['ALBUM'] = title_override
	elif master_title:
		album_result['ALBUM'] = master_title
	elif orig_title:
		album_result['ALBUM'] = orig_title
	else:
		alb = album_result.get('ALBUM', '')
		if '[' in alb:
			alb = alb.split('[')[0].strip()
		album_result['ALBUM'] = alb
	if not album_result.get('VERSION'):
		album_result['VERSION'] = (
			tags.get('VERSION', [''])[0] or tags.get('SUBTITLE', [''])[0] or ''
		)
	if not album_result.get('ALBUM_DR'):
		album_result['ALBUM_DR'] = tags.get('ALBUM DYNAMIC RANGE', [''])[0] or ''
	album_result['COVER_ART'] = cover_art_dimensions(flac_path)
	album_result['_DIRECTORY_PATH'] = directory
	return album_result


def find_flac_dirs(root: str) -> list[str]:
	"""Walk root and return directories that contain at least one FLAC file."""
	dirs = []
	for dirpath, _, files in os.walk(root):
		if any(f.endswith('.flac') for f in files):
			dirs.append(dirpath)
	return dirs


def save_csv(df: pd.DataFrame, out: Path) -> None:
	existing = [t for t in ALBUM_TAGS + ['COVER_ART'] if t in df.columns]
	out_df = df[existing].rename(columns=DISPLAY_NAMES)
	if '_DIRECTORY_PATH' in df.columns:
		out_df['_DIRECTORY_PATH'] = df['_DIRECTORY_PATH'].values
		out_df['Directory'] = df['_DIRECTORY_PATH'].values
	out_df.to_csv(out, index=False)


def save_chart(df: pd.DataFrame, out: Path) -> None:
	dr_col = 'ALBUM_DR' if 'ALBUM_DR' in df.columns else 'ALBUM DYNAMIC RANGE'
	if dr_col not in df.columns:
		return
	dr = df[dr_col].fillna('').astype(str).str.strip()
	dr = dr[dr != '']
	if dr.empty:
		return
	counts = dr.value_counts().sort_index()
	cmap = plt.get_cmap('RdYlGn')
	colors = [cmap(i / max(len(counts) - 1, 1)) for i in range(len(counts))]
	plt.figure(figsize=(10, 5))
	counts.plot(kind='bar', color=colors)
	plt.title('Albums per DR value')
	plt.xlabel('Album DR')
	plt.ylabel('Number of albums')
	plt.tight_layout()
	plt.savefig(out, dpi=150)
	plt.close()


def main() -> None:
	"""Scan FLAC library, build albums.csv and DR distribution chart.

	Supports caching via album_cache.json based on max file mtime per album.
	Use --force / -f to bypass the cache and force a full re-scan.
	"""
	import argparse

	parser = argparse.ArgumentParser(description='Scan FLAC library and generate albums.csv')
	parser.add_argument('directory', nargs='?', help='Root directory of the FLAC library')
	parser.add_argument(
		'-f', '--force', action='store_true', help='Force full rescan ignoring album_cache.json'
	)
	args = parser.parse_args()

	if args.directory:
		root = args.directory
	else:
		import config

		root = config.flacroot

	logger.info(f'Scanning {root}')
	flac_dirs = find_flac_dirs(root)
	logger.info(f'Found {len(flac_dirs)} album directories')

	data_dir = Path(
		os.environ.get('CONFIG_DIR') or getattr(__import__('config'), 'config_dir', '.')
	)
	data_dir.mkdir(parents=True, exist_ok=True)
	cache_file = data_dir / 'album_cache.json'

	cache = {}
	if not args.force and cache_file.exists():
		try:
			cache = json.loads(cache_file.read_text(encoding='utf-8'))
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not load album cache, rebuilding: {e}')

	new_cache = {}
	to_scan = []

	for d in flac_dirs:
		try:
			flacs = sorted(f for f in os.listdir(d) if f.endswith('.flac'))
			if not flacs:
				continue
			mtime = max(os.path.getmtime(os.path.join(d, f)) for f in flacs)
		except OSError:
			continue
		entry = cache.get(d)
		if entry and entry.get('mtime') == mtime and 'data' in entry:
			new_cache[d] = entry
		else:
			to_scan.append((d, mtime))

	cache_hits = len(flac_dirs) - len(to_scan)
	if cache_hits > 0:
		logger.info(f'Using cached metadata for {cache_hits}/{len(flac_dirs)} albums')

	albums = [entry['data'] for entry in new_cache.values()]

	if to_scan:
		workers = min(32, (os.cpu_count() or 4) * 4)
		with ThreadPoolExecutor(max_workers=workers) as pool:
			futures = {pool.submit(read_album, d): (d, mtime) for d, mtime in to_scan}
			done = 0
			for fut in as_completed(futures):
				d, mtime = futures[fut]
				done += 1
				result = fut.result()
				if result:
					albums.append(result)
					new_cache[d] = {'mtime': mtime, 'data': result}
				if done % 50 == 0 or done == len(to_scan):
					logger.info(f'Scanned {done}/{len(to_scan)} modified albums')

	try:
		cache_file.write_text(json.dumps(new_cache, indent=2), encoding='utf-8')
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not save album cache: {e}')

	df = pd.DataFrame(albums)
	save_csv(df, data_dir / 'albums.csv')
	save_chart(df, data_dir / 'albums_dr.png')
	logger.info(f'Done: {len(albums)} albums written to {data_dir / "albums.csv"}')


if __name__ == '__main__':
	main()
