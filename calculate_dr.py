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

# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

# calculate song and album dynamic range and write tags to files
def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   dr_sum = 0
   dr_tracks = 0
   # iterate over FLAC files, calculate title DR (if possible)
   for p in Path(albumpath).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      dr_tags = taglib.File(fullfilename)
      dr_song = 0
      DR = 0
      dra_dirty = False
      try:
         dr_song = int(dr_tags.tags["DYNAMIC RANGE"][0])
      except:
         with sf.SoundFile(fullfilename) as data:
            try:
               result = dynamic_range(AudioData.from_soundfile(data))
               DR = round(result.overall_dr_score)
            except: 
               pass
         if int(DR) != dr_song and DR != 0:
            timelog('DR old ' + str(dr_song).zfill(2) + ' --> new ' + str(DR).zfill(2), dr_tags.tags["TITLE"][0])
            dr_tags.tags["DYNAMIC RANGE"] = [str(DR).zfill(2)]
            dr_tags.save()
            dr_song = int(DR)
            dra_dirty = True
      dr_tracks += 1
      dr_sum += dr_song
   if dr_tracks > 0:
      dr_album = str(int(dr_sum / dr_tracks)).zfill(2)
   else:
      timelog("ERROR calculating DR!", albumpath + ": " + str(dr_album))
   if dra_dirty:
      for p in Path(albumpath).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         dr_tags = taglib.File(fullfilename)
         dr_tags.tags["ALBUM DYNAMIC RANGE"] = [str(dr_album).zfill(2)]
         dr_tags.save()
      timelog("Album DR calculated for ", albumpath + ": " + str(dr_album))
   else:
      timelog("Album DR for ", albumpath + ": " + str(dr_album))


def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]
   timelog('Starting analysis', flacdir)
   # find all directories containing flac files below fixdir
   flac_directories = []
   for root, dirs, files in os.walk(flacdir):
      for file in files:
         if file.endswith(".flac"):
            flac_directories.append(root)
            break
   for directory in flac_directories:
      calculate_dr(directory)
   timelog('Finished analysis', flacdir)

if __name__ == '__main__':
   main()
