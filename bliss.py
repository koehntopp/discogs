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
import csv
from datetime import datetime
from shlex import quote
import subprocess
import glob
import re
from tqdm import tqdm

# Global variables
flacroot = '/flac/'
#flacroot = '/Volumes/koehntopp/00NZB/complete/'
mp3root = '/mp3/'

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
   clean_text = clean_text.replace('+', 'and')
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
      tags = music_tag.load_file(fullfilename)
      stracktitle = clean(str(tags['tracktitle']))
      salbumtitle = clean(str(tags['album']))
      sartist = clean(str(tags['albumartist']))
      ftags = FLAC(fullfilename)
      # Check file name and path and move if wrong
      tobefilename = (str(tags['discnumber']).zfill(2) + '_' + str(tags['tracknumber']).zfill(2) + '_' + stracktitle + '.flac')
      tobepathname = (flacroot + sartist + '/' + salbumtitle + '/')
      tobefullname = tobepathname + tobefilename
      if unicodedata.normalize('NFD', fullfilename) != unicodedata.normalize('NFD', tobefullname):
         if salbumtitle != currentalbum:
            currentalbum = salbumtitle
            a = unicodedata.normalize('NFD', fullfilename)
            b = unicodedata.normalize('NFD', tobefullname)
            timelog("Moving album", str(tags['album']))
         if not os.path.exists(tobepathname):
            os.makedirs(tobepathname)
         shutil.move(fullfilename, tobefullname)
   timelog("Done.", "")

def addtocsv(flacfile):
   ftags = FLAC(flacfile)
   tags = music_tag.load_file(flacfile)
   csvzeile = [str(ftags['albumartist'][0])]
   try:
      csvzeile += [str(ftags['albumartistsort'][0])]
   except:
      csvzeile += ['']
   csvzeile += [str(ftags['album'][0])]
   try:
      csvzeile += [str(ftags['totaltracks'][0])]
   except:
      csvzeile += ["ERROR"]
   csvzeile += [str(ftags['disctotal'][0])]
   try:
      csvzeile += [str(ftags['ALBUM DYNAMIC RANGE'][0])]
   except:
      csvzeile += ['']
   try:
      csvzeile += [str(ftags['ORIGINALDATE'][0])]
   except:
      csvzeile += ['']
      timelog("No original release date!", flacfile)
   try:
      csvzeile += [str(ftags['DATE'][0])]
   except:
      csvzeile += ['ERROR']
   csvzeile += [str(int(ftags.info.bits_per_sample))]
   csvzeile += [str(int(ftags.info.sample_rate / 1000))]
   csvzeile += [str(ftags.info.channels)]
   try:
      csvzeile += [str(len(ftags.pictures))]
      csvzeile += [str(ftags.pictures[0].width)]
      csvzeile += [str(ftags.pictures[0].height)]
   except:
      csvzeile += ['', '', '']
      timelog("Picture problem", flacfile)
   try:
      csvzeile += [ftags["SUBTITLE"][0].strip()]
   except:
      csvzeile += ['']
   try:
      csvzeile += [ftags["DISCOGS_MASTER_ID"][0].strip()]
   except:
      csvzeile += ['']
   try:
      csvzeile += [ftags["DISCOGS_RELEASE_ID"][0].strip()]
   except:
      csvzeile += ['']
   try:
      csvzeile += [ftags["MUSICBRAINZ_RELEASE_GROUPID"][0].strip()]
   except:
      csvzeile += ['']
   try:
      csvzeile += [ftags["MUSICBRAINZ_ALBUMID"][0].strip()]
   except:
      csvzeile += ['']
   #print(csvzeile)
   return(csvzeile)


def checktags(flacroot):
   log_msg = " [green]Checking FLAC files in[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + flacroot)
   currentalbum = ""
   check = False
   albumcount = 0
#   t = tqdm(total=1, unit="album", disable=not show_progress)
   f = open('albums.csv', 'w')
   csvwriter = csv.writer(f)
   csvstring = ['Artist', 'Sort Artist', 'Album', 'Tracks', 'Discs', 'Album DR', 'Date Master', 'Date Release', 'Bit Depth', 'Sample Rate', 'Channels', '# Covers', 'Cover Width', 'Cover Height', 'Description', 'Discogs Master', 'Discogs Release', 'Musicbrainz Release Group', 'Musicbrainz Album']
   csvwriter.writerow(csvstring)
   for p in Path(flacroot).rglob('*.flac'):
      artistdir = (PurePosixPath(p).parent).stem
      song = str(PurePosixPath(p).name)
      # get tags
      fullfilename = str(PurePosixPath(p))
      tags = music_tag.load_file(fullfilename)
      flactags = FLAC(fullfilename)
      stracktitle = clean(str(tags['tracktitle']))
      salbumtitle = clean(str(tags['album']))
      album = str(tags['album'])
      sartist = clean(str(tags['albumartist']))
      # Check artwork
      arterror = ""      
      artwork = flactags.pictures[0].width
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1
#         t.update()
         csvwriter.writerow(addtocsv(fullfilename))
      # Check album art size
      try:
         if (artwork < 500) and (arterror != salbumtitle):
            arterror = salbumtitle
            if salbumtitle != currentalbum:
               check = True
               log_msg = " [red]Art too small[/red]"
               log_msg = log_msg + ' ' * 17
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(artwork) + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']))
      except AttributeError:
         log_msg = " [red]Art error[/red]"
         log_msg = log_msg + ' ' * 17
         rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']))

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
      try:
         csvstring1 = str(flactags['ORIGINALDATE'][0])
         #csvstring = sartist + ',' + salbumtitle + ',' + flactags['ORIGINALRELEASEDATE'][0] + ',' + flactags['DATE'][0] + ',' + flactags['VERSION'][0]
      except:
         log_msg = " [red]tag error[/red]"
         log_msg = log_msg + ' ' * 17
         rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + ' in ' + str(tags['albumartist']) + ' - ' + str(tags['album']))

      # Check for cover.jpg
      if album != album.strip():
         if salbumtitle != currentalbum:
            check = True
            log_msg = " [red]Whitespace error[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + album)
      # Check nodiscogs
      comment = str(tags['comment'])
      if "nodiscogs" in comment:
         if salbumtitle != currentalbum:
            check = True
            log_msg = " [red]No Discogs tags[/red]"
            log_msg = log_msg + ' ' * 15
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + album)
      # Do we have a new album?
      if salbumtitle != currentalbum:
         currentalbum = salbumtitle
         albumcount += 1
      # reset flag so errors are only reported once per album
      if check:
         check = False
   f.close()
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 25
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(albumcount) + " albums scanned.")


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
               tags = music_tag.load_file(firstflac)
               salbumtitle = clean(str(tags['album']))
               sartist = clean(str(tags['albumartist']))
            else:
               # if we don't we can delete the mp3
               tags = music_tag.load_file(firstmp3)
               salbumtitle = clean(str(tags['album']))
               sartist = clean(str(tags['albumartist']))
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

def add_replaygain(flacroot):
   timelog("Adding ReplayGain in", flacroot)
   for (root, dirs, files) in os.walk(flacroot, topdown=True):
      for dirname in dirs:
         # are we in an album directory? Only then album level ReplayGain works correctly
         #if not hasSubDirs(root + '/' + dirname):
         flacdir = os.path.abspath(os.path.join(flacroot, root, dirname))
         # check if there are FLAC files with 1 or 2 channels (ReplayGain does not work for 5.1)
         ffiles = glob.glob(flacdir + '/*.flac')
         if ffiles:
            channels = FLAC(ffiles[1]).info.channels
            try:
               rpgain = FLAC(ffiles[1])['REPLAYGAIN_ALBUM_GAIN'][0]
               timelog("ReplayGain exists in ", flacdir)
            except:
               if channels == 1 or channels == 2:
                  timelog("Adding ReplayGain for", flacdir)
                  escapedir = re.escape(flacdir)
                  try:
                     metaflac = 'metaflac --add-replay-gain \"' + escapedir + '/\"*.flac'
                     subprocess.run(metaflac, shell=True, check=True)
                  except OSError as err:
                     print(err)
               else:
                  timelog("# of channels in FLAC files:", str(channels) + " (" + flacdir + ")")
         else:
            timelog("No FLAC files in", flacdir)
   timelog("Done.","")


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
            tags = music_tag.load_file(flacfilename)
            stracktitle = clean(str(tags['tracktitle']))
            salbumtitle = clean(str(tags['album']))
            sartist = clean(str(tags['albumartist']))
            ftags = FLAC(flacfilename)
            #tag_version = clean(ftags['VERSION'][0])
            tobepathname = (mp3root + sartist + '/' + salbumtitle)
            if not os.path.exists(tobepathname):
               os.makedirs(tobepathname)
            log_msg = " [red]Creating MP3 for[/red]"
            log_msg = log_msg + ' ' * 14
            rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + str(tags['album']) + ' - ' + str(tags['tracktitle']))
            flac2mp3 = "ffmpeg -i " + flacfilename + " -codec:a libmp3lame -qscale:a 2 -vsync 2 " + mp3filename + " > /dev/null 2>&1"
            os.system(flac2mp3)
      except Exception as e: 
         timelog('EXCEPTION RAISED:', str(e))
      #except:
         #break
   log_msg = " [green]Done.[/green]"
   log_msg = log_msg + ' ' * 8
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


def main():
   movefiles(flacroot)
   checktags(flacroot)
   removedirs(flacroot)
   checkMP3()
   removedirs(mp3root)
   createMP3()


if __name__ == "__main__":
   main()
