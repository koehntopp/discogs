#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
#   "pathvalidate",
#   "unidecode",
#   "python-slugify",
# ]
# ///

import argparse
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath

# Allow config.py to live outside the scripts directory (e.g. /config in Docker).
_config_dir = os.environ.get('CONFIG_DIR')
if _config_dir and _config_dir not in sys.path:
	sys.path.insert(0, _config_dir)

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from pathvalidate import sanitize_filename
from slugify import slugify

from config import flacroot, mp3root
from log import logger, success


def read_audio_tags(filepath: str) -> dict[str, list[str]]:
	"""Read Vorbis/ID3 tags from FLAC or MP3 using mutagen."""
	if filepath.endswith('.mp3'):
		try:
			audio = MP3(filepath)
			tags: dict[str, list[str]] = {}
			if audio.tags:
				for k, v in audio.tags.items():
					if k.startswith('TALB'):
						tags['ALBUM'] = [str(v)]
					elif k.startswith('TPE1'):
						tags['ARTIST'] = [str(v)]
					elif k.startswith('TPE2'):
						tags['ALBUMARTIST'] = [str(v)]
					elif k.startswith('TIT2'):
						tags['TITLE'] = [str(v)]
			return tags
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read MP3 tags from {filepath}: {e}')
			return {}

	try:
		audio = FLAC(filepath)
		if audio and audio.tags:
			return {k.upper(): [str(x) for x in v] for k, v in audio.tags.items()}
	except Exception as e:  # noqa: BLE001
		logger.warning(f'Could not read FLAC tags from {filepath}: {e}')

	return {}


def hasSubDirs(dir_name: str) -> bool:
	"""Return True if dir_name contains at least one subdirectory.

	Args:
	    dir_name: Path to the directory to inspect.

	Returns:
	    True when the directory has subdirectories, False otherwise.
	"""
	return len(list(os.walk(dir_name))) > 1


def clean(dirty_text: str) -> str:
	"""Sanitize a string for use as a filesystem path component.

	Removes or substitutes characters that are problematic on common filesystems,
	replaces spaces with underscores, and transliterates German umlauts to ASCII
	digraphs (ä→ae, ö→oe, ü→ue, ß→ss).

	Args:
	    dirty_text: Raw string (e.g. an album title or artist name from a tag).

	Returns:
	    Sanitised string safe to use as a directory or file name.
	"""
	# Clean file and path names of stupid characters
	return sanitize_filename(slugify(dirty_text, lowercase=False, separator='_'))


def get_target_path_and_filename(flac_file: str, root_dir: str) -> tuple[str, str, dict[str, str]]:
	"""Compute the canonical destination path and filename for a FLAC file.

	Reads TITLE, ALBUM, ALBUMARTIST, DISCNUMBER, and TRACKNUMBER tags from the file
	and applies clean() to produce filesystem-safe components.  The filename format is:
	    <disc_zz>_<track_zz>_<title>.flac
	The directory structure under root_dir is:
	    <root_dir>/<artist>/<album>/

	Args:
	    flac_file: Absolute path to the source FLAC file.
	    root_dir: Root of the target library (e.g. flacroot).

	Returns:
	    Tuple of (target_path, target_filename, metadata_dict) where metadata_dict
	    contains 'artist', 'album', and 'track' keys with sanitised string values.
	"""
	tags = read_audio_tags(flac_file)
	track_title = clean(tags.get('TITLE', ['Unknown Title'])[0])
	album_title = clean(tags.get('ALBUM', ['Unknown Album'])[0])
	artist = clean(
		tags.get(
			'ALBUM_ARTIST_OVERRIDE', tags.get('ALBUMARTIST', tags.get('ARTIST', ['Unknown Artist']))
		)[0]
	)

	disc = tags.get('DISCNUMBER', ['01'])[0].split('/')[0].zfill(2)
	track = tags.get('TRACKNUMBER', ['00'])[0].split('/')[0].zfill(2)
	filename = f'{disc}_{track}_{track_title}.flac'
	path = os.path.join(root_dir, artist, album_title) + '/'

	return path, filename, {'artist': artist, 'album': album_title, 'track': track_title}


def move_flac_file(source_file: str, target_path: str, target_filename: str) -> bool:
	"""Move a FLAC file to its canonical location, creating the directory if needed.

	Uses Unicode NFD normalisation for the path comparison so that case-equivalent
	names (e.g. on case-insensitive HFS+) are treated as identical and not re-moved.

	Args:
	    source_file: Absolute path to the FLAC file to move.
	    target_path: Destination directory (will be created with os.makedirs if absent).
	    target_filename: Destination filename within target_path.

	Returns:
	    True when the file was actually moved, False when source and destination
	    are the same path (nothing to do).
	"""
	target_fullname = target_path + target_filename

	# Create target directory if it doesn't exist
	if not os.path.exists(target_path):
		os.makedirs(target_path)

	# Only move if paths are different (case-insensitive comparison)
	if unicodedata.normalize('NFD', source_file.lower()) != unicodedata.normalize(
		'NFD', target_fullname.lower()
	):
		if os.path.exists(target_fullname):
			logger.error(
				f'Refusing to move {source_file} -> {target_fullname}: target file already exists!'
			)
			return False
		shutil.move(source_file, target_fullname)
		return True
	return False


def movefiles(flacroot: str, full: bool = False) -> None:
	"""Reorganise FLAC files under flacroot into the canonical directory/name structure.

	Reads each file's tags and moves it to <flacroot>/<artist>/<album>/<disc>_<track>_<title>.flac
	if it is not already there.  When full=False only files directly inside flacroot are
	checked (useful for a quick ingest pass); when full=True the entire tree is scanned.

	Args:
	    flacroot: Root library directory.
	    full: When True, scan recursively; when False, scan only the root level.
	"""
	# If full==False, only check for .flac files directly in the flacroot directory (non-recursive).
	# If full==True, scan the whole tree recursively.
	logger.info(
		f'Checking FLAC folders in {flacroot}' + (' (full recursive)' if full else ' (root-only)')
	)
	currentalbum = ''
	pattern_iter = Path(flacroot).rglob('*.flac') if full else Path(flacroot).glob('*.flac')

	for p in pattern_iter:
		fullfilename = str(PurePosixPath(p))
		try:
			tags = read_audio_tags(fullfilename)
			stracktitle = clean(tags.get('TITLE', [''])[0])
			salbumtitle = clean(tags.get('ALBUM', [''])[0])
			sartist = clean(
				tags.get(
					'ALBUM_ARTIST_OVERRIDE', tags.get('ALBUMARTIST', tags.get('ARTIST', ['']))
				)[0]
			)
			disc = tags.get('DISCNUMBER', ['0'])[0].split('/')[0].zfill(2)
			track = tags.get('TRACKNUMBER', ['0'])[0].split('/')[0].zfill(2)
			tobefilename = f'{disc}_{track}_{stracktitle}.flac'
			tobepathname = flacroot + sartist + '/' + salbumtitle + '/'
			tobefullname = tobepathname + tobefilename

			if unicodedata.normalize('NFD', fullfilename.lower()) != unicodedata.normalize(
				'NFD', tobefullname.lower()
			):
				if salbumtitle != currentalbum:
					currentalbum = salbumtitle
					success(f'Moving album {salbumtitle}')
				if os.path.exists(tobefullname):
					logger.error(
						f'Refusing to move {fullfilename} -> {tobefullname}: target file already exists!'
					)
					continue
				if not os.path.exists(tobepathname):
					os.makedirs(tobepathname)
				shutil.move(fullfilename, tobefullname)
		except Exception as e:  # noqa: BLE001
			logger.error(f'Error moving file {fullfilename}: {e}')
			continue
	logger.info('Done.')


def ingestfiles(ingest_dir: str) -> None:
	"""Move all FLAC files from an ingest directory into the canonical flacroot structure.

	Recursively finds every FLAC file in ingest_dir, reads its tags, and moves it into
	the correct location under flacroot using get_target_path_and_filename().  After
	calling this, run removedirs(ingest_dir) to clean up empty subdirectories.

	Args:
	    ingest_dir: Source directory containing freshly downloaded/ripped FLAC files.
	"""
	logger.info(f'Ingesting FLAC files from {ingest_dir}')
	currentalbum = ''

	if not os.path.exists(ingest_dir):
		logger.error(f'Error: Directory does not exist: {ingest_dir}')
		return

	# Find all FLAC files in the ingest directory
	for p in Path(ingest_dir).rglob('*.flac'):
		fullfilename = str(PurePosixPath(p))
		try:
			target_path, target_filename, metadata = get_target_path_and_filename(
				fullfilename, flacroot
			)

			if metadata['album'] != currentalbum:
				currentalbum = metadata['album']
				logger.info(f'Ingesting album {metadata["album"]}')

			if move_flac_file(fullfilename, target_path, target_filename):
				success(f'Ingested {metadata["track"]}')
		except Exception as e:  # noqa: BLE001
			logger.error(f'Error ingesting file {fullfilename}: {e}')

	logger.info('Done. Ingest complete.')


def removedirs(rootdir: str) -> None:
	"""Recursively remove directories containing no FLAC or MP3 files under rootdir.

	Walks bottom-up so children are handled before parents; a parent with only
	non-music files becomes removable once its music-free children are gone.
	Non-music files (e.g. .nfo) are deleted before the directory is removed.

	Args:
	    rootdir: Root directory to clean up.
	"""
	logger.info(f'Removing empty dirs in {rootdir}')
	for root, dirs, files in os.walk(rootdir, topdown=False):
		dir_path = Path(root)
		if dir_path == Path(rootdir):
			continue  # never remove the root itself
		if list(dir_path.rglob('*.flac')) or list(dir_path.rglob('*.mp3')):
			continue
		# Skip directories the SMB server is already cleaning up
		if any(f.name.startswith('.smbdelete') for f in dir_path.rglob('*') if f.is_file()):
			logger.info(f'Skipping SMB-pending directory {dir_path}')
			continue
		# No music anywhere under this dir — delete files then the directory
		all_deleted = True
		for f in sorted(dir_path.rglob('*'), reverse=True):
			if f.is_file():
				try:
					f.unlink()
					logger.warning(f'Removed non-music file {f}')
				except OSError as err:
					logger.error(f'Could not remove file {f}: {err}')
					all_deleted = False
		if all_deleted:
			try:
				dir_path.rmdir()
				logger.warning(f'Removed directory {dir_path}')
			except OSError as err:
				if err.errno == 16:  # EBUSY — SMB pending, will clean up on its own
					logger.info(f'Directory pending SMB cleanup {dir_path}')
				else:
					logger.error(f'Could not remove directory {dir_path}: {err}')

	logger.info('Done.')


def checkMP3() -> None:
	"""Delete stale MP3 album directories that lack a corresponding FLAC source.

	For each leaf directory under mp3root, checks whether:
	- A matching FLAC file exists in flacroot (same relative path, .mp3 → .flac).
	- If yes, whether the FLAC directory is newer than the MP3 directory (indicating
	  the FLAC was updated and the MP3 should be regenerated).

	Deletes the MP3 directory when either condition is true so that createMP3() can
	regenerate it from the current FLAC source.
	"""
	logger.info(f'Checking MP3 folders in {mp3root}')

	for root, dirs, _ in os.walk(mp3root, topdown=True):
		for dirname in dirs:
			# are we in an album directory?
			if not hasSubDirs(os.path.join(root, dirname)):
				mp3dir = os.path.join(root, dirname)
				p = Path(mp3dir)

				try:
					firstmp3 = str(next(p.glob('*.mp3')))
				except StopIteration:
					continue  # Skip if no MP3 files found

				firstflac = firstmp3.replace(mp3root, flacroot).replace('.mp3', '.flac')
				mp3_mtime = os.path.getmtime(firstmp3)
				flac_mtime = 0.0

				try:
					if os.path.isfile(firstflac):
						flac_mtime = os.path.getmtime(firstflac)
						tags = read_audio_tags(firstflac)
					else:
						tags = read_audio_tags(firstmp3)

					salbumtitle = clean(tags.get('ALBUM', ['Unknown Album'])[0])
					sartist = clean(
						tags.get('ALBUMARTIST', tags.get('ARTIST', ['Unknown Artist']))[0]
					)

					if not os.path.isfile(firstflac):
						logger.warning(f'MP3 but no FLAC - deleting {sartist} - {salbumtitle}')
						shutil.rmtree(mp3dir)
					elif flac_mtime > mp3_mtime:
						logger.warning(f'FLAC file newer - deleting {sartist} - {salbumtitle}')
						shutil.rmtree(mp3dir)

				except Exception as e:
					logger.error(f'Error processing directory {mp3dir}: {e}')
					continue

	logger.info('Done.')


def createMP3() -> None:
	"""Transcode any FLAC files that do not yet have a corresponding MP3.

	Walks flacroot recursively and, for each .flac file, checks whether the mirrored
	.mp3 file exists under mp3root (same relative path).  Missing MP3s are created with
	ffmpeg using libmp3lame VBR quality 2 (~190 kbps).  Directory structure is created
	automatically under mp3root.
	"""
	logger.info(f'Creating missing MP3s in {mp3root}')

	for p in Path(flacroot).rglob('*.flac'):
		try:
			flacfilename = str(PurePosixPath(p))
			mp3filename = flacfilename.replace(flacroot, mp3root).replace('.flac', '.mp3')

			if not os.path.isfile(mp3filename):
				# Get metadata
				tags = read_audio_tags(flacfilename)
				stracktitle = clean(tags.get('TITLE', ['Unknown Title'])[0])
				salbumtitle = clean(tags.get('ALBUM', ['Unknown Album'])[0])
				sartist = clean(tags.get('ALBUMARTIST', tags.get('ARTIST', ['Unknown Artist']))[0])

				# Create directory structure
				tobepathname = Path(mp3root) / sartist / salbumtitle
				tobepathname.mkdir(parents=True, exist_ok=True)

				logger.info(f'Creating MP3 for {salbumtitle} - {stracktitle}')

				# Construct and execute ffmpeg command with proper escaping
				flac2mp3 = [
					'ffmpeg',
					'-loglevel',
					'error',
					'-i',
					flacfilename,
					'-codec:a',
					'libmp3lame',
					'-qscale:a',
					'2',
					'-vsync',
					'2',
					mp3filename,
				]
				subprocess.run(flac2mp3, check=False)

		except Exception as e:
			logger.error(f'Error creating MP3 {flacfilename}: {e}')
			continue

	logger.info('Done.')


def main() -> None:
	"""Entry point for the bliss library management tool.

	Subcommands (flags):
	    --ingest DIR   Move all FLACs from DIR into flacroot, then clean up empty dirs.
	    --full         Recursively reorganise the entire flacroot tree.
	    --mp3          Sync the MP3 mirror: delete stale MP3 dirs, then transcode missing ones.
	    (no flags)     Quick scan: reorganise only files directly in flacroot (not recursive).
	"""
	parser = argparse.ArgumentParser(description='Music library management tool')
	parser.add_argument(
		'directory', nargs='?', help='Ingest FLAC files from this directory into the library'
	)
	parser.add_argument('--mp3', action='store_true', help='Create missing MP3 files from FLACs')
	parser.add_argument('--full', action='store_true', help='Scan entire flacroot recursively')
	parser.add_argument(
		'--ingest',
		type=str,
		metavar='DIRECTORY',
		help='Ingest FLAC files from a directory into the library',
	)

	args = parser.parse_args()

	# Positional directory argument — same as --ingest
	if args.directory:
		ingestfiles(args.directory)
		removedirs(args.directory)
		return

	# If --ingest is specified, use it
	if args.ingest:
		ingestfiles(args.ingest)
		removedirs(args.ingest)
		return

	# If --full is specified, do a recursive scan of flacroot
	if args.full:
		movefiles(flacroot, full=True)
		removedirs(flacroot)
		return

	# Run selected operations
	if args.mp3:
		checkMP3()
		removedirs(mp3root)
		createMP3()

	# If no arguments provided, default to root-only scan
	if not any(vars(args).values()):
		movefiles(flacroot, full=False)
		return


if __name__ == '__main__':
	main()
