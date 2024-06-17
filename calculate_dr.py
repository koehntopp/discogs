# import system libraries
import sys
import os
import glob
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
import requests
from urllib.parse import quote, urlencode

# https://github.com/supermihi/pytaglib
import taglib

# import DRMETER https://github.com/janw/drmeter/
from drmeter.algorithm import dynamic_range
from drmeter.models import AudioData
import soundfile as sf

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

# calculate song and album dynamic range and write tags to files
def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   dr_sum = 0
   dr_tracks = 0
   # iterate over FLAC files, calculate title DR (if possible)
   for p in Path(albumpath).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      dr_tags = taglib.File(fullfilename)
      drsong = 0
      DR = 0
      try:
         drsong = int(flactag(dr_tags, "DYNAMIC RANGE"))
      except (TypeError, KeyError, ValueError):
         with sf.SoundFile(fullfilename) as data:
            try:
               result = dynamic_range(AudioData.from_soundfile(data))
               DR = round(result.overall_dr_score)
               dr_dirty = True
            except: 
               timelog('libsoundfile Error:', fullfilename)
               DR = 0
         if int(DR) != drsong and DR != 0:
            timelog('DR old ' + str(drsong).zfill(2) + ' --> new ' + str(DR).zfill(2), flactag(dr_tags, "TITLE"))
            dr_tags.tags["DYNAMIC RANGE"] = [str(DR).zfill(2)]
            dr_tags.save()
      if DR > 0 or drsong > 0:
         dr_tracks += 1
         dr_sum += DR
         dr_sum += drsong
   # done iterating, do we have more than one track with DR?
   if dr_tracks > 0:
      dra_dirty = False
      # newly calculated album DR
      dr_album = round(dr_sum / dr_tracks)
      # compare to existing album DR
      for p in Path(albumpath).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         dr_tags = taglib.File(fullfilename)
         try:
            dra = int(flactag(dr_tags, "ALBUM DYNAMIC RANGE"))
         except: 
            dra = 0
         if dra != dr_album:
            dr_tags.tags['ALBUM DYNAMIC RANGE'] = [str(dr_album).zfill(2)]
            dr_tags.save()
            dra_dirty = True
      if dra_dirty:
         timelog("Album DR calculated for ", albumpath + ": " + str(dr_album))
      else:
         timelog("Album DR for ", albumpath + ": " + str(dr_album))

def listdirs(flacdir):
   flac_directories = []
   for pattern in glob.iglob(os.path.join(flacdir, "**", "*.flac")):
   # Extract the directory path from the matched FLAC file path
      dirpath = os.path.dirname(pattern)
      flac_directories.append(dirpath)
   return list(set(flac_directories))


# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir):
   # find all directories containing flac files below fixdir
   flacdirs = listdirs(fixdir)
   
   for flacdir in flacdirs:
      calculate_dr(flacdir)

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
