#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
#   "drmeter",
#   "soundfile",
# ]
# ///

import os

# import system libraries
import sys
from pathlib import Path, PurePosixPath

import soundfile as sf
from drmeter.algorithm import dynamic_range
from drmeter.models import AudioData
from mutagen.flac import FLAC

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
	last_album_name = 'Unknown'

	# iterate over FLAC files, calculate title DR (if possible)
	for p in Path(albumpath).rglob('*.flac'):
		fullfilename = str(PurePosixPath(p))
		flac_files.append(fullfilename)
		tracks += 1
		dr_song = 0
		DR = 0
		dra_dirty = False

		try:
			audio = FLAC(fullfilename)
			if not audio.tags:
				audio.add_tags()

			dr_val = audio.tags.get('DYNAMIC_RANGE') or audio.tags.get('DYNAMIC RANGE') or ['']
			try:
				dr_song = int(dr_val[0])
			except (ValueError, TypeError, IndexError):
				dr_song = 0

			if dr_song == 0:
				with sf.SoundFile(fullfilename) as data:
					try:
						result = dynamic_range(AudioData.from_soundfile(data))
						DR = round(result.overall_dr_score)
					except Exception as e:  # noqa: BLE001
						logger.error(f'DR calculation failed for {fullfilename}: {e}')

				if DR != dr_song:
					title_str = (audio.tags.get('TITLE') or ['Unknown'])[0]
					logger.info(f'DR {str(dr_song).zfill(2)} → {str(DR).zfill(2)}  {title_str}')
					audio['DYNAMIC_RANGE'] = [str(DR).zfill(2)]
					audio.save()
					try:
						os.utime(fullfilename, None)
					except Exception as e:  # noqa: BLE001
						logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
					dr_song = DR
					dra_dirty = True

			if audio.tags.get('ALBUM'):
				last_album_name = audio.tags['ALBUM'][0]
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not process FLAC file {fullfilename}: {e}')
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
				f0 = FLAC(flac_files[0])
				if f0.tags:
					val = f0.tags.get('ALBUM_DR') or f0.tags.get('ALBUM DYNAMIC RANGE') or ['']
					dr_album_old = val[0] if val else ''
			except Exception:  # noqa: BLE001
				dr_album_old = ''

		if dra_dirty or dr_album != dr_album_old:
			for fullfilename in flac_files:
				try:
					audio = FLAC(fullfilename)
					if not audio.tags:
						audio.add_tags()
					audio['ALBUM_DR'] = [str(dr_album).zfill(2)]
					audio.save()
					try:
						os.utime(fullfilename, None)
					except Exception as e:  # noqa: BLE001
						logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
				except Exception as e:  # noqa: BLE001
					logger.warning(f'Could not update ALBUM_DR for {fullfilename}: {e}')
			logger.info(f'Album DR updated to {dr_album} for {last_album_name}')
		else:
			logger.info(f'Album DR {dr_album} unchanged for {last_album_name}')
	else:
		logger.error(f'Could not calculate DR for {albumpath}')


def main() -> None:
	"""Command line interface for calculating Dynamic Range scores."""
	albumpath = sys.argv[1] if len(sys.argv) > 1 else '.'
	calculate_dr(albumpath)


if __name__ == '__main__':
	main()
