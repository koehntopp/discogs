# import system libraries
import subprocess
import json
import time
import sys
import os
import re
import shutil

# import music libraries
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
# https://github.com/KristoforMaynard/music-tag
import music_tag

flacdir = ""

# import config file containing default working directory )
#from config import workdir

def main():
   if len(sys.argv) != 2:
      print("path to FLAC files missing")
      exit(1)
   else:
      flacdir = sys.argv[1]

   # walk through directory given as ARGV and all subdirs
   currentDirectory = os.getcwd()
   for (subdir, dirs, files) in os.walk(flacdir):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            # load the tags
            tag = music_tag.load_file(filepath)
            tag_album = str(tag['album']).replace(" ", "_")
            tag_artist = str(tag['albumartist']).replace(" ", "_")
            tag_title = str(tag['tracktitle']).replace(" ", "_")
            tag_trackno = str(int(tag['tracknumber'])).zfill(2)
            tag_discno = str(int(tag['discnumber'])).zfill(2)
            correct_filename = tag_discno + "_" + tag_trackno + "_" + tag_title + ".flac"
            correct_filepath = flacdir + os.sep + tag_artist + os.sep + tag_album + os.sep + tag_discno + "_" + tag_trackno + "_" + tag_title + ".flac"
            if filepath != correct_filepath:
               
               shutil.move(filepath, correct_filepath)

if __name__ == "__main__":
    main()

