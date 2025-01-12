from pathlib import Path, PurePosixPath
from pathvalidate import sanitize_filename
import unicodedata
from rich import print as rprint
import os
import shutil
import time
from datetime import datetime
from tqdm import tqdm

# https://github.com/supermihi/pytaglib
import taglib

# Global variables
flacroot = '/Volumes/FLAC/'
mp3root = '/Volumes/MP3/'
opusroot = '/Volumes/Opus/'

def timelog(txt1, txt2):
   log_msg = "[green]" + txt1 + "[/green]"
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white] " + log_msg + txt2)


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


def movefiles(flacroot):
   timelog("Checking FLAC folders in", flacroot)
   currentalbum = ""
   #   t = tqdm(total=1, unit="album", disable=not show_progress)
   for p in Path(flacroot).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      metadata = taglib.File(fullfilename)
      stracktitle = clean(str(metadata.tags['TITLE'][0]))
      salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
      sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
      tobefilename = (str(metadata.tags['DISCNUMBER'][0]).zfill(2) + '_' + str(metadata.tags['TRACKNUMBER'][0]).zfill(2) + '_' + stracktitle + '.flac')
      tobepathname = (flacroot + sartist + '/' + salbumtitle + '/')
      tobefullname = tobepathname + tobefilename
      if unicodedata.normalize('NFD', fullfilename.lower()) != unicodedata.normalize('NFD', tobefullname.lower()):
         if salbumtitle != currentalbum:
            currentalbum = salbumtitle
            timelog("Moving album", salbumtitle)
         if not os.path.exists(tobepathname):
            os.makedirs(tobepathname)
         shutil.move(fullfilename, tobefullname)
   timelog("Done.", "")

def removedirs(rootdir):
   log_msg = " [green]Removing empty dirs in[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + rootdir)
   isdirty = os.truncate
   while isdirty:
      for (root, dirs, files) in os.walk(rootdir, topdown=True):
         isdirty = False
         for dirname in dirs:
            if not hasSubDirs(root + '/' + dirname):
               if (not list(Path(root + '/' + dirname).rglob("*.flac"))) and (not list(Path(root + '/' + dirname).rglob("*.mp3"))):
                  try:
                     shutil.rmtree(root + '/' + dirname)
                     isdirty = True
                     log_msg = " [red]Removing directory[/red]"
                     log_msg = log_msg + ' ' * 12
                     rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(root + dirname))
                  except OSError as err:
                     print(err)
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)

def checkMP3():   
   global mp3root, flacroot
   log_msg = " [green]Checking MP3 folders in[/green]"
   log_msg = log_msg + ' ' * 7
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + mp3root)
   for (root, dirs, files) in os.walk(mp3root, topdown=True):
      for dirname in dirs:
         # are we in an album directory?
         if not hasSubDirs(root + '/' + dirname):
            mp3dir = os.path.join(mp3root, root, dirname)
            p = Path(mp3dir)
            try:
               firstmp3 = str(next(p.glob('*.mp3')))
            except:
               return
            firstflac = firstmp3.replace(mp3root, flacroot)
            firstflac = firstflac.replace('.mp3', '.flac')
            mp3time = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(firstmp3)))
            flactime = "00000000"
            # does the mp3 file we find have a flac representation?
            if os.path.isfile(firstflac):
               # get the timestamp for the flac file
               flactime = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(firstflac)))
               metadata = taglib.File(firstflac)
               salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
               sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
            else:
               # if we don't we can delete the mp3
               try:
                  metadata = taglib.File(firstmp3)
               except:
                  print("ERROR " + firstmp3)    
               salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
               sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
               log_msg = " [red]MP3 but no FLAC - deleting[/red]"
               log_msg = log_msg + ' ' * 4
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + sartist + " - " + salbumtitle)
               try:
                  shutil.rmtree(mp3dir)
               except OSError as err:
                  print(err)
            if mp3time < flactime:
               # if the flac file is newer we need to re-create the mp3
               log_msg = " [red]FLAC dir newer - deleting[/red]"
               log_msg = log_msg + ' ' * 5
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + sartist + " - " + salbumtitle)
               try:
                  shutil.rmtree(mp3dir)
               except OSError as err:
                  print(err)
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def createMP3():
   global mp3root, flacroot
   log_msg = " [green]Creating missing MP3s in[/green]"
   log_msg = log_msg + ' ' * 6
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + mp3root)
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      flacfilename = str(PurePosixPath(p))
      mp3filename = flacfilename.replace(flacroot, mp3root)
      mp3filename = mp3filename.replace(".flac", ".mp3")
      try:
         if not os.path.isfile(mp3filename):
            metadata = taglib.File(flacfilename)
            stracktitle = clean(str(metadata.tags['TITLE'][0]))
            salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
            sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
            tobepathname = (mp3root + sartist + '/' + salbumtitle)
            if not os.path.exists(tobepathname):
               os.makedirs(tobepathname)
            log_msg = " [red]Creating MP3 for[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + salbumtitle + ' - ' + stracktitle)
            flac2mp3 = "ffmpeg -i " + flacfilename + " -codec:a libmp3lame -qscale:a 2 -vsync 2 " + mp3filename + " > /dev/null 2>&1"
            os.system(flac2mp3)
      except Exception as e: 
         timelog('EXCEPTION RAISED:', str(e))
      #except:
         #break
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)

def createOpus():
   global opusroot, flacroot
   log_msg = " [green]Creating missing Opus files in[/green]"
   log_msg = log_msg + ' ' * 6
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + opusroot)
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      flacfilename = str(PurePosixPath(p))
      opusfilename = flacfilename.replace(flacroot, opusroot)
      opusfilename = opusfilename.replace(".flac", ".mp3")
      try:
         if not os.path.isfile(opusfilename):
            metadata = taglib.File(flacfilename)
            stracktitle = clean(str(metadata.tags['TITLE'][0]))
            salbumtitle = clean(str(metadata.tags['ALBUM'][0]))
            sartist = clean(str(metadata.tags['ALBUMARTIST'][0]))
            tobepathname = (opusroot + sartist + '/' + salbumtitle)
            if not os.path.exists(tobepathname):
               os.makedirs(tobepathname)
            log_msg = " [red]Creating Opus for[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + salbumtitle + ' - ' + stracktitle)
            flac2mp3 = "ffmpeg -i " + flacfilename + " -codec:a libmp3lame -qscale:a 2 -vsync 2 " + mp3filename + " > /dev/null 2>&1"
            os.system(flac2opus)
      except Exception as e: 
         timelog('EXCEPTION RAISED:', str(e))
      #except:
         #break
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def main():
   movefiles(flacroot)
   removedirs(flacroot)
   checkMP3()
   removedirs(mp3root)
   createMP3()

if __name__ == "__main__":
   main()