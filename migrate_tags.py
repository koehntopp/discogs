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

# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir):
   flac_files = 0

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

                  if dirty:
                     tags.save()
                     #// TODO: update MP3
                  flac_files += 1
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
