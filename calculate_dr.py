#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "drmeter",
#   "soundfile",
# ]
# ///

import os

# import system libraries
import sys
from pathlib import Path, PurePosixPath

import soundfile as sf

# https://github.com/supermihi/pytaglib
import taglib

# import DRMETER https://codeberg.org/janw/drmeter
from drmeter.algorithm import dynamic_range
from drmeter.models import AudioData

from log import logger


# calculate song and album dynamic range and write tags to files
def calculate_dr(albumpath: str) -> None:
	"""Calculate the Dynamic Range score for every track in an album directory.

	Iterates all FLAC files in albumpath (recursively). For each file, reads the
	existing DYNAMIC RANGE tag; if absent, computes it with drmeter and writes the
	result back. After processing all tracks, derives the album-level DR score as the
	mean of per-track scores and writes ALBUM DYNAMIC RANGE to every file if the
	value changed.

	Logs a warning when some tracks are missing a DR score (e.g. corrupt files).

	Args:
	    albumpath: Absolute path to the album directory.
	"""
	# assumption: folder only contains a single album
	dr_sum = 0
	dr_tracks = 0
	tracks = 0
	flac_files: list[str] = []
	# iterate over FLAC files, calculate title DR (if possible)
	for p in Path(albumpath).rglob('*.flac'):
		fullfilename = str(PurePosixPath(p))
		flac_files.append(fullfilename)
		tracks += 1
		dr_song = 0
		DR = 0
		dra_dirty = False
		try:
			with taglib.File(fullfilename) as dr_tags:
				try:
					dr_val = (
						dr_tags.tags.get('DYNAMIC_RANGE')
						or dr_tags.tags.get('DYNAMIC RANGE')
						or ['']
					)
					dr_song = int(dr_val[0])
				except (KeyError, IndexError, ValueError, TypeError):
					with sf.SoundFile(fullfilename) as data:
						try:
							result = dynamic_range(AudioData.from_soundfile(data))
							DR = round(result.overall_dr_score)
						except Exception as e:  # noqa: BLE001
							logger.error(f'DR calculation failed for {fullfilename}: {e}')
					if DR != dr_song:
						title_str = (dr_tags.tags.get('TITLE') or ['Unknown'])[0]
						logger.info(f'DR {str(dr_song).zfill(2)} → {str(DR).zfill(2)}  {title_str}')
						dr_tags.tags['DYNAMIC_RANGE'] = [str(DR).zfill(2)]
						dr_tags.save()
						try:
							os.utime(fullfilename, None)
						except Exception as e:  # noqa: BLE001
							logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
						dr_song = DR
						dra_dirty = True
		except OSError as e:
			logger.warning(f'Could not read FLAC file {fullfilename}: {e}')
			continue
		if dr_song > 0:
			dr_tracks += 1
			dr_sum += dr_song
	if dr_tracks != tracks:
		logger.warning(f'Incomplete DR: {dr_tracks}/{tracks} tracks have DR scores')
	if dr_tracks > 0:
		dr_album = str(round(dr_sum / dr_tracks)).zfill(2)
		dr_album_old = ''
		if flac_files:
			try:
				with taglib.File(flac_files[0]) as dr_tags:
					dr_album_old = (
						dr_tags.tags.get('ALBUM_DR')
						or dr_tags.tags.get('ALBUM DYNAMIC RANGE')
						or ['']
					)[0]
			except (OSError, KeyError, IndexError, TypeError):
				dr_album_old = ''
		if dra_dirty or dr_album != dr_album_old:
			last_album_str = 'Unknown'
			for fullfilename in flac_files:
				try:
					with taglib.File(fullfilename) as dr_tags:
						dr_tags.tags['ALBUM_DR'] = [str(dr_album).zfill(2)]
						dr_tags.save()
						last_album_str = (dr_tags.tags.get('ALBUM') or ['Unknown'])[0]
						try:
							os.utime(fullfilename, None)
						except Exception as e:  # noqa: BLE001
							logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
				except OSError as e:
					logger.warning(f'Could not update ALBUM_DR for {fullfilename}: {e}')
			logger.info(f'Album DR updated to {dr_album} for {last_album_str}')
		else:
			album_str = (dr_tags.tags.get('ALBUM') or ['Unknown'])[0]
			logger.info(f'Album DR {dr_album} unchanged for {album_str}')
	else:
		logger.error(f'Could not calculate DR for {albumpath}')


def main() -> None:
	"""Entry point: walk a FLAC directory tree and calculate DR for every album.

	Reads the root directory from config.flacdir or a single positional command-line
	argument, discovers all album directories containing FLAC files, and calls
	calculate_dr() for each one in sequence.
	"""
	if len(sys.argv) != 2:
		from config import nzbdir as flacdir
	else:
		flacdir = sys.argv[1]
	# find all directories containing flac files below fixdir
	flac_directories = []
	for root, dirs, files in os.walk(flacdir):
		for file in files:
			if file.endswith('.flac'):
				flac_directories.append(root)
				break
	for directory in flac_directories:
		logger.info(f'DR: {directory}')
		calculate_dr(directory)


if __name__ == '__main__':
	main()
