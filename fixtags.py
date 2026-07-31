#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "requests",
#   "discogs_client",
#   "mutagen",
#   "pillow",
#   "rich",
# ]
# ///

import argparse
import os
import sys
import time
from json import JSONDecodeError
from pathlib import Path, PurePosixPath

from discogs_client.exceptions import HTTPError
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

from log import _console_handler, logger, success


def discogs_fetch(fn, *args, retries: int = 3, backoff: float = 60.0):
	"""Call fn(*args), retrying on rate-limit or empty-response errors.

	The Discogs API may return a 429 HTTPError or an empty body (which surfaces
	as JSONDecodeError) when the rate limit is hit. Both are retried.

	Args:
		fn: Callable that triggers a Discogs API fetch.
		*args: Positional arguments forwarded to fn.
		retries: Maximum number of retry attempts.
		backoff: Seconds to sleep before each retry.

	Returns:
		The return value of fn(*args).

	Raises:
		The last exception if all retries are exhausted.
	"""
	for attempt in range(retries + 1):
		try:
			return fn(*args)
		except (JSONDecodeError, HTTPError) as e:
			if attempt < retries:
				logger.warning(
					f'Discogs API error ({type(e).__name__}), sleeping {backoff}s (attempt {attempt + 1}/{retries})'
				)
				time.sleep(backoff)
			else:
				raise


# import music libraries
# https://github.com/joalla/discogs_client
# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
import io

import discogs_client

# https://github.com/supermihi/pytaglib
import taglib
from mutagen.flac import FLAC, Picture
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

from config import discogs_api_key as api_key

try:
	from config import cover_max_size as _cover_max_size
except ImportError:
	_cover_max_size = 1500


def resize_covers(directory: str, max_size: int = _cover_max_size) -> None:
	"""Resize embedded cover art in all FLACs in directory if larger than max_size px."""
	album_name = Path(directory).name
	for flac_path in sorted(Path(directory).glob('*.flac')):
		try:
			audio = FLAC(str(flac_path))
			if not audio.pictures:
				continue
			changed = False
			new_pictures = []
			for pic in audio.pictures:
				if (
					pic.mime not in ('image/jpeg', 'image/png')
					or not pic.data
					or len(pic.data) < 100
				):
					new_pictures.append(pic)
					continue
				try:
					img = Image.open(io.BytesIO(pic.data))
					img.load()
				except Exception as err:  # noqa: BLE001
					logger.warning(f'Corrupt or unparseable embedded image in {flac_path}: {err}')
					new_pictures.append(pic)
					continue
				w, h = img.size
				if w <= max_size and h <= max_size:
					new_pictures.append(pic)
					continue
				img.thumbnail((max_size, max_size), Image.LANCZOS)
				buf = io.BytesIO()
				img.save(buf, format='JPEG', quality=90)
				new_pic = Picture()
				new_pic.type = pic.type
				new_pic.desc = pic.desc
				new_pic.mime = 'image/jpeg'
				new_pic.width, new_pic.height = img.size
				new_pic.depth = 24
				new_pic.data = buf.getvalue()
				new_pictures.append(new_pic)
				orig_size = f'{w}x{h}'
				changed = True
			if changed:
				audio.clear_pictures()
				for pic in new_pictures:
					audio.add_picture(pic)
				audio.save()
				success(
					f'Album art resized {orig_size} → {new_pictures[-1].width}x{new_pictures[-1].height} in {album_name}'
				)
		except Exception as e:
			logger.warning(f'Cover resize failed for {flac_path}: {e}')


# extract a single FLAC tag
def flactag(song: FLAC | dict, tag: str, required: bool = False) -> str:
	"""Extract a single tag value from a FLAC file's metadata.

	Args:
	    song: Mutagen FLAC object or dict with loaded tags.
	    tag: Tag key to retrieve (e.g. 'ALBUM', 'ARTIST').
	    required: If True, log an error when the tag is missing.

	Returns:
	    First value for the tag, or empty string if the key is absent.
	"""
	tags = song.tags if isinstance(song, FLAC) and song.tags else song
	if not isinstance(tags, dict):
		try:
			tags = dict(tags)
		except Exception:
			tags = {}

	# Try exact key or uppercase/lowercase key
	for k in (tag, tag.upper(), tag.lower()):
		if k in tags and tags[k]:
			val = tags[k]
			return str(val[0]) if isinstance(val, (list, tuple)) else str(val)

	if required:
		logger.error(f'Tag Error: {tag} missing in FLAC metadata')
	return ''


# fix tags for a single album (in a single directory)
def fixdir(fixdir: str, dclient: discogs_client.Client) -> None:
	"""Enrich all FLAC files in a single album directory with Discogs metadata.

	Reads the DISCOGS_RELEASE_ID tag from the first FLAC file found, queries the
	Discogs API for release and master-release data, then updates every FLAC file in
	the directory with a normalised set of tags:

	    RELEASEDATE / DATE    – release year of this specific pressing
	    ORIGINALDATE / ORIGINALRELEASEDATE – year of the master (original) release
	    ALBUM                 – formatted title: "<name> [<year> <desc> <kHz>DR<dr>]"
	    ORIGINAL_TITLE        – canonical Discogs title (from master release if available)

	Skips the directory silently if no FLAC files exist or if DISCOGS_RELEASE_ID is
	missing / non-numeric. Sleeps 1 second after each Discogs API call to respect the
	rate limit.

	Args:
	    fixdir: Absolute path to the album directory to process.
	    dclient: Authenticated Discogs client instance.
	"""
	flac_files = 0
	first_flac = next(
		(filename for filename in os.listdir(fixdir) if filename.endswith('.flac')), None
	)
	if first_flac is not None:
		first_flac_path = os.path.join(fixdir, first_flac)
	else:
		return
	try:
		audio = FLAC(first_flac_path)
		first_tags = (
			{k.upper(): [str(x) for x in v] for k, v in audio.tags.items()} if audio.tags else {}
		)
		first_sample_rate = audio.info.sample_rate if audio.info else 44100
	except Exception as e:
		logger.warning(f'Skipping unreadable file {first_flac_path}: {e}')
		return

	discogs = True
	try:
		discogs_id_str = first_tags.get('DISCOGS_RELEASE_ID', [''])[0]
		discogs_id = int(discogs_id_str)
	except (ValueError, IndexError):
		discogs = False
		return
	# if we found discogs tags to work with go ahead
	if discogs:
		drelease = discogs_fetch(dclient.release, discogs_id)

		release_title = discogs_fetch(lambda: drelease.title.strip())
		try:
			master = discogs_fetch(lambda: drelease.master)
			master_title = discogs_fetch(lambda: master.title.strip()) if master else release_title
		except Exception:  # noqa: BLE001
			master = None
			master_title = release_title

		album_override = first_tags.get('ALBUM_TITLE_OVERRIDE', [''])[0]
		album_name = album_override or master_title

		# Sample rate & resolution
		def _read_sr(filepath: str) -> int:
			try:
				f = FLAC(filepath)
				return f.info.sample_rate if f.info else 0
			except Exception:  # noqa: BLE001
				return 0

		max_rate_hz = max(
			(_read_sr(str(p)) for p in Path(fixdir).rglob('*.flac') if p.suffix == '.flac'),
			default=first_sample_rate,
		)
		max_res_str = (
			f'{max_rate_hz / 1000:.1f}kHz'.replace('.0kHz', 'kHz') if max_rate_hz > 0 else '44.1kHz'
		)

		try:
			album_year_release = int(
				first_tags.get('ALBUM_RELEASE_YEAR', [''])[0] or first_tags.get('DATE', [''])[0]
			)
		except ValueError:
			album_year_release = drelease.year
		try:
			album_year_master = (
				discogs_fetch(lambda: master.main_release.year) if master else album_year_release
			)
		except Exception:  # noqa: BLE001
			logger.warning(
				f'Could not fetch master release year for Discogs ID {discogs_id} in {fixdir}, using release year'
			)
			album_year_master = album_year_release
		if album_year_release == 0 and album_year_master != 0:
			album_year_release = album_year_master
		if album_year_release != 0 and album_year_master == 0:
			album_year_master = album_year_release

		subtitle = first_tags.get('SUBTITLE', [''])[0].strip()
		album_format = first_tags.get('ALBUM_FORMAT', [''])[0] or subtitle or 'CD'
		album_edition = first_tags.get('ALBUM_EDITION', [''])[0]

		dr_rating = (
			first_tags.get('ALBUM_DR', [''])[0]
			or first_tags.get('ALBUM DYNAMIC RANGE', [''])[0].strip()
			or ''
		)

		ed_str = f' ({album_edition})' if album_edition else ''
		yr_str = f' {album_year_release}' if album_year_release else ''
		fmt_str = f' {album_format}' if album_format else ''
		album_newtitle = f'{album_name} [{yr_str.strip()}{fmt_str}{ed_str}]'

		new_tags = {
			'RELEASEDATE': [str(album_year_release)],
			'DATE': [str(album_year_release)],
			'YEAR': [str(album_year_release)],
			'ORIGINALDATE': [str(album_year_master)],
			'ORIGINALRELEASEDATE': [str(album_year_master)],
			'ORIGINAL DATE': [str(album_year_master)],
			'ORIGINAL YEAR': [str(album_year_master)],
			'ALBUM_MASTER_TITLE': [master_title],
			'ALBUM_RELEASE_TITLE': [release_title],
			'ALBUM_MASTER_YEAR': [str(album_year_master)],
			'ALBUM_RELEASE_YEAR': [str(album_year_release)],
			'ALBUM_FORMAT': [album_format],
			'ALBUM_MAX_RESOLUTION': [max_res_str],
			'ALBUM': [album_newtitle],
			'ORIGINAL_TITLE': [master_title],
		}
		if album_edition:
			new_tags['ALBUM_EDITION'] = [album_edition]
		if dr_rating:
			new_tags['ALBUM_DR'] = [dr_rating]

		try:
			country = discogs_fetch(lambda: drelease.country.strip())
			if country:
				new_tags['ALBUM_RELEASE_COUNTRY'] = [country]
		except Exception:  # noqa: BLE001
			pass

		try:
			labels = discogs_fetch(lambda: drelease.labels)
			if labels and len(labels) > 0:
				label_name = labels[0].name.strip()
				if label_name:
					new_tags['ALBUM_RELEASE_LABEL'] = [label_name]
		except Exception:  # noqa: BLE001
			pass

		managed_optional = [
			'ALBUM_EDITION',
			'ALBUM_DR',
			'ALBUM_RELEASE_COUNTRY',
			'ALBUM_RELEASE_LABEL',
		]
		for p in Path(fixdir).rglob('*.flac'):
			fullfilename = str(PurePosixPath(p))
			try:
				audio = FLAC(fullfilename)
				if not audio.tags:
					audio.add_tags()

				stale_removed = False
				for opt_tag in managed_optional:
					if opt_tag not in new_tags and opt_tag in audio.tags:
						audio.tags.pop(opt_tag, None)
						stale_removed = True

				needs_update = stale_removed or any(
					[str(x) for x in audio.tags.get(k, [])] != v for k, v in new_tags.items()
				)

				if needs_update:
					for k, v in new_tags.items():
						audio[k] = v
					try:
						audio.save()
						try:
							os.utime(fullfilename, None)
						except Exception as e:
							logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
						flac_files += 1
					except Exception as e:
						logger.warning(f'Could not save tags for {fullfilename}: {e}')
			except Exception as e:
				logger.warning(f'Skipping unreadable file {fullfilename}: {e}')

		if flac_files > 0:
			success(f'Album name changed to {album_newtitle}')
		else:
			logger.info(f'No changes required for {album_newtitle}')
		resize_covers(fixdir)
	else:
		logger.error(f'No Discogs release ID found in {fixdir}')


def main() -> None:
	"""Entry point: locate all FLAC album directories and apply Discogs tag enrichment.

	Accepts an optional positional directory argument; falls back to flacdir from
	config.py when none is given. Creates a single authenticated Discogs client and
	processes each discovered album directory in sequence.
	"""
	parser = argparse.ArgumentParser(description='Fix FLAC file tags using Discogs metadata')
	parser.add_argument('directory', nargs='?', help='directory containing FLAC files to process')
	args = parser.parse_args()

	if args.directory:
		flacdir = args.directory
	else:
		import config

		flacdir = config.nzbdir

	flac_directories = []
	for root, dirs, files in os.walk(flacdir):
		for file in files:
			if file.endswith('.flac'):
				flac_directories.append(root)
				break

	dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)

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
			task_id = progress.add_task('Fixing tags', total=len(flac_directories))
			for directory in flac_directories:
				fixdir(directory, dclient)
				progress.update(task_id, advance=1)
		finally:
			if is_tty:
				_console_handler.stream = orig_stream


if __name__ == '__main__':
	main()
