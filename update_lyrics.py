# import system libraries
import json
import time
import sys
import os
import re
import glob
import traceback
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
import requests
from urllib.parse import quote, urlencode

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

from mutagen.flac import FLAC

# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
# https://github.com/KristoforMaynard/music-tag
import music_tag

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

def get_lrclyrics(flactags):
   # try to find better lyrics data for one song
   duration = str(round(flactags.info.length))
   try:
      albumtitle = flactags['ORIGINAL_TITLE'][0]
   except KeyError:
      albumtitle = flactags['ALBUM'][0]
   # query lrclib.net https://github.com/tranxuanthang/lrcget
   url_template = 'https://lrclib.net/api/get?{}'
   headers = {
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36"
   }
   params = {
      'artist_name': flactags['ALBUMARTIST'][0],
      'track_name': flactags['TITLE'][0],
      'album_name': albumtitle,
      'duration': duration,
   }
   url = url_template.format(urlencode(params, safe='()', quote_via=quote))
   lyricsdata = ''
   lyricstype = 'none'
   try:
      response = requests.get(url)
      data = response.json()
      if data['syncedLyrics']:
         lyricsdata = data['syncedLyrics']
         lyricstype = 'lrc'
      elif data['plainLyrics']:
         lyricsdata = data['plainLyrics']
         lyricstype = 'plain'
   except:
      lyricsdata = ''
   return lyricsdata, lyricstype


# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir):
   global lrc_total
   flac_files = 0
   lrctotal = 0
   nototal = 0
   lrcnew = 0
   txttotal = 0
   txtnew = 0

   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)

   # find all directories containing flac files below fixdir
   files = glob.glob(os.path.join(fixdir, '**', '*.flac'), recursive=True)
   paths = list(set(map(os.path.dirname, files)))
   pathbar = tqdm(range(len(paths)))
   for i in pathbar:
      shortpath = (
         (PurePath(paths[i]).name[:40] + '..')
         if len(PurePath(paths[i]).name) > 40
         else PurePath(paths[i]).name
      )
      # timelog('Analyzing ', shortpath)
      firstflac = next(Path(paths[i]).rglob('*.flac'), None)
      tags = FLAC(firstflac)
      discogs = True
      try:
         discogs_idstring = tags['DISCOGS_RELEASE_ID']
         discogs_id = int(discogs_idstring[0])
      except:
         discogs = False
      # if we found discogs tags to work with go ahead
      if discogs:
         tag_album = str(tags['album'])
         tag_artist = str(tags['albumartist'])
         drelease = dclient.release(discogs_id)
         # make Discogs API rate limit happy
         time.sleep(3)
         try:
            album_name = tags['ORIGINAL FILENAME'][0].strip()
         except:
            album_name = drelease.title.strip()
         album_artist = tags['ALBUMARTIST'][0]
         songs = 0
         # write new tags to files
         for subdir, dirs, files in os.walk(paths[i]):
            for filename in files:
               filepath = paths[i] + os.sep + filename
               if filepath.endswith('.flac'):
                  dirty = False
                  tags = FLAC(filepath)
                  try:
                     lyrics = tags['LYRICS'][0].strip()
                  except KeyError:
                     lyrics = ''
                  if lyrics == '' or not re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
                     lrc, lrctype = get_lrclyrics(tags)
                     if lrctype == 'lrc':
                        tags['LYRICS'] = lrc
                        lrcnew += 1
                        lrctotal += 1
                        dirty = True
                        tqdm.write(
                           '           LRC lyrics added for '
                           + tags['TITLE'][0]
                           + ' ('
                           + album_artist
                           + ')'
                        )
                     elif lrctype == 'plain' and lyrics == '':
                        tags['LYRICS'] = lrc
                        txtnew += 1
                        txttotal += 1
                        dirty = True
                        tqdm.write(
                           '           TXT lyrics added for '
                           + tags['TITLE'][0]
                           + ' ('
                           + album_artist
                           + ')'
                        )
                     else:
                        if lyrics != '':
                           txttotal += 1
                        else:
                           nototal += 1
                  else:
                     if re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
                        lrctotal += 1
                  if dirty:
                     tags.save()
                  flac_files += 1
      else:
         timelog('No Discogs tags found in ', shortpath)
   timelog('Finished analysis', fixdir)
   tqdm.write(
      '         '
      + str(flac_files)
      + ' FLAC files processed, '
      + str(lrcnew)
      + ' LRC lyrics and '
      + str(txtnew)
      + ' TXT lyrics added'
   )
   tqdm.write(
      '         '
      + str(flac_files)
      + ' FLAC files processed, '
      + str(lrctotal)
      + ' LRC lyrics and '
      + str(txttotal)
      + ' TXT lyrics present, '
      + str(nototal)
      + ' files without lyrics'
   )


def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]

   timelog('Starting analysis', flacdir)

   walkdirs(flacdir)


if __name__ == '__main__':
   main()
