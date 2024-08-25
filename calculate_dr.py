# import system libraries
import sys
import os
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm

# https://github.com/supermihi/pytaglib
import taglib

# import DRMETER https://github.com/janw/drmeter/
from drmeter.algorithm import dynamic_range
from drmeter.models import AudioData
import soundfile as sf

def hasSubDirs(dir_name):
   subdirs = list(os.walk(dir_name))
   return(len(list(os.walk(dir_name))) > 1)

# logging function
def timelog(txt1, txt2, color = "green"):
   log_msg = '[' + color + ']' + txt1 + '[/' + color + ']'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

# calculate song and album dynamic range and write tags to files
def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   dr_sum = 0
   dr_tracks = 0
   tracks = 0
   # iterate over FLAC files, calculate title DR (if possible)
   for p in Path(albumpath).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      dr_tags = taglib.File(fullfilename)
      tracks += 1
      dr_song = 0
      DR = 0
      dra_dirty = False
      try:
         # do we have a song DR entry
         dr_song = int(dr_tags.tags["DYNAMIC RANGE"][0])
      except:
         # if we don't, calculate it
         with sf.SoundFile(fullfilename) as data:
            try:
               result = dynamic_range(AudioData.from_soundfile(data))
               DR = int(round(result.overall_dr_score))
            except Exception as e: 
               print(e)
               timelog('Error calculating DR:', dr_tags.tags["TITLE"][0], "red")
         if DR != dr_song:
            timelog('DR old ' + str(dr_song).zfill(2) + ' --> new ' + str(DR).zfill(2), dr_tags.tags["TITLE"][0])
            dr_tags.tags["DYNAMIC RANGE"] = [str(DR).zfill(2)]
            dr_tags.save()
            dr_song = DR
            dra_dirty = True
      if dr_song > 0:
         dr_tracks += 1
         dr_sum += dr_song
   if dr_tracks != tracks:
      timelog('ERROR: Total tracks ' + str(tracks) + ' , tracks with DR ' + str(dr_tracks), "", "red")
   else:
      if dr_tracks > 0:
         dr_album = str(round(dr_sum / dr_tracks)).zfill(2)
         try:
            dr_album_old = dr_tags.tags["ALBUM DYNAMIC RANGE"][0]
         except:
            dr_album_old = ""
         timelog("Album DR in files:", dr_album_old)
         if dra_dirty or dr_album != dr_album_old:
            for p in Path(albumpath).rglob('*.flac'):
               fullfilename = str(PurePosixPath(p))
               dr_tags = taglib.File(fullfilename)
               dr_tags.tags["ALBUM DYNAMIC RANGE"] = [str(dr_album).zfill(2)]
               dr_tags.save()
            timelog("Album DR updated to:", str(dr_album), "red")
         else:
            timelog("Album DR for " +  dr_tags.tags["ALBUM"][0] + ":", str(dr_album))
      else:
         timelog("ERROR calculating DR!", albumpath + ": " + str(dr_album))


def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]
   # find all directories containing flac files below fixdir
   flac_directories = []
   for root, dirs, files in os.walk(flacdir):
      for file in files:
         if file.endswith(".flac"):
            flac_directories.append(root)
            break
   for directory in flac_directories:
      timelog('Starting Dynamic Range calculation in ', directory)
      calculate_dr(directory)
   print("")  

if __name__ == '__main__':
   main()
