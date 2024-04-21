# walks along $flacroot and identifies the number of channels in album to identify 5.1 and mono versions
from pathlib import Path, PurePosixPath
import music_tag
from mutagen.flac import FLAC
from pathvalidate import sanitize_filename
from rich import print as rprint
import os
from datetime import datetime

from config import flacroot

def hasSubDirs(dir_name):
   return(len(list(os.walk(dir_name))) > 1)

def clean(dirty_text):
   # Clean file and path names of stupid characters
   clean_text = sanitize_filename(dirty_text)
   clean_text = clean_text.replace('.', '')
   clean_text = clean_text.replace('(', '')
   clean_text = clean_text.replace(')', '')
   clean_text = clean_text.replace('\'', '')
   clean_text = clean_text.replace('&', 'and')
   clean_text = clean_text.replace('+', 'and')
   clean_text = clean_text.replace('\´', '')
   clean_text = clean_text.replace('\"', '')
   clean_text = clean_text.replace(',', '')
   clean_text = clean_text.replace(' ', '_')
   return clean_text

def checktags(flacroot):
   log_msg = " [green]Checking FLAC files in[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + flacroot)
   currentalbum = ""
   check = False
   albumcount = 0
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      # get tags
      fullfilename = str(PurePosixPath(p))
      tags = music_tag.load_file(fullfilename)
      sinfo = FLAC(fullfilename).info
      salbumtitle = clean(str(tags['album']))
      sartist = clean(str(tags['albumartist']))
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1 
         if sinfo.channels == 6:
            check = True
            log_msg = " [red]5.1 Version [/red]"
            log_msg = log_msg + ' ' * 18
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + sartist + ' - ' + artistdir)
         if sinfo.channels == 1:
            check = True
            log_msg = " [red]Mono Version [/red]"
            log_msg = log_msg + ' ' * 17
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + sartist + ' - ' + artistdir)
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1
      # reset flag so errors are only reported once per album
      if check:
         check = False
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 25
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(albumcount) + " albums scanned.")


def main():
   checktags(flacroot)


if __name__ == "__main__":
   main()
