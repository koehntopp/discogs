# import system libraries
import time
import sys
import os
import re
import glob
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
import requests
from urllib.parse import quote, urlencode

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# extract a single FLAC tag
def flactag(song, tag):
   try:
      return(song.tags[tag][0])
   except: 
      #timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
      return("")

def hasSubDirs(dir_name):
   subdirs = list(os.walk(dir_name))
   return(len(list(os.walk(dir_name))) > 1)

# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

def get_lrclyrics(flactags, albumtitle):
   # try to find better lyrics data for one song
   duration = str(round(flactags.length))
   # query lrclib.net https://github.com/tranxuanthang/lrcget
   url_template = 'https://lrclib.net/api/get?{}'
   headers = {
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36"
   }
   params = {'artist_name': flactags.tags['ARTIST'], 'track_name': flactags.tags['TITLE'], 'album_name': albumtitle, 'duration': duration}
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
   first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
   if first_flac != None:
      first_flac_path = os.path.join(fixdir, first_flac)
   else:
      return(lrcnew + txtnew)
   tags = taglib.File(first_flac_path)
   discogs = True
   try:
      discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
   except:
      discogs = False
      return(lrcnew + txtnew)
   # if we found discogs tags to work with go ahead
   if discogs:
      tag_album = flactag(tags, "ALBUM")
      tag_artist = flactag(tags, "ALBUMARTIST")
      samplerate = int(tags.sampleRate / 1000)
      drelease = dclient.release(discogs_id)
      # make Discogs API rate limit happy
      time.sleep(3)
      album_name = flactag(tags, 'ORIGINAL FILENAME').strip()
      if album_name == "":
         album_name = drelease.title.strip()
      artist = flactag(tags, 'ARTIST')
      songs = 0
      # write new tags to files
      for p in Path(fixdir).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         tags = taglib.File(fullfilename)
         dirty = False
         try:
            lyrics = flactag(tags, 'LYRICS').strip()
         except KeyError:
            lyrics = ''
         if lyrics == '' or not re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
            lrc, lrctype = get_lrclyrics(tags, album_name)
            if lrctype == 'lrc':
               tags.tags['LYRICS'] = [lrc]
               lrcnew += 1
               lrctotal += 1
               dirty = True
               tqdm.write('           LRC lyrics added for ' + tags.tags['TITLE'][0] + ' (' + artist + ')')
            elif lrctype == 'plain' and lyrics == '':
               tags.tags['LYRICS'] = [lrc]
               txtnew += 1
               txttotal += 1
               dirty = True
               tqdm.write('           TXT lyrics added for ' + tags.tags['TITLE'][0] + ' (' + artist + ')')
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
            #// TODO: update MP3
         flac_files += 1
   else:
      timelog('No Discogs tags found in ', shortpath)
   tqdm.write('         ' + str(flac_files) + ' FLAC files processed, ' + str(lrcnew) + ' LRC lyrics and ' + str(txtnew) + ' TXT lyrics added' )
   tqdm.write('         ' + str(flac_files) + ' FLAC files processed, ' + str(lrctotal) + ' LRC lyrics and ' + str(txttotal) + ' TXT lyrics present, ' + str(nototal) + ' files without lyrics')
   return(lrcnew + txtnew)

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
