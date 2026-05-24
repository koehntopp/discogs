# /// script
# dependencies = [
#   "rich",
#   "tqdm",
#   "pytaglib",
#   "requests",
#   "pyacoustid",
# ]
# ///

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

# https://github.com/beetbox/pyacoustid/tree/master
import acoustid

# logging function
def timelog(txt1: str, txt2: str, colour: str = 'white') -> None:
   """Print a timestamped log line with rich colour formatting.

   Args:
       txt1: Label text displayed in the given colour.
       txt2: Value text appended after the label.
       colour: Rich colour name applied to both the timestamp and label; defaults to 'white'.
   """
   log_msg = f'[{colour}]' + txt1 + f'[/{colour}]'
   log_msg = log_msg + ' ' * (40 - len(txt1))
   rprint(f'[white]{datetime.now().strftime("%H:%M:%S")}[/white] ' + log_msg + txt2)

# calculate acoustic fingerprints and write tags to files
def calculate_fp(albumpath: str) -> None:
   """Generate and store AcoustID fingerprints for every FLAC file in an album directory.

   Reads the existing ACOUSTID FINGERPRINT tag from each file; if absent, calls
   fpcalc via pyacoustid to compute a fingerprint and writes it back to the file.
   Logs the number of fingerprints generated vs total tracks processed.

   Args:
       albumpath: Absolute path to the album directory (searched recursively).
   """
   total = 0
   calculated = 0
   # assumption: folder only contains a single album
   # iterate over FLAC files, calculate title DR (if possible)
   for p in Path(albumpath).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      dr_tags = taglib.File(fullfilename)
      total += 1
      fingerprint = ""
      try:
         fingerprint = dr_tags.tags['ACOUSTID FINGERPRINT'][0].strip()
      except (KeyError, IndexError):
         if fingerprint == "":
            try:
               duration, fingerprint = acoustid.fingerprint_file(fullfilename, maxlength=10000, force_fpcalc=False)
               dr_tags.tags['ACOUSTID FINGERPRINT'] = [fingerprint]
               dr_tags.save()
               calculated += 1
            except acoustid.FingerprintGenerationError:
               timelog("Fingerprint could not be calculated - ", fullfilename)      
   timelog("AcoustID fingerprints generated for ", str(calculated) + " of " + str(total) + " files.")

def main() -> None:
   """Entry point: walk a FLAC directory tree and generate AcoustID fingerprints.

   Reads the root directory from config.flacdir or a single positional command-line
   argument, discovers all album directories containing FLAC files, and calls
   calculate_fp() for each one in sequence.
   """
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]
   flac_directories = []
   for root, dirs, files in os.walk(flacdir):
      for file in files:
         if file.endswith(".flac"):
            flac_directories.append(root)
            break
   for directory in flac_directories:
      timelog('Starting AcoustID fingerprint generation in ', directory)
      calculate_fp(directory)
   print("")

if __name__ == '__main__':
   main()
