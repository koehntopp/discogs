# import system libraries
import subprocess
import json
import time
import sys
import os

# import music libraries
import discogs_client
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
import music_tag

# import Discogs file containing api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

def main():
   if len(sys.argv) != 2:
      print("path to FLAC files missing")
      exit(1)
   else:
      flacdir = sys.argv[1]

   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   current_album = ""
   current_artist = ""

   # walk through directory given as ARGV and all subdirs
   currentDirectory = os.getcwd()
   for (subdir, dirs, files) in os.walk(flacdir):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            tag = music_tag.load_file(filepath)
            tag_album = str(tag['album'])
            tag_artist = str(tag['albumartist'])
            # Do we have a new album to process?
            if (tag_artist != current_artist) or (tag_album != current_album):
               current_album = tag_album
               current_artist = tag_artist
               print (current_artist.ljust(50, ' ') + " - " + current_album)

if __name__ == "__main__":
    main()

