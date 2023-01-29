# import system libraries
import subprocess
import json
import time
import sys
import os
import re
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

# import config file containing APISEEDS apiseeds_key for lyrics (String with API token from https://happi.dev/panel )
#from config import apiseeds_key

def timelog(txt1, txt2):
   log_msg = "[green]" + txt1 + "[/green]"
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white] " + log_msg + txt2)

def main():
   if len(sys.argv) != 2:
      #      print("path to FLAC files missing")
      #      exit(1)
      flacdir = '/Volumes/koehntopp/00NZB/'
      #flacdir = '/Volumes/FLAC/Asia/'
   else:
      flacdir = sys.argv[1]

   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   current_album = ""
   current_artist = ""
   current_discogs_id = 12345

   timelog('Starting analysis', '')

def mp3gen():
    for root, dirs, files in os.walk('.'):
        for filename in files:
            if os.path.splitext(filename)[1] == ".mp3":
                yield os.path.join(root, filename)



   # walk through directory given as ARGV and all subdirs
   currentDirectory = os.getcwd()
   for (subdir, dirs, files) in os.walk(flacdir):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            # load the tags
            tags = music_tag.load_file(filepath)
            tag_album = str(tags['album'])
            tag_artist = str(tags['albumartist'])
            # Do we have a new album to process?
            if (tag_artist != current_artist) or (tag_album != current_album) or (current_discogs_id != discogs_id):
               timelog('New album found in', subdir)
               try:
                  discogs_idstring = tags["DISCOGS_RELEASE_ID"]
                  discogs_id = (int(discogs_idstring[0]))
                  current_album = tag_album
                  current_artist = tag_artist
                  current_discogs_id = discogs_id
                  bitrate = int(tags.info.sample_rate / 1000)
                  drelease = dclient.release(discogs_id)
                  # make Discogs API rate limit happy
                  time.sleep(3)
                  # get catalog number (publisher names too long)
                  album_catno = ""
                  labels_json = json.dumps(drelease.labels[0].data)
                  labels = json.loads(labels_json)
                  album_label = (labels["name"])
                  album_catno = " " + (labels["catno"])
                  album_name = drelease.title.strip()
                  album_artist = current_artist.strip()
                  # get the release date from the master release which will be used for all files
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
                  if special_title and album_year_release_str:
                     special_title = " " + special_title
                  # build the new album title
                  try:
                     album_description = tags["SUBTITLE"][1].strip() + ' '
                  except:
                     album_description = ''
                  album_newtitle = album_name + ' (' + album_year_release_str + " " + album_description + str(bitrate) + "kHz" + ')'
                  # write new tags to files
                  for flacfile in files:
                     if flacfile.endswith(".flac"):
                        filename = os.path.join(currentDirectory, subdir, flacfile)
                        tags = music_tag.load_file(filename)
                        tags.remove_tag('YEAR')
                        tags['YEAR'] = str(album_year_release)
                        tags['DATE'] = str(album_year_release)
                        tags['ORIGINALDATE'] = str(album_year_master)
                        tags['VERSION'] = special_title
                        tags['ALBUM'] = album_newtitle
                        tags['ORIGINAL_TITLE'] = album_name
                        tags.save()
                  timelog('Tags updated', current_artist + " - " + album_newtitle)
                  current_album = album_newtitle
               except:
                  timelog('No Discogs tags', filepath)
   timelog('Done.', '')

if __name__ == "__main__":
   main()
