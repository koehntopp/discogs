# /// script
# dependencies = [
#   "structlog",
#   "pytaglib",
#   "requests",
#   "discogs_client",
#   "mutagen",
#   "pillow",
# ]
# ///

from log import logger, success
# import system libraries
import time
import sys
import os
from pathlib import Path, PurePosixPath, PurePath
from typing import Optional
import argparse
from discogs_client.exceptions import HTTPError
from json import JSONDecodeError


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
				logger.warning(f'Discogs API error ({type(e).__name__}), sleeping {backoff}s (attempt {attempt + 1}/{retries})')
				time.sleep(backoff)
			else:
				raise

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
import io
from mutagen.flac import FLAC, Picture
from PIL import Image

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
				if pic.mime not in ('image/jpeg', 'image/png'):
					new_pictures.append(pic)
					continue
				img = Image.open(io.BytesIO(pic.data))
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
				success(f'Album art resized {orig_size} → {new_pictures[-1].width}x{new_pictures[-1].height} in {album_name}')
		except Exception as e:
			logger.warning(f'Cover resize failed for {flac_path}: {e}')


# extract a single FLAC tag
def flactag(song: taglib.File, tag: str, required: bool = False) -> str:
   """Extract a single tag value from a FLAC file's metadata.

   Args:
       song: TagLib file object with loaded tags.
       tag: Tag key to retrieve (e.g. 'ALBUM', 'ARTIST').
       required: If True, log an error when the tag is missing.

   Returns:
       First value for the tag, or empty string if the key is absent.
   """
   try:
      return(song.tags[tag][0])
   except (KeyError, IndexError):
      if required:
         logger.error(f'Tag Error: {tag} -- {song.tags["ALBUMARTIST"][0]} - {song.tags["ALBUM"][0]}')
      return("")

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
   first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
   if first_flac is not None:
      first_flac_path = os.path.join(fixdir, first_flac)
   else:
      return
   try:
      tags = taglib.File(first_flac_path)
   except OSError as e:
      logger.warning(f'Skipping unreadable file {first_flac_path}: {e}')
      return
   discogs = True
   try:
      discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
   except ValueError:
      discogs = False
      return
   # if we found discogs tags to work with go ahead
   if discogs:
      drelease = discogs_fetch(dclient.release, discogs_id)

      try:
         master = discogs_fetch(lambda: drelease.master)
         discogs_name = master.title.strip() if master else discogs_fetch(lambda: drelease.title.strip())
      except Exception:
         master = None
         discogs_name = discogs_fetch(lambda: drelease.title.strip())

      album_name = flactag(tags, 'ORIGINAL FILENAME').strip() or discogs_name
      bitrate = int(tags.sampleRate / 1000)
      try:
         album_year_release = int(flactag(tags, 'DATE'))
      except ValueError:
         album_year_release = drelease.year
      try:
         album_year_master = discogs_fetch(lambda: master.main_release.year) if master else album_year_release
      except Exception:
         logger.warning(f'Could not fetch master release year for Discogs ID {discogs_id} in {fixdir}, using release year')
         album_year_master = album_year_release
      if album_year_release == 0 and album_year_master != 0:
         album_year_release = album_year_master
      if album_year_release != 0 and album_year_master == 0:
         album_year_master = album_year_release
      album_description = flactag(tags, 'SUBTITLE').strip() or 'CD'
      dr_rating = flactag(tags, "ALBUM DYNAMIC RANGE").strip() or ''

      album_newtitle = (f"{album_name} [{str(album_year_release)} {album_description} {str(bitrate)}kHz DR{dr_rating}]")
      # Create new tags dictionary once, as it's the same for all files in the album.
      new_tags = {
         'RELEASEDATE': [str(album_year_release)],
         'DATE': [str(album_year_release)],
         'ORIGINALDATE': [str(album_year_master)],
         'ORIGINALRELEASEDATE': [str(album_year_master)],
         'ALBUM': [album_newtitle],
         'ORIGINAL_TITLE': [discogs_name]
      }

      for p in Path(fixdir).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         try:
            tags = taglib.File(fullfilename)
         except OSError as e:
            logger.warning(f'Skipping unreadable file {fullfilename}: {e}')
            continue
         if any(tags.tags.get(k) != v for k, v in new_tags.items()):
            tags.tags.update(new_tags)
            try:
               tags.save()
               flac_files += 1
            except OSError as e:
               logger.warning(f'Could not save tags for {fullfilename}: {e}')
      
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
    parser.add_argument('directory', nargs='?',
                       help='directory containing FLAC files to process')
    args = parser.parse_args()

    if args.directory:
        flacdir = args.directory
    else:
        import config
        flacdir = config.nzbdir

    flac_directories = []
    for root, dirs, files in os.walk(flacdir):
        for file in files:
            if file.endswith(".flac"):
                flac_directories.append(root)
                break
    
    dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
    for directory in flac_directories:
        fixdir(directory, dclient)

if __name__ == '__main__':
   main()
