# /// script
# dependencies = [
#   "loguru",
#   "pytaglib",
#   "requests",
# ]
# ///

from log import logger, timelog
# import system libraries
import sys
import os
import re
from pathlib import Path, PurePosixPath, PurePath
import requests
from concurrent.futures import ThreadPoolExecutor

import time

# https://github.com/supermihi/pytaglib
import taglib

LRC_PATTERN = re.compile(r'\[\d\d\D\d\d\D\d\d\]')

# Initialize counters
stats = {'flac_files': 0, 'lrc_total': 0, 'no_total': 0, 'lrc_new': 0, 'txt_total': 0, 'txt_new': 0, 'error': 0}

# extract a single FLAC tag
def flactag(song: taglib.File, tag: str) -> str:
    """Extract a single tag value from a FLAC file's metadata.

    Args:
        song: TagLib file object with loaded tags.
        tag: Tag key to retrieve.

    Returns:
        First value for the tag, or empty string if not found.
    """
    try:
        return song.tags.get(tag, [""])[0]
    except (KeyError, IndexError):
        # timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
        return ""


def get_lrclyrics(flactags: taglib.File, albumtitle: str) -> tuple[str, str]:
   """Query the lrclib.net API to retrieve lyrics for a single track.
   
   Args:
       flactags: TagLib file object containing song metadata
       albumtitle: Album title string
       
   Returns:
       Tuple of (lyrics_text, lyrics_type) where lyrics_type is 'lrc', 'plain' or 'none'
   """
   params = {
       'artist_name': flactags.tags['ARTIST'],
       'track_name': flactags.tags['TITLE'], 
       'album_name': albumtitle,
       'duration': str(round(flactags.length))
   }
   
   pattern = r'\[(\d{2}:\d{2}\.\d{2})\d{1}\]'
   
   try:
       response = requests.get(
           'https://lrclib.net/api/get',
           params=params,
           headers={'User-Agent': 'Mozilla/5.0'}
       )
       data = response.json()
       
       if data['syncedLyrics']:
           syncedLyrics = re.sub(pattern, r'[\1]', data['syncedLyrics'])
           return syncedLyrics, 'lrc'
       elif data['plainLyrics']:
           return data['plainLyrics'], 'plain'
           
   except Exception:
       pass

   return '', 'none'

def _fetch_track_lyrics(flac_path: str, album_name: str) -> tuple[str, str, str, str, bool]:
    """Fetch lyrics for a single track (runs in thread pool — no file writes).

    Opens its own taglib.File instance so it is safe to call concurrently.
    Skips the network call when the file already contains LRC-format lyrics.

    Args:
        flac_path: Absolute path to the FLAC file.
        album_name: Album title passed to the lrclib.net API.

    Returns:
        Tuple of (flac_path, title, lyrics_text, lyrics_type, is_dirty) where
        is_dirty is True when new lyrics were fetched and should be written back.
    """
    tags = taglib.File(flac_path)
    title = flactag(tags, 'TITLE')
    existing = flactag(tags, 'LYRICS').strip() if 'LYRICS' in tags.tags else ''

    if existing and LRC_PATTERN.match(existing):
        return flac_path, title, existing, 'lrc', False

    lrc, lrctype = get_lrclyrics(tags, album_name)
    if lrctype == 'lrc':
        return flac_path, title, lrc, 'lrc', True
    if lrctype == 'plain' and not existing:
        return flac_path, title, lrc, 'txt', True
    return flac_path, title, existing, ('txt' if existing else 'none'), False

def walkdirs(fixdir: str) -> int:
    """Process all FLAC files in an album directory, fetching lyrics where missing.

    Reads the DISCOGS_RELEASE_ID and ORIGINAL_TITLE tags from the first FLAC file to
    identify the album, then fetches lyrics for all tracks concurrently (up to 8
    simultaneous lrclib.net requests) via _fetch_track_lyrics().  Results are applied
    sequentially in the main thread. Skips the directory if no FLAC files are found or
    DISCOGS_RELEASE_ID is absent. Updates global stats counters for reporting.

    Args:
        fixdir: Path to the album directory to process.


    Returns:
        Number of files that had new lyrics written (lrc_new + txt_new for this call).
    """
    global stats
    stats['txt_new'] = 0
    stats['lrc_new'] = 0    
       
    # Get first FLAC file
    first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
    if not first_flac:
        return 0
        
    # Check for Discogs ID
    tags = taglib.File(os.path.join(fixdir, first_flac))
    try:
        discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
        album_name = flactag(tags, 'ORIGINAL_TITLE').strip()
        artist = flactag(tags, 'ARTIST')
    except ValueError:
        stats['error'] += 1
        return 0

    # Collect FLAC paths, then fetch lyrics concurrently (HTTP only, no writes)
    flac_paths = [str(PurePosixPath(p)) for p in Path(fixdir).rglob('*.flac')]
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_track_lyrics, p, album_name) for p in flac_paths]
        fetch_results = [f.result() for f in futures]

    # Apply results sequentially (file writes are not thread-safe)
    for flac_path, title, lyrics, lyric_type, is_dirty in fetch_results:
        stats['flac_files'] += 1
        if lyric_type == 'lrc':
            stats['lrc_total'] += 1
            if is_dirty:
                stats['lrc_new'] += 1
                logger.success(f'LRC lyrics added for {title} ({artist})')
        elif lyric_type == 'txt':
            stats['txt_total'] += 1
            if is_dirty:
                stats['txt_new'] += 1
                logger.success(f'TXT lyrics added for {title} ({artist})')
        else:
            stats['no_total'] += 1

        if is_dirty:
            tags = taglib.File(flac_path)
            tags.tags['LYRICS'] = [lyrics]
            tags.save()

    return stats['lrc_new'] + stats['txt_new']

def main() -> None:
    """Entry point: walk a FLAC directory tree and update lyrics for all albums.

    Reads the root directory from config.flacdir or a single positional command-line
    argument. Processes each album directory in sequence
    and prints summary totals on completion.
    """
    if len(sys.argv) != 2:
        from config import nzbdir as flacdir
    else:
        flacdir = sys.argv[1]

    flac_directories = []
    updated = 0

    # Find all directories containing FLAC files
    for root, dirs, files in os.walk(flacdir):
        for file in files:
            if file.endswith(".flac"):
                flac_directories.append(root)
                break

    total = len(flac_directories)
    logger.info(f"Starting lyrics update in {flacdir} ({total} albums)")
    last_report = time.monotonic()
    for i, directory in enumerate(flac_directories, 1):
        updated += walkdirs(directory)
        if time.monotonic() - last_report >= 10:
            logger.info(
                f"Progress: {i}/{total} albums — "
                f"LRC: {stats['lrc_total']} TXT: {stats['txt_total']} "
                f"None: {stats['no_total']} New: {updated}"
            )
            last_report = time.monotonic()
    logger.success(
        f"Done — LRC: {stats['lrc_total']} TXT: {stats['txt_total']} "
        f"None: {stats['no_total']} New: {updated}"
    )

if __name__ == '__main__':
    main()
