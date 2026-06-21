# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "pandas",
#   "matplotlib",
#   "mutagen",
#   "pillow",
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
import io
import taglib
from mutagen.flac import FLAC
from PIL import Image

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
			img = Image.open(io.BytesIO(audio.pictures[0].data))
			return f'{img.width}x{img.height}'
	except Exception:
		pass
	return ''


def read_album(directory: str, lyrics_dir: Path | None = None) -> dict | None:
	"""Read album tags from the first FLAC; write per-track lyrics to lyrics_dir if given."""
	flacs = sorted(f for f in os.listdir(directory) if f.endswith('.flac'))
	if not flacs:
		return None
	album_result = None
	for i, fname in enumerate(flacs):
		flac_path = str(PurePosixPath(directory) / fname)
		try:
			with taglib.File(flac_path) as f:
				tags = f.tags
		except Exception:
			continue
		if i == 0:
			album_result = {tag: (tags.get(tag, [''])[0] or '') for tag in ALBUM_TAGS}
			album_result['COVER_ART'] = cover_art_dimensions(flac_path)
			album_result['_DIRECTORY_PATH'] = directory
		if lyrics_dir is not None:
			discogs_id = (tags.get('DISCOGS_RELEASE_ID') or [''])[0].strip()
			lyrics = (tags.get('LYRICS') or [''])[0].strip()
			if discogs_id and lyrics:
				track = (tags.get('TRACKNUMBER') or ['0'])[0].split('/')[0].zfill(2)
				ext = 'lrc' if lyrics.startswith('[') else 'txt'
				(lyrics_dir / f'{discogs_id}_{track}.{ext}').write_text(lyrics, encoding='utf-8')
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
	lyrics_dir = data_dir / 'lyrics'
	lyrics_dir.mkdir(parents=True, exist_ok=True)

	workers = min(32, (os.cpu_count() or 4) * 4)
	albums = []
	with ThreadPoolExecutor(max_workers=workers) as pool:
		futures = {pool.submit(read_album, d, lyrics_dir): d for d in flac_dirs}
		done = 0
		for fut in as_completed(futures):
			done += 1
			result = fut.result()
			if result:
				albums.append(result)
			if done % 50 == 0 or done == len(flac_dirs):
				logger.info(f"{done}/{len(flac_dirs)} scanned, {len(albums)} albums")

	df = pd.DataFrame(albums)
	save_csv(df, data_dir / 'albums.csv')
	save_chart(df, data_dir / 'albums_dr.png')
	logger.info(f"Done: {len(albums)} albums written to {data_dir / 'albums.csv'}")


if __name__ == '__main__':
	main()
