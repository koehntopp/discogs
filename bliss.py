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
flacroot = '/Volumes/FLAC/'
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
   clean_text = clean_text.replace(' ', '_')
   return clean_text

def moveflacfiles(flacroot):
    timelog("Checking FLAC folders in", flacroot)

    # Iterate over directories containing FLAC files
    directories_with_flac = set([p.parent for p in Path(flacroot).rglob('*.flac')])

    for directory in tqdm(directories_with_flac, desc="Processing FLAC directories", unit="directory"):
        try:
            # Get the first .flac file in the directory
            first_flac = next(directory.glob('*.flac'), None)
            if not first_flac:
                continue  # Skip if no .flac files are found (shouldn't happen)

            fullfilename = str(PurePosixPath(first_flac))

            # Open the first FLAC file and get its metadata
            with taglib.File(fullfilename) as metadata:
                # Get required tags with fallbacks for missing metadata
                tags = metadata.tags
                stracktitle = clean(str(tags.get('TITLE', ['Unknown Title'])[0]))
                salbumtitle = clean(str(tags.get('ALBUM', ['Unknown Album'])[0]))
                sartist = clean(str(tags.get('ALBUMARTIST', tags.get('ARTIST', ['Unknown Artist']))[0]))
                disc_num = str(tags.get('DISCNUMBER', ['1'])[0]).zfill(2)
                track_num = str(tags.get('TRACKNUMBER', ['0'])[0]).zfill(2)

            # Construct new file path for this directory
            tobepathname = Path(flacroot) / sartist / salbumtitle
            new_fullname = str(tobepathname / f"{disc_num}_{track_num}_{stracktitle}.flac")

            # If the first FLAC file is in its correct location, skip further processing
            if unicodedata.normalize('NFD', fullfilename.lower()) == unicodedata.normalize('NFD', new_fullname.lower()):
                continue

            # Process all files in the directory
            timelog("Processing album", salbumtitle)
            tobepathname.mkdir(parents=True, exist_ok=True)
            for flac_file in directory.glob('*.flac'):
                try:
                    fullfilename = str(PurePosixPath(flac_file))
                    with taglib.File(fullfilename) as metadata:
                        tags = metadata.tags
                        stracktitle = clean(str(tags.get('TITLE', ['Unknown Title'])[0]))
                        disc_num = str(tags.get('DISCNUMBER', ['1'])[0]).zfill(2)
                        track_num = str(tags.get('TRACKNUMBER', ['0'])[0]).zfill(2)

                    # Construct new filename and move the file
                    tobefilename = f"{disc_num}_{track_num}_{stracktitle}.flac"
                    tobefullname = str(tobepathname / tobefilename)
                    shutil.move(fullfilename, tobefullname)

                except Exception as e:
                    timelog("Error processing file", f"{fullfilename}: {str(e)}")

        except Exception as e:
            timelog("Error processing directory", f"{directory}: {str(e)}")
            continue

    timelog("Done.", "")

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
    
    args = parser.parse_args()
    
    # If no arguments provided, show help
    if not any(vars(args).values()):
        moveflacfiles(flacroot)
        removedirs(flacroot)
        return
    
    # Run selected operations
    if args.mp3:
        checkMP3()
        removedirs(mp3root)
        createMP3()

if __name__ == "__main__":
    main()