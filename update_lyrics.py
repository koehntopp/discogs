# /// script
# dependencies = [
#   "rich",
#   "pytaglib",
#   "requests",
#   "alive-progress",
# ]
# ///

# import system libraries
import sys
import os
import re
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
import requests
from typing import Any

from alive_progress import alive_bar

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# Initialize counters
stats = {'flac_files': 0, 'lrc_total': 0, 'no_total': 0, 'lrc_new': 0, 'txt_total': 0, 'txt_new': 0, 'error': 0}

# extract a single FLAC tag
def flactag(song: taglib.File, tag: str) -> str:
    try:
        return song.tags.get(tag, [""])[0]
    except (KeyError, IndexError):
        # timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
        return ""

# logging function
def timelog(txt1: str, txt2: str, color: str = 'white') -> None:
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint(f'[{color}]{datetime.now().strftime("%H:%M:%S")}[/{color}] ' + log_msg + txt2)

def get_lrclyrics(flactags: taglib.File, albumtitle: str) -> tuple[str, str]:
   """Query lrclib.net API to find lyrics for a song.
   
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

def process_flac_file(tags: taglib.File, album_name: str, artist: str) -> tuple[str, bool]:
    dirty = False
    lyrics = flactag(tags, 'LYRICS').strip() if 'LYRICS' in tags.tags else ''
    
    if lyrics == '' or not re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
        lrc, lrctype = get_lrclyrics(tags, album_name)
        if lrctype == 'lrc':
            tags.tags['LYRICS'] = [lrc]
            rprint(f'         [yellow]LRC lyrics added[/yellow] for {tags.tags["TITLE"][0]} ([yellow]{artist}[/yellow])')
            return 'lrc', True
        elif lrctype == 'plain' and lyrics == '':
            tags.tags['LYRICS'] = [lrc]
            rprint(f'         [yellow]TXT lyrics added[/yellow] for {tags.tags["TITLE"][0]} ([yellow]{artist}[/yellow])')
            return 'txt', True
        else:
            return ('txt' if lyrics else 'none'), False
    else:
        return ('lrc' if re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics) else 'none'), False

def walkdirs(fixdir: str, bar: Any) -> int:
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

    # Process each FLAC file
    for p in Path(fixdir).rglob('*.flac'):
        tags = taglib.File(str(PurePosixPath(p)))
        lyric_type, is_dirty = process_flac_file(tags, album_name, artist)
        
        # Update statistics
        stats['flac_files'] += 1
        if lyric_type == 'lrc':
            stats['lrc_total'] += 1
            if is_dirty:
                stats['lrc_new'] += 1
        elif lyric_type == 'txt':
            stats['txt_total'] += 1
            if is_dirty:
                stats['txt_new'] += 1
        else:
            stats['no_total'] += 1
            
        if is_dirty:
            tags.save()
            
        # Update progress bar
        bar.title(f"{artist} - {album_name} : ")
        bar.text(f"LRC: {stats['lrc_total']} , TXT: {stats['txt_total']} , No Lyrics: {stats['no_total']}")
        bar()

    return stats['lrc_new'] + stats['txt_new']

def main() -> None:
    if len(sys.argv) != 2:
        from config import flacdir
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

    # Process each directory
    with alive_bar(enrich_print=False, monitor="{count}", length=20, spinner=None, bar=None) as bar:
        print("")
        timelog('Starting lyrics update in ', str(flacdir))
        print("")
        for directory in flac_directories:
            updated += walkdirs(directory, bar)
            bar()
        bar.title("")
        
        bar()          
        print("")
        timelog('Total Lyrics: ', f"LRC: {stats['lrc_total']} , TXT: {stats['txt_total']}, No Lyrics: {stats['no_total']}")
        timelog('Lyrics added: ', str(updated))
        print("")

if __name__ == '__main__':
    main()
