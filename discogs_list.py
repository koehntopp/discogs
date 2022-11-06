# import system libraries
import subprocess
import json
import time
import sys
import os

# import music libraries
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
import music_tag

def main():
   if len(sys.argv) != 2:
      print("path to FLAC files missing")
      exit(1)
   else:
      flacdir = sys.argv[1]

   # initialize Discogs API
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
               # get FLAC metadata
               audio = FLAC(filepath)
               # Look in the comments for either ##nodiscogs## (leave me alone) or ###<title>### (special title to assign)
               discogs_comments_raw = str(audio.vc)
               comment_pos = discogs_comments_raw.find('COMMENT')
               if comment_pos:
                  discogs_comments_raw = discogs_comments_raw[comment_pos:10000]
                  comment_pos = discogs_comments_raw.find('\')')
                  discogs_comments_raw = discogs_comments_raw[11:comment_pos]
                  # no Discogs release available? Skip album.
                  if "##nodiscogs##" in discogs_comments_raw:
                     print ("##nodiscogs##" + current_artist.ljust(50, ' ') + " - " + current_album)
                  else: 
                     print (current_artist.ljust(50, ' ') + " - " + current_album)

if __name__ == "__main__":
    main()

