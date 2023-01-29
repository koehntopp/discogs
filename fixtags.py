# import system libraries
import subprocess
import json
import time
import sys
import os
import re
import glob
import numpy as np
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
# https://github.com/KristoforMaynard/music-tag
import music_tag

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# calculate dynamic range
from drmeter import calc_drscore

def timelog(txt1, txt2):
   log_msg = "[green]" + txt1 + "[/green]"
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white] " + log_msg + txt2)

def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   idx = 0
   dr_sum = 0
   dr_tracks = 0
   dr_dirty = False
   # calculate title DR (if possible)
   for p in Path(albumpath).rglob( '*.flac' ):
      DRMED = 0
      fullfilename = str(PurePosixPath(p))
      dr_tags = FLAC(fullfilename)
      try: 
         DRMED = int(dr_tags['DYNAMIC RANGE'][0])
      except:
         try:
            DR, Peak, RMS , DRMED= calc_drscore(fullfilename)
            dr_tags['DYNAMIC RANGE'] = str(round(DRMED)).zfill(2)
            dr_tags.save()
         except:
            dr_dirty = True
      idx += 1
      dr_tracks += 1
      dr_sum += DRMED
   if not dr_dirty:
      dr_album = round(dr_sum / dr_tracks)
   else:
      dr_album = 0
   return(dr_album)

def walkdirs(fixdir):
   current_album = ""
   current_artist = ""
   current_discogs_id = 12345
   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   # find all directories containing flac files below fixdir
   files = glob.glob(os.path.join(fixdir, '**', '*.flac'), recursive=True)
   paths = list(set(map(os.path.dirname, files)))
   for i in range(len(paths)):
      timelog('Processing files in', paths[i])
      firstflac = next(Path(paths[i]).rglob('*.flac'), None)
      dynamicrange = calculate_dr(paths[i])
      tags = FLAC(firstflac)
      try:
         discogs_idstring = tags["DISCOGS_RELEASE_ID"]
         discogs_id = (int(discogs_idstring[0]))
         tag_album = str(tags['album'])
         tag_artist = str(tags['albumartist'])
         bitrate = int(tags.info.sample_rate / 1000)
         drelease = dclient.release(discogs_id)
         # make Discogs API rate limit happy
         time.sleep(3)
         album_catno = ""
         labels_json = json.dumps(drelease.labels[0].data)
         labels = json.loads(labels_json)
         album_label = (labels["name"])
         album_catno = " " + (labels["catno"])
         album_name = drelease.title.strip()
         album_artist = tags['ALBUMARTIST'][0]
         #get the release date from the master release which will be used for all files
         # release date goes into the album name instead
         album_year_release = (drelease.year)
         mrelease = drelease.master
         if drelease.master:
            album_year_master = (mrelease.main_release.year)
         else:
            album_year_master = album_year_release
         if album_year_release == 0 and album_year_master != 0:
            album_year_release = album_year_master
         if album_year_release == 0:
            album_year_release_str = ""
         else:
            album_year_release_str = str(album_year_release)
         if album_year_release != 0 and album_year_master == 0:
            album_year_master = album_year_release
         try:
            album_description = tags['SUBTITLE'][0].strip() + ' '
         except:
            album_description = ''
         album_newtitle = album_name + ' (' + album_year_release_str + " " + album_description + str(bitrate) + "kHz" + ')'
         songs = 0
         # write new tags to files
         for (subdir, dirs, files) in os.walk(paths[i]):
            for filename in files:
               filepath = paths[i] + os.sep + filename
               if filepath.endswith(".flac"):
                  mtags = music_tag.load_file(filepath)
                  mtags.remove_tag('YEAR')
                  mtags.save()
                  tags = FLAC(filepath)
                  try:
                     subtitle = tags['SET SUBTITLE'][0].strip()
                  except:
                     subtitle = ''
                  tags['DISCSUBTITLE'] = subtitle
                  tags['YEAR'] = str(album_year_release)
                  tags['DATE'] = str(album_year_release)
                  tags['ORIGINALDATE'] = str(album_year_master)
                  tags['VERSION'] = album_description.strip()
                  tags['ALBUM'] = album_newtitle
                  tags['ORIGINAL_TITLE'] = album_name
                  tags['ALBUM DYNAMIC RANGE'] = str(dynamicrange).zfill(2)
                  tags.save()
                  songs += 1
         timelog('Tags updated', album_artist + " - " + album_newtitle + ' DR' + str(dynamicrange).zfill(2) + ' (' + str(songs) + ' songs)')
      except:
         timelog('No Discogs tags in', paths[i])

def main():
   if len(sys.argv) != 2:
      #      print("path to FLAC files missing")
      #      exit(1)      flacdir = '/koehntopp/00NZB/complete/'
      #flacdir = '/Volumes/k'
      from config import flacdir
   else:
      flacdir = sys.argv[1]

   timelog('Starting analysis', flacdir)

   walkdirs(flacdir)

if __name__ == "__main__":
   main()
