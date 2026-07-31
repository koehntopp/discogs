#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
# ]
# ///

import argparse
import os
import tempfile
from pathlib import Path
from subprocess import DEVNULL, Popen, call

from log import logger, set_log_level, success

SCRIPTS_DIR = Path(__file__).parent


def main() -> None:
	"""Run the full NZB post-processing pipeline on a directory of FLAC files.

	Reads the target directory from config.nzbdir or a single positional command-line
	argument. Runs dot_clean, then calculate_dr, rsgain, and calculate_fp in parallel,
	followed by fixtags and update_lyrics sequentially.
	"""
	parser = argparse.ArgumentParser(
		description='Run the NZB post-processing pipeline on a directory of FLAC files'
	)
	parser.add_argument('directory', nargs='?', help='Directory containing FLAC files')
	parser.add_argument(
		'-q',
		'--quiet',
		action='store_true',
		help='Quiet mode: hide INFO logs, show only SUCCESS, WARNING, and ERROR',
	)
	parser.add_argument(
		'--log-level',
		type=str,
		default=None,
		help="Set log level ('DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR')",
	)

	args = parser.parse_args()

	if args.quiet:
		active_log_level = 'SUCCESS'
	elif args.log_level:
		active_log_level = args.log_level.upper()
	else:
		active_log_level = os.environ.get('LOG_LEVEL', 'SUCCESS')

	set_log_level(active_log_level)
	child_env = {**os.environ, 'LOG_LEVEL': active_log_level}

	nzbdir = args.directory
	if not nzbdir:
		from config import nzbdir

	from config import (
		rsgain_clip_mode,
		rsgain_loudness,
		rsgain_max_peak,
		rsgain_skip,
		rsgain_true_peak,
	)

	# Generate a temporary rsgain preset from config values
	preset_ini = (
		'[Global]\n'
		f'TargetLoudness={rsgain_loudness}\n'
		f'ClipMode={rsgain_clip_mode}\n'
		f'MaxPeakLevel={rsgain_max_peak}\n'
		f'TruePeak={"true" if rsgain_true_peak else "false"}\n'
		'Album=true\n'
		'TagMode=i\n'
	)
	preset_file = tempfile.NamedTemporaryFile(
		mode='w', suffix='.ini', delete=False, prefix='rsgain_'
	)
	preset_file.write(preset_ini)
	preset_file.close()

	skip_flag = ['-S'] if rsgain_skip else []

	call(['dot_clean', nzbdir], stdout=DEVNULL, stderr=DEVNULL)

	rsgain_cmd = ['rsgain', 'easy'] + skip_flag + ['-p', preset_file.name, nzbdir]
	if active_log_level in ('SUCCESS', 'WARNING', 'ERROR'):
		rsgain_cmd.insert(2, '-q')
	logger.info(f'rsgain command: {" ".join(rsgain_cmd)}')
	parallel = [
		('calculate_dr', Popen([str(SCRIPTS_DIR / 'calculate_dr.py'), nzbdir], env=child_env)),
		('rsgain', Popen(rsgain_cmd, stdout=DEVNULL, stderr=DEVNULL)),
		('calculate_fp', Popen([str(SCRIPTS_DIR / 'calculate_fp.py'), nzbdir], env=child_env)),
	]
	for name, p in parallel:
		rc = p.wait()
		if rc != 0:
			logger.error(f'Warning: {name} exited with code {rc}')
		else:
			success(f'{name} done')

	os.unlink(preset_file.name)

	call([str(SCRIPTS_DIR / 'fixtags.py'), nzbdir], env=child_env)
	call([str(SCRIPTS_DIR / 'update_lyrics.py'), nzbdir], env=child_env)


if __name__ == '__main__':
	main()
