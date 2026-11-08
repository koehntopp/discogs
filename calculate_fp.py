#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
#   "mutagen",
#   "requests",
#   "pyacoustid",
#   "rich",
# ]
# ///

import os

# import system libraries
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import acoustid
from mutagen.flac import FLAC

from log import logger
from scan_progress import scan_progress


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

	paths = list(Path(albumpath).rglob('*.flac'))

	# fpcalc runs as a subprocess, so threads suffice; tags are written sequentially below.
	def needs_fp(path: Path) -> bool:
		try:
			tags = FLAC(str(path)).tags or {}
		except Exception:  # noqa: BLE001
			return False  # unreadable: the main loop logs it
		return not str(
			(tags.get('ACOUSTID_FINGERPRINT') or tags.get('ACOUSTID FINGERPRINT') or [''])[0]
		).strip()

	todo = [p for p in paths if needs_fp(p)]
	pool = ThreadPoolExecutor(max_workers=os.cpu_count() or 1)
	futures: dict[Path, Future] = {
		p: pool.submit(
			acoustid.fingerprint_file, str(PurePosixPath(p)), maxlength=10000, force_fpcalc=False
		)
		for p in todo
	}

	for p in paths:
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
					_duration, raw_fp = futures[p].result()
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

	pool.shutdown()
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
	with scan_progress(len(flac_directories), 'Fingerprinting') as tick:
		for directory in flac_directories:
			logger.info(f'Starting AcoustID fingerprint generation in {directory}')
			calculate_fp(directory)
			tick()


if __name__ == '__main__':
	main()
