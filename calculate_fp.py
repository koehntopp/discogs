#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
#   "requests",
#   "pyacoustid",
# ]
# ///

import os

# import system libraries
import sys
from pathlib import Path, PurePosixPath

import acoustid
from mutagen.flac import FLAC

from log import logger


# calculate acoustic fingerprints and write tags to files
def calculate_fp(albumpath: str) -> None:
	"""Generate and store AcoustID fingerprints for every FLAC file in an album directory.

	Reads the existing ACOUSTID FINGERPRINT tag from each file; if absent, calls
	fpcalc via pyacoustid to compute a fingerprint and writes it back to the file.
	Logs the number of fingerprints generated vs total tracks processed.

	Args:
	    albumpath: Absolute path to the album directory (searched recursively).
	"""
	total = 0
	calculated = 0

	for p in Path(albumpath).rglob('*.flac'):
		fullfilename = str(PurePosixPath(p))
		total += 1
		fingerprint = ''

		try:
			audio = FLAC(fullfilename)
			if not audio.tags:
				audio.add_tags()

			fp_tags = audio.tags.get('ACOUSTID_FINGERPRINT') or audio.tags.get(
				'ACOUSTID FINGERPRINT'
			)
			fingerprint = str(fp_tags[0]).strip() if fp_tags else ''

			if not fingerprint:
				try:
					_duration, raw_fp = acoustid.fingerprint_file(
						fullfilename, maxlength=10000, force_fpcalc=False
					)
					fingerprint = (
						raw_fp.decode('utf-8') if isinstance(raw_fp, bytes) else str(raw_fp).strip()
					)
					audio['ACOUSTID_FINGERPRINT'] = [fingerprint]
					audio.save()
					try:
						os.utime(fullfilename, None)
					except Exception as e:  # noqa: BLE001
						logger.warning(f'Could not touch file mtime for {fullfilename}: {e}')
					title_str = (audio.tags.get('TITLE') or ['Unknown'])[0]
					logger.info(f'Calculated AcoustID fingerprint for {title_str}')
					calculated += 1
				except Exception as e:  # noqa: BLE001
					logger.error(f'Fingerprint calculation failed for {fullfilename}: {e}')
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read FLAC file {fullfilename}: {e}')
			continue

	logger.info(f'AcoustID fingerprints generated for {calculated} of {total} files.')


def main() -> None:
	"""Entry point: walk a FLAC directory tree and generate AcoustID fingerprints.

	Reads the root directory from config.flacdir or a single positional command-line
	argument, discovers all album directories containing FLAC files, and calls
	calculate_fp() for each one in sequence.
	"""
	if len(sys.argv) != 2:
		from config import nzbdir as flacdir
	else:
		flacdir = sys.argv[1]
	flac_directories = []
	for root, _dirs, files in os.walk(flacdir):
		for file in files:
			if file.endswith('.flac'):
				flac_directories.append(root)
				break
	for directory in flac_directories:
		logger.info(f'Starting AcoustID fingerprint generation in {directory}')
		calculate_fp(directory)


if __name__ == '__main__':
	main()
