# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "mutagen",
#   "pathvalidate",
#   "python-slugify",
# ]
# ///

from log import logger, success
import os
import subprocess
import argparse
from pathlib import Path, PurePosixPath

import base64
import taglib
from mutagen.flac import FLAC
from mutagen.oggopus import OggOpus
from pathvalidate import sanitize_filename
from slugify import slugify

from config import opusroot

OPUS_BITRATE = '192k'



def clean(dirty_text: str) -> str:
   """Sanitise a string for use as a filesystem path component.

   Args:
       dirty_text: Raw string (e.g. an album title or artist name from a tag).

   Returns:
       Sanitised string safe to use as a directory or file name.
   """
   return sanitize_filename(slugify(dirty_text, lowercase=False, separator='_'))


def copy_cover(flac_path: Path, opus_path: Path) -> bool:
   """Copy embedded cover art from a FLAC file into an Opus file.

   Opus stores cover art as a base64-encoded METADATA_BLOCK_PICTURE Vorbis comment.
   Returns True if at least one picture was copied, False if none were found.

   Args:
       flac_path: Source FLAC file with embedded pictures.
       opus_path: Destination Opus file to receive the cover art.
   """
   flac = FLAC(str(flac_path))
   if not flac.pictures:
      return False
   opus = OggOpus(str(opus_path))
   opus['metadata_block_picture'] = [
      base64.b64encode(pic.write()).decode('ascii') for pic in flac.pictures
   ]
   opus.save()
   return True


def convert_dir(flacdir: str) -> None:
   """Convert all FLAC files in flacdir to Opus under opusroot.

   Reads ALBUMARTIST and ALBUM tags from the first FLAC file to build the target
   directory path (<opusroot>/<artist>/<album>/). Each file is transcoded with ffmpeg
   to libopus at OPUS_BITRATE using VBR. Files that already exist at the target path
   are skipped. Output filename format mirrors bliss.py: <disc>_<track>_<title>.opus.

   Args:
       flacdir: Path to a directory containing FLAC files to convert.
   """
   flac_files = sorted(Path(flacdir).glob('*.flac'))
   if not flac_files:
      logger.error(f'No FLAC files found in {flacdir}')
      return

   first = taglib.File(str(flac_files[0]))
   artist = clean(first.tags.get('ALBUMARTIST', first.tags.get('ARTIST', ['Unknown']))[0])
   album = clean(first.tags.get('ALBUM', ['Unknown'])[0])

   target_dir = Path(flacdir) / artist / album
   target_dir.mkdir(parents=True, exist_ok=True)

   logger.info(f'Converting {artist} / {album}')

   converted = 0
   skipped = 0
   errors = 0

   for flac_path in flac_files:
      tags = taglib.File(str(flac_path))
      disc = tags.tags.get('DISCNUMBER', ['01'])[0].zfill(2)
      track = tags.tags.get('TRACKNUMBER', ['00'])[0].zfill(2)
      title = clean(tags.tags.get('TITLE', [flac_path.stem])[0])
      opus_path = target_dir / f'{disc}_{track}_{title}.opus'

      if opus_path.exists():
         skipped += 1
         continue

      cmd = [
         'ffmpeg', '-loglevel', 'error',
         '-i', str(flac_path),
         '-map', '0:a',
         '-c:a', 'libopus',
         '-b:a', OPUS_BITRATE,
         '-vbr', 'on',
         str(opus_path),
      ]
      result = subprocess.run(cmd)
      if result.returncode == 0:
         copy_cover(flac_path, opus_path)
         success(f'Converted {opus_path.name}')
         converted += 1
      else:
         logger.error(f'Failed {flac_path}')
         errors += 1

   logger.info(f'Done. {converted} converted, {skipped} skipped, {errors} errors')


def main() -> None:
   """Entry point: convert a single FLAC directory to Opus.

   Reads the source directory from the positional argument and writes Opus files
   to <opusroot>/<artist>/<album>/ as defined in config.py.
   """
   parser = argparse.ArgumentParser(description='Convert a FLAC folder to Opus')
   parser.add_argument('directory', help='source directory containing FLAC files')
   args = parser.parse_args()
   convert_dir(args.directory)


if __name__ == '__main__':
   main()
