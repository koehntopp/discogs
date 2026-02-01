# /// script
# dependencies = [
#   "rich",
#   "tqdm",
#   "pytaglib",
#   "requests",
#   "discogs_client",
#   "alive-progress",
#   "pyacoustid",
#   "pathvalidate"
# ]
# ///

from pathlib import Path, PurePosixPath
from pathvalidate import sanitize_filename
import unicodedata
from rich import print as rprint
import os
import shutil
import time
from datetime import datetime
from tqdm import tqdm
import argparse

# https://github.com/supermihi/pytaglib
import taglib

# Global variables
flacroot = '/Volumes/flac/'
mp3root = '/Volumes/MP3/'
opusroot = '/Volumes/Opus/'

# logging function
def timelog(txt1, txt2, color: str = 'white'):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint(f'[{color}]{datetime.now().strftime("%H:%M:%S")}[/{color}] ' + log_msg + txt2)

def hasSubDirs(dir_name):
   subdirs = list(os.walk(dir_name))
   return(len(list(os.walk(dir_name))) > 1)


def clean(dirty_text):
   # Clean file and path names of stupid characters
   clean_text = sanitize_filename(dirty_text)
   clean_text = clean_text.replace('.', '')
   clean_text = clean_text.replace('#', '')
   clean_text = clean_text.replace('(', '')
   clean_text = clean_text.replace(')', '')
   clean_text = clean_text.replace('\'', '')
   clean_text = clean_text.replace('&', 'and')
   clean_text = clean_text.replace('+', 'plus')
   clean_text = clean_text.replace('´', '')
   clean_text = clean_text.replace('’', '')
   clean_text = clean_text.replace('″', '')
   clean_text = clean_text.replace('\"', '')
   clean_text = clean_text.replace(',', '')
   clean_text = clean_text.replace(';', '')
   clean_text = clean_text.replace(':', '')
   clean_text = clean_text.replace('ä', 'ae')
   clean_text = clean_text.replace('ö', 'oe')
   clean_text = clean_text.replace('ü', 'ue')
   clean_text = clean_text.replace('Ä', 'Ae')
   clean_text = clean_text.replace('Ö', 'Oe')
   clean_text = clean_text.replace('Ü', 'Ue')
   clean_text = clean_text.replace('ß', 'ss')
   clean_text = clean_text.replace(' ', '_')
   return clean_text

def get_target_path_and_filename(flac_file, root_dir):
   """Extract metadata from FLAC and return (target_path, target_filename, metadata_dict)"""
   metadata = taglib.File(flac_file)
   track_title = clean(str(metadata.tags['TITLE'][0]))
   album_title = clean(str(metadata.tags['ALBUM'][0]))
   artist = clean(str(metadata.tags['ALBUMARTIST'][0]))
   
   filename = (str(metadata.tags['DISCNUMBER'][0]).zfill(2) + '_' + 
               str(metadata.tags['TRACKNUMBER'][0]).zfill(2) + '_' + 
               track_title + '.flac')
   path = os.path.join(root_dir, artist, album_title) + '/'
   
   return path, filename, {
      'artist': artist,
      'album': album_title,
      'track': track_title
   }

def move_flac_file(source_file, target_path, target_filename):
   """Move FLAC file to target location, creating directory if needed"""
   target_fullname = target_path + target_filename
   
   # Create target directory if it doesn't exist
   if not os.path.exists(target_path):
      os.makedirs(target_path)
   
   # Only move if paths are different (case-insensitive comparison)
   if unicodedata.normalize('NFD', source_file.lower()) != unicodedata.normalize('NFD', target_fullname.lower()):
      shutil.move(source_file, target_fullname)
      return True
   return False

def movefiles(flacroot, full: bool = False):
   # If full==False, only check for .flac files directly in the flacroot directory (non-recursive).
   # If full==True, scan the whole tree recursively.
   timelog("Checking FLAC folders in", flacroot + (" (full recursive)" if full else " (root-only)"))
   currentalbum = ""
   pattern_iter = Path(flacroot).rglob('*.flac') if full else Path(flacroot).glob('*.flac')

   for p in pattern_iter:
      fullfilename = str(PurePosixPath(p))
      try:
         # Use safer tag access with defaults
         metadata = taglib.File(fullfilename)
         stracktitle = clean(str(metadata.tags.get('TITLE', [''])[0]))
         salbumtitle = clean(str(metadata.tags.get('ALBUM', [''])[0]))
         sartist = clean(str(metadata.tags.get('ALBUMARTIST', metadata.tags.get('ARTIST', ['']))[0]))
         tobefilename = (str(metadata.tags.get('DISCNUMBER', ['0'])[0]).zfill(2) + '_' + str(metadata.tags.get('TRACKNUMBER', ['0'])[0]).zfill(2) + '_' + stracktitle + '.flac')
         tobepathname = (flacroot + sartist + '/' + salbumtitle + '/')
         tobefullname = tobepathname + tobefilename

         if unicodedata.normalize('NFD', fullfilename.lower()) != unicodedata.normalize('NFD', tobefullname.lower()):
            if salbumtitle != currentalbum:
               currentalbum = salbumtitle
               timelog("Moving album", salbumtitle)
            if not os.path.exists(tobepathname):
               os.makedirs(tobepathname)
            shutil.move(fullfilename, tobefullname)
      except Exception as e:
         timelog("Error moving file", f"{fullfilename}: {str(e)}", color='red')
         continue
   timelog("Done.", "")

def ingestfiles(ingest_dir):
   """Ingest files from a directory and organize them into flacroot"""
   global flacroot
   timelog("Ingesting FLAC files from", ingest_dir)
   currentalbum = ""
   
   if not os.path.exists(ingest_dir):
      timelog("Error: Directory does not exist", ingest_dir, color='red')
      return
   
   # Find all FLAC files in the ingest directory
   for p in Path(ingest_dir).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      try:
         target_path, target_filename, metadata = get_target_path_and_filename(fullfilename, flacroot)
         
         if metadata['album'] != currentalbum:
            currentalbum = metadata['album']
            timelog("Ingesting album", metadata['album'])
         
         if move_flac_file(fullfilename, target_path, target_filename):
            timelog("Ingested", f"{metadata['track']}", color='green')
      except Exception as e:
         timelog("Error ingesting file", f"{fullfilename}: {str(e)}", color='red')
   
   timelog("Done.", "Ingest complete")

def removedirs(rootdir):
    timelog("Removing empty dirs in", rootdir)
    is_dirty = True
    
    while is_dirty:
        is_dirty = False
        for root, dirs, _ in os.walk(rootdir, topdown=True):
            for dirname in dirs:
                dir_path = Path(root) / dirname
                
                # Check if directory has no subdirs and no music files
                if (not hasSubDirs(str(dir_path)) and 
                    not list(dir_path.rglob("*.flac")) and 
                    not list(dir_path.rglob("*.mp3"))):
                    try:
                        shutil.rmtree(dir_path)
                        is_dirty = True
                        timelog("Removing directory", str(dir_path), color='red')
                    except OSError as err:
                        timelog("Error removing directory", f"{str(dir_path)}: {err}", color='red')
    
    timelog("Done.", "")

def checkMP3():   
   global mp3root, flacroot
   log_msg = " [green]Checking MP3 folders in[/green]"
   log_msg = log_msg + ' ' * 7
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + mp3root)
   timelog("Checking MP3 folders in", mp3root)
   
   for root, dirs, _ in os.walk(mp3root, topdown=True):
       for dirname in dirs:
           # are we in an album directory?
           if not hasSubDirs(os.path.join(root, dirname)):
               mp3dir = os.path.join(root, dirname)
               p = Path(mp3dir)
               
               try:
                   firstmp3 = str(next(p.glob('*.mp3')))
               except StopIteration:
                   continue  # Skip if no MP3 files found
               
               firstflac = firstmp3.replace(mp3root, flacroot).replace('.mp3', '.flac')
               mp3time = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(firstmp3)))
               flactime = "00000000"

               try:
                   if os.path.isfile(firstflac):
                       # get the timestamp for the flac file
                       flactime = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(firstflac)))
                       metadata = taglib.File(firstflac)
                   else:
                       # if we don't have FLAC, read MP3 metadata before deleting
                       metadata = taglib.File(firstmp3)
                       
                   salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
                   sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
                   
                   if not os.path.isfile(firstflac):
                       timelog("MP3 but no FLAC - deleting", f"{sartist} - {salbumtitle}", color='red')
                       shutil.rmtree(mp3dir)
                   elif mp3time < flactime:
                       timelog("FLAC dir newer - deleting", f"{sartist} - {salbumtitle}", color='red')
                       shutil.rmtree(mp3dir)
                       
               except Exception as e:
                   timelog("Error processing directory", f"{mp3dir}: {str(e)}", color='red')
                   continue

   timelog("Done.", "")


def createMP3():
   global mp3root, flacroot
   timelog("Creating missing MP3s in", mp3root)
   
   for p in Path(flacroot).rglob('*.flac'):
      try:
         flacfilename = str(PurePosixPath(p))
         mp3filename = flacfilename.replace(flacroot, mp3root).replace(".flac", ".mp3")
         
         if not os.path.isfile(mp3filename):
            # Get metadata
            with taglib.File(flacfilename) as metadata:
               stracktitle = clean(str(metadata.tags.get('TITLE', ['Unknown Title'])[0]))
               salbumtitle = clean(str(metadata.tags.get('ALBUM', ['Unknown Album'])[0]))
               sartist = clean(str(metadata.tags.get('ALBUMARTIST', metadata.tags.get('ARTIST', ['Unknown Artist']))[0]))
            
            # Create directory structure
            tobepathname = Path(mp3root) / sartist / salbumtitle
            tobepathname.mkdir(parents=True, exist_ok=True)
            
            timelog("Creating MP3 for", f"{salbumtitle} - {stracktitle}", color='red')
            
            # Construct and execute ffmpeg command with proper escaping
            flac2mp3 = [
               "ffmpeg", "-i", flacfilename,
               "-codec:a", "libmp3lame",
               "-qscale:a", "2",
               "-vsync", "2",
               mp3filename,
               "-loglevel", "error"
            ]
            os.system(" ".join(f'"{arg}"' for arg in flac2mp3))
            
      except Exception as e:
         timelog("Error creating MP3", f"{flacfilename}: {str(e)}", color='red')
         continue

   timelog("Done.", "")

def main():
    parser = argparse.ArgumentParser(description='Music library management tool')
    parser.add_argument('--mp3', action='store_true', help='Create missing MP3 files from FLACs')
    parser.add_argument('--full', action='store_true', help='Scan entire flacroot recursively')
    parser.add_argument('--ingest', type=str, metavar='DIRECTORY', help='Ingest FLAC files from a directory into the library')

    args = parser.parse_args()

    # If --ingest is specified, use it
    if args.ingest:
        ingestfiles(args.ingest)
        removedirs(args.ingest)
        return

    # If --full is specified, do a recursive scan of flacroot
    if args.full:
        movefiles(flacroot, full=True)
        removedirs(flacroot)
        return

    # Run selected operations
    if args.mp3:
        checkMP3()
        removedirs(mp3root)
        createMP3()

    # If no arguments provided, default to root-only scan
    if not any(vars(args).values()):
        movefiles(flacroot, full=False)
        return

if __name__ == "__main__":
    main()