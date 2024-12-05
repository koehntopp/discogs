# import system libraries
import time
import sys
import os
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

# extract a single FLAC tag
def flactag(song, tag):
   try:
      return(song.tags[tag][0])
   except: 
      #timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
      return("")

# fix tags for a single album (in a single directory)
def fixdir(fixdir):
   flac_files = 0
   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
   if first_flac != None:
      first_flac_path = os.path.join(fixdir, first_flac)
   else:
      return
   tags = taglib.File(first_flac_path)
   discogs = True
   try:
      discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
   except:
      discogs = False
      return
   # if we found discogs tags to work with go ahead
   if discogs:
      samplerate = int(tags.sampleRate / 1000)
      drelease = dclient.release(discogs_id)
      # make Discogs API rate limit happy
      time.sleep(1)
      # if for some reason the Discogs filename has weird additions we can overwrite it with ORIGINAL FILENAME
      discogs_name = drelease.master.title.strip()
      album_name = flactag(tags, 'ORIGINAL FILENAME').strip()
      if album_name == "":
         album_name = discogs_name
      album_artist = flactag(tags, 'ALBUMARTIST')
      # get the release date from the master release which will be used for all files
      # release date goes into the album name instead
      album_year_release = drelease.year
      mrelease = drelease.master
      if drelease.master:
         album_year_master = mrelease.main_release.year
      else:
         album_year_master = album_year_release
      if album_year_release == 0 and album_year_master != 0:
         album_year_release = album_year_master
      if album_year_release == 0:
         album_year_release_str = ''
      else:
         album_year_release_str = str(album_year_release) + ' '
      if album_year_release != 0 and album_year_master == 0:
         album_year_master = album_year_release
      try:
         album_description = flactag(tags, 'SUBTITLE').strip() + ' '
      except:
         album_description = ''
      if album_description.strip() == '':
         album_description = 'CD '
      try:
         album_dr = " DR" + flactag(tags, "ALBUM DYNAMIC RANGE").strip()
      except:
         album_dr = ""
         timelog("No album DR!", album_artist + " - " + album_name + " " + album_description)

      album_newtitle = (album_name + ' [' + album_year_release_str + album_description + str(samplerate) + 'kHz' + album_dr + ']')
      songs = 0
      # write new tags to files

      for p in Path(fixdir).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         tags = taglib.File(fullfilename)
         try:
            del tags.tags["YEAR"]
         except:
            pass
         try:
            del tags.tags["DATE"]
         except:
            pass
         tags.tags['RELEASEDATE'] = [str(album_year_release)]
         tags.tags['DATE'] = [str(album_year_release)]
         tags.tags['ORIGINALDATE'] = [str(album_year_master)]
         tags.tags['ORIGINALRELEASEDATE'] = [str(album_year_master)]
         tags.tags['ALBUM'] = [album_newtitle]
         tags.tags['ORIGINAL_TITLE'] = [discogs_name]
         tags.save()
         flac_files += 1
      timelog("Album title is ", album_newtitle)
   else:
      timelog('No Discogs tags found in ', shortpath)

def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]
   flac_directories = []
   for root, dirs, files in os.walk(flacdir):
      for file in files:
         if file.endswith(".flac"):
            flac_directories.append(root)
            break
   for directory in flac_directories:
      timelog('Starting to fix tags in ', directory)
      fixdir(directory)
   print("")

if __name__ == '__main__':
   main()
