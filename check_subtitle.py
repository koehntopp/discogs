# import system libraries
import time
import sys
import os
import glob
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

from mutagen.flac import FLAC

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# extract a single FLAC tag
def flactag(song, tag):
   try:
      return(song.tags[tag][0])
   except: 
      #timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
      return("")

# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir):
   flac_files = 0

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
      tags = taglib.File(firstflac)
      discogs = True
      try:
         discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
      except:
         discogs = False
      # if we found discogs tags to work with go ahead
      if discogs:
         drelease = dclient.release(discogs_id)
         # make Discogs API rate limit happy
         time.sleep(3)
         album_name = flactag(tags, 'ORIGINAL FILENAME').strip()
         if album_name == "":
            album_name = drelease.title.strip()
         album_artist = flactag(tags, 'ALBUMARTIST')
         songs = 0
         # write new tags to files
         for subdir, dirs, files in os.walk(paths[i]):
            for filename in files:
               filepath = paths[i] + os.sep + filename
               if filepath.endswith('.flac'):
                  tags = taglib.File(filepath)
                  sub = ""
                  try:
                     subtitle = flactag(tags, 'SET SUBTITLE').strip()
                  except KeyError:
                     subtitle = ''
                  if subtitle and subtitle != sub:
                     sub = subtitle
                     timelog("Subtitle:", album_name + " - " + subtitle)





      else:
         timelog('No Discogs tags found in ', shortpath)
   timelog('Finished analysis', fixdir)


def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]

   timelog('Starting analysis', flacdir)

   walkdirs(flacdir)


if __name__ == '__main__':
   main()
