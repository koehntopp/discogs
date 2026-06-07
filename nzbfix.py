# /// script
# dependencies = [
#   "structlog",
# ]
# ///

from log import logger, success
import os, sys, tempfile
from subprocess import call, Popen, DEVNULL
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent



def main() -> None:
   """Run the full NZB post-processing pipeline on a directory of FLAC files.

   Reads the target directory from config.nzbdir or a single positional command-line
   argument. Runs dot_clean, then calculate_dr, rsgain, and calculate_fp in parallel,
   followed by fixtags and update_lyrics sequentially.
   """
   if len(sys.argv) != 2:
      from config import nzbdir
   else:
      nzbdir = sys.argv[1]

   from config import (
      rsgain_loudness, rsgain_clip_mode, rsgain_max_peak,
      rsgain_true_peak, rsgain_opus_mode, rsgain_skip,
   )

   # Generate a temporary rsgain preset from config values
   preset_ini = (
      '[Global]\n'
      f'TargetLoudness={rsgain_loudness}\n'
      f'ClipMode={rsgain_clip_mode}\n'
      f'MaxPeakLevel={rsgain_max_peak}\n'
      f'TruePeak={"true" if rsgain_true_peak else "false"}\n'
      f'OpusMode={rsgain_opus_mode}\n'
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

   logger.info(f'Starting parallel processing in {nzbdir}')
   rsgain_cmd = ['rsgain', 'easy'] + skip_flag + ['-p', preset_file.name, nzbdir]
   logger.info(f"rsgain command: {' '.join(rsgain_cmd)}")
   parallel = [
      ('calculate_dr',  Popen(['uv', 'run', str(SCRIPTS_DIR / 'calculate_dr.py'), nzbdir])),
      ('rsgain',        Popen(rsgain_cmd)),
      ('calculate_fp',  Popen(['uv', 'run', str(SCRIPTS_DIR / 'calculate_fp.py'), nzbdir])),
   ]
   for name, p in parallel:
      rc = p.wait()
      if rc != 0:
         logger.error(f'Warning: {name} exited with code {rc}')
      else:
         success(f'{name} done')

   os.unlink(preset_file.name)

   call(['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), nzbdir])
   call(['uv', 'run', str(SCRIPTS_DIR / 'update_lyrics.py'), nzbdir])


if __name__ == '__main__':
   main()
