# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "pandas",
#   "matplotlib",
# ]
# ///

from log import logger
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import taglib

ALBUM_TAGS = [
	'ALBUMARTIST', 'ALBUM', 'ALBUM DYNAMIC RANGE', 'ORIGINAL_TITLE',
	'ORIGINALDATE', 'RELEASEDATE', 'CATALOGNUMBER',
	'DISCOGS_RELEASE_ID', 'MUSICBRAINZ_ALBUMID', 'SUBTITLE',
]

DISPLAY_NAMES = {
	'ALBUMARTIST':        'Album Artist',
	'ALBUM':              'Album',
	'ALBUM DYNAMIC RANGE':'DR',
	'ORIGINAL_TITLE':     'Original Title',
	'ORIGINALDATE':       'Original Date',
	'RELEASEDATE':        'Release Date',
	'CATALOGNUMBER':      'Catalog',
	'DISCOGS_RELEASE_ID': 'Discogs',
	'MUSICBRAINZ_ALBUMID':'MusicBrainz',
	'SUBTITLE':           'Version',
}

SCRIPTS_DIR = Path(__file__).parent


def read_album(directory: str) -> dict | None:
	"""Read album tags from the first FLAC file in directory. Returns None if no FLACs."""
	first_flac = next((f for f in os.listdir(directory) if f.endswith('.flac')), None)
	if not first_flac:
		return None
	try:
		with taglib.File(str(PurePosixPath(directory) / first_flac)) as f:
			tags = f.tags
	except Exception:
		return None
	result = {tag: (tags.get(tag, [''])[0] or '') for tag in ALBUM_TAGS}
	result['_DIRECTORY_PATH'] = directory
	return result


def find_flac_dirs(root: str) -> list[str]:
	"""Walk root and return directories that contain at least one FLAC file."""
	dirs = []
	for dirpath, _, files in os.walk(root):
		if any(f.endswith('.flac') for f in files):
			dirs.append(dirpath)
	return dirs


def save_csv(df: pd.DataFrame, out: Path) -> None:
	existing = [t for t in ALBUM_TAGS if t in df.columns]
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

	workers = min(32, (os.cpu_count() or 4) * 4)
	albums = []
	with ThreadPoolExecutor(max_workers=workers) as pool:
		futures = {pool.submit(read_album, d): d for d in flac_dirs}
		done = 0
		for fut in as_completed(futures):
			done += 1
			result = fut.result()
			if result:
				albums.append(result)
			if done % 50 == 0 or done == len(flac_dirs):
				logger.info(f"{done}/{len(flac_dirs)} scanned, {len(albums)} albums")

	import os as _os
	data_dir = Path(_os.environ.get('CONFIG_DIR') or getattr(__import__('config'), 'config_dir', '.'))
	data_dir.mkdir(parents=True, exist_ok=True)
	df = pd.DataFrame(albums)
	save_csv(df, data_dir / 'albums.csv')
	save_chart(df, data_dir / 'albums_dr.png')
	logger.info(f"Done: {len(albums)} albums written to {data_dir / 'albums.csv'}")


if __name__ == '__main__':
	main()
