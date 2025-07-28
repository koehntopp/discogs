# import system libraries
import sys
import os
import re
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
import requests
from rich.console import Console

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# Add this after imports:
console = Console()

# extract a single FLAC tag
def flactag(song, tag):
    try:
        return song.tags.get(tag, [""])[0]
    except (KeyError, IndexError):
        # timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
        return ""

# logging function
def timelog(txt1, txt2, color: str = 'white'):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint(f'[{color}]{datetime.now().strftime("%H:%M:%S")}[/{color}] ' + log_msg + txt2)

def get_lrclyrics(flactags, albumtitle):
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
   
   try:
       response = requests.get(
           'https://lrclib.net/api/get',
           params=params,
           headers={'User-Agent': 'Mozilla/5.0'}
       )
       data = response.json()
       
       if data['syncedLyrics']:
           return data['syncedLyrics'], 'lrc'
       elif data['plainLyrics']:
           return data['plainLyrics'], 'plain'
           
   except:
       pass
       
   return '', 'none'

def process_flac_file(tags, album_name, artist):
    dirty = False
    lyrics = flactag(tags, 'LYRICS').strip() if 'LYRICS' in tags.tags else ''
    
    if lyrics == '' or not re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
        lrc, lrctype = get_lrclyrics(tags, album_name)
        if lrctype == 'lrc':
            tags.tags['LYRICS'] = [lrc]
            console.print(f'           [yellow]LRC lyrics added[/yellow] for {tags.tags["TITLE"][0]} ([yellow]{artist}[/yellow])')
            return 'lrc', True
        elif lrctype == 'plain' and lyrics == '':
            tags.tags['LYRICS'] = [lrc]
            console.print(f'           [yellow]TXT lyrics added[/yellow] for {tags.tags["TITLE"][0]} ([yellow]{artist}[/yellow])')
            return 'txt', True
        else:
            return ('txt' if lyrics else 'none'), False
    else:
        return ('lrc' if re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics) else 'none'), False

def walkdirs(fixdir):
    # Initialize counters
    stats = {'flac_files': 0, 'lrc_total': 0, 'no_total': 0, 
            'lrc_new': 0, 'txt_total': 0, 'txt_new': 0}
    
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
    except:
        timelog('No Discogs tags found in ', fixdir)
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

    # Print summary with colors, only showing when there are changes
    if stats["lrc_new"] > 0 or stats["txt_new"] > 0:
        summary_new = f'         {stats["flac_files"]} FLAC files processed'
        if stats["lrc_new"] > 0:
            summary_new += f', [cyan]{stats["lrc_new"]} LRC lyrics[/cyan]'
        if stats["txt_new"] > 0:
            summary_new += f', [magenta]{stats["txt_new"]} TXT lyrics[/magenta]'
        summary_new += ' added'
        console.print(summary_new)

    summary_total = f'         {stats["flac_files"]} FLAC files processed'
    if stats["lrc_total"] > 0:
        summary_total += f', [cyan]{stats["lrc_total"]} LRC lyrics[/cyan]'
    if stats["txt_total"] > 0:
        summary_total += f', [magenta]{stats["txt_total"]} TXT lyrics[/magenta]'
    if stats["no_total"] > 0:
        summary_total += f', [red]{stats["no_total"]}[/red] files without lyrics'
    summary_total += ' present'
    console.print(summary_total)
    
    return stats['lrc_new'] + stats['txt_new']

def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]
   flac_directories = []
   updated = 0
   for root, dirs, files in os.walk(flacdir):
      for file in files:
         if file.endswith(".flac"):
            flac_directories.append(root)
            break
   for directory in flac_directories:
      timelog('Starting lyrics update in ', directory)
      updated += walkdirs(directory)
   print("")
   timelog('Lyrics added: ', str(updated))

if __name__ == '__main__':
   main()
