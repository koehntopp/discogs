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
from mutagen.flac import Picture
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

from config import discogs_api_key as api_key

try:
	from config import cover_max_size as _cover_max_size
except ImportError:
	_cover_max_size = 1500

try:
	from config import musicbrainz_languages as _musicbrainz_languages
except ImportError:
	_musicbrainz_languages = True

import musicbrainz_client
from disc_layout import album_root

LANGUAGE_TAG = 'LYRICS_LANGUAGE'


def resize_covers(directory: str, max_size: int = _cover_max_size) -> None:
	"""Resize embedded cover art in all FLACs in directory if larger than max_size px."""
	album_name = Path(directory).name
	for flac_path in sorted(Path(directory).rglob('*.flac')):
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
		except Exception as e:  # noqa: BLE001
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
		except Exception:  # noqa: BLE001
			tags = {}

	# Try exact key or uppercase/lowercase key
	for k in (tag, tag.upper(), tag.lower()):
		if tags.get(k):
			val = tags[k]
			return str(val[0]) if isinstance(val, (list, tuple)) else str(val)

	if required:
		logger.error(f'Tag Error: {tag} missing in FLAC metadata')
	return ''


# fix tags for a single album (in a single directory)
def musicbrainz_release_id(tags: dict[str, list[str]]) -> str:
	"""The user-set MusicBrainz release id (not the release-group id) from upper-cased tags."""
	for key in ('MUSICBRAINZ_ALBUMID', 'MUSICBRAINZ ALBUM ID'):
		values = tags.get(key)
		if values and values[0].strip():
			return values[0].strip()
	return ''


def load_language_release(first_tags: dict[str, list[str]], refresh: bool = False) -> dict | None:
	"""The album's parsed MusicBrainz release, or None: switched off in config, no
	MUSICBRAINZ_ALBUMID, or MusicBrainz could not be asked (then language tags stay as they are)."""
	if not _musicbrainz_languages:
		return None
	mbid = musicbrainz_release_id(first_tags)
	if not mbid:
		return None
	try:
		import config

		base = Path(os.environ.get('CONFIG_DIR') or config.config_dir)
	except (ImportError, AttributeError):
		base = Path('.')
	release = musicbrainz_client.release_languages(mbid, base / 'musicbrainz', refresh)
	if release is None:
		logger.warning(
			f'MusicBrainz lookup failed for release {mbid}; {LANGUAGE_TAG} left as it is'
		)
	return release


def _leading_int(value: str, default: int) -> int:
	try:
		return int(value.split('/')[0].strip())
	except ValueError:
		return default


def apply_language(audio: FLAC, release: dict | None) -> bool:
	"""Set (or remove) LYRICS_LANGUAGE on one file from the MusicBrainz release; True if it changed.

	A file that cannot be matched to a MusicBrainz track (another edition of the album) keeps whatever
	it has; a matched track with no sung language loses the tool-owned tag.
	"""
	if release is None or audio.tags is None:
		return False
	tags = audio.tags
	track = musicbrainz_client.find_track(
		release,
		tags.get('MUSICBRAINZ_RELEASETRACKID', [''])[0].strip(),
		_leading_int(tags.get('DISCNUMBER', ['1'])[0], 1),
		_leading_int(tags.get('TRACKNUMBER', ['0'])[0], 0),
		tags.get('TITLE', [''])[0],
	)
	if track is None:
		return False
	wanted = track['languages']
	if [str(x) for x in tags.get(LANGUAGE_TAG, [])] == wanted:
		return False
	if wanted:
		audio[LANGUAGE_TAG] = wanted
	elif LANGUAGE_TAG in tags:
		del tags[LANGUAGE_TAG]
	else:
		return False
	return True


def fix_languages(album_dir: str, refresh: bool = False) -> None:
	"""--languages-only: write only LYRICS_LANGUAGE for one album (no Discogs, no other tag)."""
	files = sorted(Path(album_dir).rglob('*.flac'))
	if not files:
		return
	try:
		first = FLAC(str(files[0]))
		first_tags = (
			{k.upper(): [str(x) for x in v] for k, v in first.tags.items()} if first.tags else {}
		)
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Skipping unreadable file {files[0]}: {e}')
		return
	release = load_language_release(first_tags, refresh)
	if release is None:
		return
	changed = 0
	for path in files:
		try:
			audio = FLAC(str(path))
			if not audio.tags:
				audio.add_tags()
			if apply_language(audio, release):
				audio.save()
				try:
					os.utime(path, None)
				except Exception as e:  # noqa: BLE001
					logger.warning(f'Could not touch file mtime for {path}: {e}')
				changed += 1
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not update {LANGUAGE_TAG} in {path}: {e}')
	name = Path(album_dir).name
	if changed:
		success(f'{LANGUAGE_TAG} updated on {changed} track(s) in {name}')
	else:
		logger.info(f'{LANGUAGE_TAG} already up to date in {name}')


def fixdir(fixdir: str, dclient: discogs_client.Client, refresh_musicbrainz: bool = False) -> None:
	"""Enrich all FLAC files in a single album directory with Discogs metadata.

	Reads the DISCOGS_RELEASE_ID tag from the first FLAC file found, queries the
	Discogs API for release and master-release data, then updates every FLAC file in
	the directory with a normalised set of tags:

	    RELEASEDATE / DATE    – release year of this specific pressing
	    ORIGINALDATE / ORIGINALRELEASEDATE – year of the master (original) release
	    ALBUM                 – formatted title: "<name> [<year> <desc> <kHz>DR<dr>]"
	    ORIGINAL_TITLE        – canonical Discogs title (from master release if available)

	Also writes DISCSUBTITLE per track (not uniformly like the tags above): that track's
	own SET SUBTITLE when present, which Roon shows as the disc title of a box set.
	PART and WORK (written by earlier versions) are removed where set; the old code is kept
	commented out in the per-file loop.

	Also writes LYRICS_LANGUAGE per track from MusicBrainz (the sung language of the track's
	work, ISO 639-3), anchored by the user-set MUSICBRAINZ_ALBUMID; see apply_language.

	If ALBUM_ARTIST_OVERRIDE is set, it's written into ALBUMARTIST (uniformly,
	like ALBUM/VERSION) -- a manual correction, not something derived from
	Discogs. Left entirely untouched when the override is absent.

	Skips the directory silently if no FLAC files exist or if DISCOGS_RELEASE_ID is
	missing / non-numeric. Sleeps 1 second after each Discogs API call to respect the
	rate limit.

	Args:
	    fixdir: Absolute path to the album directory to process.
	    dclient: Authenticated Discogs client instance.
	"""
	flac_files = 0
	first_flac_path = next((str(p) for p in sorted(Path(fixdir).rglob('*.flac'))), None)
	if first_flac_path is None:
		return
	try:
		audio = FLAC(first_flac_path)
		first_tags = (
			{k.upper(): [str(x) for x in v] for k, v in audio.tags.items()} if audio.tags else {}
		)
		first_sample_rate = audio.info.sample_rate if audio.info else 44100
	except Exception as e:  # noqa: BLE001
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

		# ALBUM_ARTIST_OVERRIDE only ever corrects a wrong ALBUMARTIST manually --
		# no Discogs-derived artist data is fetched or stored for this. When absent,
		# ALBUMARTIST is left entirely alone (not part of new_tags at all).
		album_artist_override = first_tags.get('ALBUM_ARTIST_OVERRIDE', [''])[0].strip()

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

		# Tool-written tags are never read back as input: the release year comes only from
		# the Discogs release, so it always follows DISCOGS_RELEASE_ID.
		release_year = int(drelease.year or 0)
		album_year_release = release_year
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

		catalog_number = (
			first_tags.get('CATALOGNUMBER', [''])[0]
			or first_tags.get('CATALOG NUMBER', [''])[0]
			or first_tags.get('CATALOG_NUMBER', [''])[0]
			or first_tags.get('CATALOGNO', [''])[0]
			or ''
		).strip()

		dr_str = ''
		if dr_rating:
			try:
				dr_str = f'DR{int(dr_rating):02d}'
			except ValueError:
				dr_str = ''

		ed_str = f' ({album_edition})' if album_edition else ''
		yr_str = f'{album_year_release}' if album_year_release else ''
		fmt_str = f' {album_format}' if album_format else ''
		dr_part = f' {dr_str}' if dr_str else ''
		cat_part = f' ({catalog_number})' if catalog_number else ''
		version_str = f'{yr_str}{dr_part}{fmt_str}{ed_str}{cat_part}'.strip()

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
			'ALBUM_FORMAT': [album_format],
			'ALBUM_MAX_RESOLUTION': [max_res_str],
			'ALBUM': [album_name],
			'VERSION': [version_str],
			'ORIGINAL_TITLE': [master_title],
		}
		if release_year:
			new_tags['ALBUM_RELEASE_YEAR'] = [str(release_year)]
		if album_edition:
			new_tags['ALBUM_EDITION'] = [album_edition]
		if dr_rating:
			new_tags['ALBUM_DR'] = [dr_rating]
		if album_artist_override:
			new_tags['ALBUMARTIST'] = [album_artist_override]

		try:
			country = discogs_fetch(lambda: drelease.country.strip())
			if country:
				new_tags['ALBUM_RELEASE_COUNTRY'] = [country]
		except Exception:  # noqa: BLE001, S110  # optional tag: skipped when Discogs has no value
			pass

		try:
			labels = discogs_fetch(lambda: drelease.labels)
			if labels and len(labels) > 0:
				label_name = labels[0].name.strip()
				if label_name:
					new_tags['ALBUM_RELEASE_LABEL'] = [label_name]
		except Exception:  # noqa: BLE001, S110  # optional tag: skipped when Discogs has no value
			pass

		mb_release = load_language_release(first_tags, refresh_musicbrainz)
		managed_optional = [
			'ALBUM_EDITION',
			'ALBUM_DR',
			'ALBUM_RELEASE_YEAR',
			'ALBUM_RELEASE_COUNTRY',
			'ALBUM_RELEASE_LABEL',
		]
		for p in Path(fixdir).rglob('*.flac'):
			fullfilename = str(PurePosixPath(p))
			if not os.path.isfile(fullfilename):
				continue
			try:
				audio = FLAC(fullfilename)
				if not audio.tags:
					audio.add_tags()

				# DISCSUBTITLE is per-track (Roon box-set disc title): it comes from
				# each track's own SET SUBTITLE (a tag the user sets manually on
				# discs within multi-disc editions, so it varies track to track
				# within a single fixdir), not from the uniform album-level new_tags.
				set_subtitle = audio.tags.get('SET SUBTITLE', [''])[0].strip()
				disc_subtitle_changed = bool(set_subtitle) and [
					str(x) for x in audio.tags.get('DISCSUBTITLE', [])
				] != [set_subtitle]
				disc_subtitle_stale = not set_subtitle and 'DISCSUBTITLE' in audio.tags

				# WORK/PART (Roon grouping by work, replaced by DISCSUBTITLE) are removed where set.
				# The previous per-track writer is kept for reference:
				# title = audio.tags.get('TITLE', [''])[0].strip()
				# part_changed = bool(title) and [str(x) for x in audio.tags.get('PART', [])] != [title]
				# work_changed = bool(set_subtitle) and [
				# 	str(x) for x in audio.tags.get('WORK', [])
				# ] != [set_subtitle]
				# work_stale = not set_subtitle and 'WORK' in audio.tags
				legacy_grouping = [t for t in ('WORK', 'PART') if t in audio.tags]

				language_changed = apply_language(audio, mb_release)
				stale_removed = bool(legacy_grouping) or disc_subtitle_stale or language_changed
				for opt_tag in managed_optional:
					if opt_tag not in new_tags and opt_tag in audio.tags:
						del audio.tags[opt_tag]
						stale_removed = True

				needs_update = (
					stale_removed
					or disc_subtitle_changed
					or any(
						[str(x) for x in audio.tags.get(k, [])] != v for k, v in new_tags.items()
					)
				)

				if needs_update:
					for k, v in new_tags.items():
						audio[k] = v
					for legacy_tag in legacy_grouping:
						del audio.tags[legacy_tag]
					# if title:
					# 	audio['PART'] = [title]
					# if set_subtitle:
					# 	audio['WORK'] = [set_subtitle]
					# elif 'WORK' in audio.tags:
					# 	del audio.tags['WORK']
					if set_subtitle:
						audio['DISCSUBTITLE'] = [set_subtitle]
					elif 'DISCSUBTITLE' in audio.tags:
						del audio.tags['DISCSUBTITLE']
					try:
						audio.save()
						try:
							os.utime(fullfilename, None)
						except Exception as e:  # noqa: BLE001
							logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
						flac_files += 1
					except Exception as e:  # noqa: BLE001
						logger.warning(f'Could not save tags for {fullfilename}: {e}')
			except Exception as e:  # noqa: BLE001
				logger.warning(f'Skipping unreadable file {fullfilename}: {e}')

		display_title = f'{album_name} [{version_str}]' if version_str else album_name
		if flac_files > 0:
			success(f'Album name changed to {display_title}')
		else:
			logger.info(f'No changes required for {display_title}')
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
	parser.add_argument(
		'--languages-only',
		action='store_true',
		help='only write LYRICS_LANGUAGE from MusicBrainz (no Discogs lookups, no other tags)',
	)
	parser.add_argument(
		'--refresh-musicbrainz',
		action='store_true',
		help='ignore cached MusicBrainz answers and ask again',
	)
	args = parser.parse_args()

	if args.directory:
		flacdir = args.directory
	else:
		import config

		flacdir = config.nzbdir

	# A 'Disc N' folder belongs to its parent album (Roon box set): one fixdir per album.
	flac_directories = []
	for root, dirs, files in os.walk(flacdir):
		for file in files:
			if file.endswith('.flac'):
				album_dir = album_root(root)
				if album_dir not in flac_directories:
					flac_directories.append(album_dir)
				break

	dclient = (
		None
		if args.languages_only
		else discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
	)

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
				if args.languages_only:
					fix_languages(directory, args.refresh_musicbrainz)
				else:
					fixdir(directory, dclient, args.refresh_musicbrainz)
				progress.update(task_id, advance=1)
		finally:
			if is_tty:
				_console_handler.stream = orig_stream


if __name__ == '__main__':
	main()
