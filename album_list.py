# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "pandas",
#   "matplotlib",
#   "mutagen",
# ]
# ///

from log import logger
import os
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import taglib
from mutagen.flac import FLAC

ALBUM_TAGS = [
	'ALBUMARTIST', 'ALBUM', 'ALBUM DYNAMIC RANGE', 'ORIGINAL_TITLE',
	'ORIGINAL FILENAME', 'ORIGINALDATE', 'RELEASEDATE', 'CATALOGNUMBER',
	'DISCOGS_RELEASE_ID', 'MUSICBRAINZ_ALBUMID', 'SUBTITLE',
]

DISPLAY_NAMES = {
	'ALBUMARTIST':        'Album Artist',
	'ALBUM':              'Album',
	'ALBUM DYNAMIC RANGE':'DR',
	'ORIGINAL_TITLE':     'Original Title',
	'ORIGINAL FILENAME':  'Original Filename',
	'ORIGINALDATE':       'Original Date',
	'RELEASEDATE':        'Release Date',
	'CATALOGNUMBER':      'Catalog',
	'DISCOGS_RELEASE_ID': 'Discogs',
	'MUSICBRAINZ_ALBUMID':'MusicBrainz',
	'SUBTITLE':           'Version',
	'COVER_ART':          'Cover Art',
}

SCRIPTS_DIR = Path(__file__).parent


def cover_art_dimensions(flac_path: str) -> str:
	"""Return 'WxH' of the first embedded picture, or empty string if none."""
	try:
		audio = FLAC(flac_path)
		if audio.pictures:
			pic = audio.pictures[0]
			return f'{pic.width}x{pic.height}'
	except Exception:
		pass
	return ''


def read_album(directory: str) -> dict | None:
	"""Read album tags from the first FLAC file in the directory."""
	flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
	if not flacs:
		return None
	flac_path = str(PurePosixPath(directory) / flacs[0])
	try:
		with taglib.File(flac_path) as f:
			tags = f.tags
	except Exception:
		return None

	album_result = {tag: (tags.get(tag, [''])[0] or '') for tag in ALBUM_TAGS}
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
		out_df['Directory'] = df['_DIRECTORY_PATH'].values
	out_df.to_csv(out, index=False)


def save_chart(df: pd.DataFrame, out: Path) -> None:
	if 'ALBUM DYNAMIC RANGE' not in df.columns:
		return
	dr = df['ALBUM DYNAMIC RANGE'].fillna('').astype(str).str.strip()
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
	root = sys.argv[1] if len(sys.argv) == 2 else str(__import__('config').flacroot)

	logger.info(f"Scanning {root}")
	flac_dirs = find_flac_dirs(root)
	logger.info(f"Found {len(flac_dirs)} album directories")

	data_dir = Path(os.environ.get('CONFIG_DIR') or getattr(__import__('config'), 'config_dir', '.'))
	data_dir.mkdir(parents=True, exist_ok=True)
	cache_file = data_dir / 'album_cache.json'

	cache = {}
	if cache_file.exists():
		try:
			cache = json.loads(cache_file.read_text(encoding='utf-8'))
		except Exception as e:
			logger.warning(f"Could not load album cache, rebuilding: {e}")

	new_cache = {}
	to_scan = []

	for d in flac_dirs:
		try:
			mtime = os.path.getmtime(d)
		except OSError:
			continue
		entry = cache.get(d)
		if entry and entry.get('mtime') == mtime and 'data' in entry:
			new_cache[d] = entry
		else:
			to_scan.append((d, mtime))

	cache_hits = len(flac_dirs) - len(to_scan)
	if cache_hits > 0:
		logger.info(f"Using cached metadata for {cache_hits}/{len(flac_dirs)} albums")

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
					logger.info(f"Scanned {done}/{len(to_scan)} modified albums")

	try:
		cache_file.write_text(json.dumps(new_cache, indent=2), encoding='utf-8')
	except Exception as e:
		logger.warning(f"Could not save album cache: {e}")

	df = pd.DataFrame(albums)
	save_csv(df, data_dir / 'albums.csv')
	save_chart(df, data_dir / 'albums_dr.png')
	logger.info(f"Done: {len(albums)} albums written to {data_dir / 'albums.csv'}")


if __name__ == '__main__':
	main()
