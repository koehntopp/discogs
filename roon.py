from pathlib import Path, PurePosixPath
import music_tag
from mutagen import mp3
from mutagen.flac import FLAC, StreamInfo
from pathvalidate import sanitize_filename
import unicodedata
from rich import print as rprint
import os
import shutil
import time
from datetime import datetime

# Global variables
flacroot = '/Volumes/roon'


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
   clean_text = clean_text.replace('+', 'and')
   clean_text = clean_text.replace('\´', '')
   clean_text = clean_text.replace('\"', '')
   clean_text = clean_text.replace(',', '')
   clean_text = clean_text.replace(' ', '_')
   return clean_text


def movefiles(flacroot):
   log_msg = " [green]Checking FLAC folders in[/green]"
   log_msg = log_msg + ' ' * 6
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + flacroot)
   currentalbum = ""
   for p in Path(flacroot).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      tags = music_tag.load_file(fullfilename)
      # read tags to build folder name
      audio = FLAC(fullfilename)
      tag_release_date = str(audio['DATE'][0])
      tag_dr_album = int(audio['ALBUM DYNAMIC RANGE'][0])
      try:
         tag_label = clean(audio['DISCOGS_CATALOG_NUMBER'][0])
      except:
         tag_label = ""
      folder_add = '_' + tag_release_date + \
          '_DR' + str(tag_dr_album).zfill(2) + '_' + tag_label
      stracktitle = clean(str(tags['tracktitle']))
      salbumtitle = clean(str(tags['album']))
      sartist = clean(str(tags['albumartist']))
      # Check file name and path and move if wrong
      tobefilename = (str(tags['discnumber']).zfill(
          2) + '_' + str(tags['tracknumber']).zfill(2) + '_' + stracktitle + '.flac')
      tobepathname = (flacroot + '/' + sartist + '/' +
                      salbumtitle + folder_add + '/')
      tobefullname = tobepathname + tobefilename
      if unicodedata.normalize('NFD', fullfilename) != unicodedata.normalize('NFD', tobefullname):
         if salbumtitle != currentalbum:
            currentalbum = salbumtitle
            a = unicodedata.normalize('NFD', fullfilename)
            b = unicodedata.normalize('NFD', tobefullname)
            log_msg = " [red]Moving album[/red]"
            log_msg = log_msg + ' ' * 18
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                   "[/white]" + log_msg + str(tags['album']))
         if not os.path.exists(tobepathname):
            os.makedirs(tobepathname)
         shutil.move(fullfilename, tobefullname)
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def checktags(flacroot):
   log_msg = " [green]Checking FLAC files in[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + flacroot)
   currentalbum = ""
   check = False
   albumcount = 0
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      song = str(PurePosixPath(p).name)
      # get tags
      fullfilename = str(PurePosixPath(p))
      tags = music_tag.load_file(fullfilename)
      stracktitle = clean(str(tags['tracktitle']))
      salbumtitle = clean(str(tags['album']))
      album = str(tags['album'])
      sartist = clean(str(tags['albumartist']))
      # Check artwork
      arterror = ""
      artwork = tags['artwork']
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1
      # Check album art size
      try:
         if (artwork.first.width < 500) and (arterror != salbumtitle):
            arterror = salbumtitle
            if salbumtitle != currentalbum:
               check = True
               log_msg = " [red]Art too small[/red]"
               log_msg = log_msg + ' ' * 17
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(
                   artwork.first.width) + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']))
      except AttributeError:
         log_msg = " [red]Art error[/red]"
         log_msg = log_msg + ' ' * 17
         rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" +
                log_msg + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']))

      # Check for lyrics
      lyrics = str(tags['lyrics'])
#      lyricslrc = str(tags['sylt'])
      if lyrics == "":
         log_msg = " [red]No lyrics[/red]"
         log_msg = log_msg + ' ' * 17
#         rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']) + ' - ' + stracktitle)
      else:
         log_msg = " [red]May have lrc[/red]"
         log_msg = log_msg + ' ' * 14
#            rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']) + ' - ' + stracktitle + ' - ' + lyrics[:20])

      # Check for cover.jpg
      if album != album.strip():
         if salbumtitle != currentalbum:
            check = True
            log_msg = " [red]Whitespace error[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                   "[/white]" + log_msg + album)
      # Check nodiscogs
      comment = str(tags['comment'])
      if "nodiscogs" in comment:
         if salbumtitle != currentalbum:
            check = True
            log_msg = " [red]No Discogs tags[/red]"
            log_msg = log_msg + ' ' * 15
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                   "[/white]" + log_msg + album)
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1
      # reset flag so errors are only reported once per album
      if check:
         check = False
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 25
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + str(albumcount) + " albums scanned.")


def removedirs(rootdir):
   log_msg = " [green]Removing empty dirs in[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + rootdir)
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
                     rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                            "[/white]" + log_msg + str(root + dirname))
                  except OSError as err:
                     print(err)
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def checkMP3():
   global mp3root, flacroot
   log_msg = " [green]Checking MP3 folders in[/green]"
   log_msg = log_msg + ' ' * 7
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + mp3root)
   for (root, dirs, files) in os.walk(mp3root, topdown=True):
      for dirname in dirs:
         if not hasSubDirs(root + '/' + dirname):
            mp3dir = os.path.join(mp3root, root, dirname)
            p = Path(mp3dir)
            firstmp3 = str(next(p.glob('*.mp3')))
            firstflac = firstmp3.replace(mp3root, flacroot)
            firstflac = firstflac.replace('.mp3', '.flac')
            mp3time = time.strftime(
                '%Y%m%d', time.localtime(os.path.getmtime(firstmp3)))
            flactime = "00000000"
            if os.path.isfile(firstflac):
               flactime = time.strftime(
                   '%Y%m%d', time.localtime(os.path.getmtime(firstflac)))
               tags = music_tag.load_file(firstflac)
               salbumtitle = clean(str(tags['album']))
               sartist = clean(str(tags['albumartist']))
            else:
               tags = music_tag.load_file(firstmp3)
               salbumtitle = clean(str(tags['album']))
               sartist = clean(str(tags['albumartist']))
               log_msg = " [red]MP3 but no FLAC - deleting[/red]"
               log_msg = log_msg + ' ' * 4
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                      "[/white]" + log_msg + sartist + " - " + salbumtitle)
               try:
                  shutil.rmtree(mp3dir)
               except OSError as err:
                  print(err)
            if mp3time < flactime:
               log_msg = " [red]FLAC dir newer - deleting[/red]"
               log_msg = log_msg + ' ' * 5
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                      "[/white]" + log_msg + sartist + " - " + salbumtitle)
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
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
          "[/white]" + log_msg + mp3root)
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      flacfilename = str(PurePosixPath(p))
      mp3filename = flacfilename.replace(flacroot, mp3root)
      mp3filename = mp3filename.replace(".flac", ".mp3")
      try:
         if not os.path.isfile(mp3filename):
            tags = music_tag.load_file(flacfilename)
            stracktitle = clean(str(tags['tracktitle']))
            salbumtitle = clean(str(tags['album']))
            sartist = clean(str(tags['albumartist']))
            tobepathname = (mp3root + sartist + '/' + salbumtitle + '/')
            if not os.path.exists(tobepathname):
               os.makedirs(tobepathname)
            log_msg = " [red]Creating MP3 for[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" +
                   log_msg + str(tags['album']) + ' - ' + str(tags['tracktitle']))
            flac2mp3 = "ffmpeg -i " + flacfilename + \
                " -codec:a libmp3lame -qscale:a 2 -vsync 2 " + mp3filename + " > /dev/null 2>&1"
            os.system(flac2mp3)
      except:
         break
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def main():
   movefiles(flacroot)
   checktags(flacroot)
   removedirs(flacroot)
#   checkMP3()
#   removedirs(mp3root)
#   createMP3()


if __name__ == "__main__":
   main()
