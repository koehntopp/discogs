# import system libraries
import subprocess
import json
import time
import sys
import os
import re
import numpy as np
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath


# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
# https://github.com/KristoforMaynard/music-tag
import music_tag

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# import config file containing APISEEDS apiseeds_key for lyrics (String with API token from https://happi.dev/panel )
#from config import apiseeds_key


def main():
   if len(sys.argv) != 2:
      #      print("path to FLAC files missing")
      #      exit(1)
      flacdir = '/Volumes/roon'
   else:
      flacdir = sys.argv[1]

   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   current_album = ""
   current_artist = ""
   current_discogs_id = 12345

   log_msg = " [green]Starting analysis[/green]"
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)

   # walk through directory given as ARGV and all subdirs
   currentDirectory = os.getcwd()
   for (subdir, dirs, files) in os.walk(flacdir):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            # load the tags
            tag = music_tag.load_file(filepath)
            tag_album = str(tag['album'])
            tag_artist = str(tag['albumartist'])
            # get FLAC metadata
            audio = FLAC(filepath)
            if ("DISCOGS_RELEASE_ID" in audio):
               discogs_idstring = audio["DISCOGS_RELEASE_ID"]
               discogs_id = (int(discogs_idstring[0]))

            # Do we have a new album to process?
            if (tag_artist != current_artist) or (tag_album != current_album) or (current_discogs_id != discogs_id):
               log_msg = " [red]Working on[/red]"
               log_msg = log_msg + ' ' * 14 + subdir
               rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                      "[/white]" + log_msg)
               current_album = tag_album
               current_artist = tag_artist
               current_discogs_id = discogs_id
               special_title = ""
               new_title = ""
               discogs_relnotes = ""
               album_comments = ''

               bitrate = int(audio.info.sample_rate / 1000)

               # does it have a Discogs release assigned we can use for tagging?
               if ("DISCOGS_RELEASE_ID" in audio):
                  drelease = dclient.release(discogs_id)
                  # make Discogs API rate limit happy
                  time.sleep(3)
                  # get media type and catalog number (publisher names too long)
                  formats_json = json.dumps(drelease.formats[0])
                  formats = json.loads(formats_json)
                  album_media = (formats["name"]).strip()
                  labels_json = json.dumps(drelease.labels[0].data)
                  labels = json.loads(labels_json)
                  album_label = (labels["name"])
                  album_catno = " " + (labels["catno"])
                  if "none" in album_catno:


                     album_catno = ""
                  # get the release date from the master release which will be used for all files
                  # release date goes into the album name instead
                  try:
                     if drelease.notes.strip() != '':
                        album_comments = drelease.notes.strip()
                  except:
                     pass      
                  album_year_release = (drelease.year)
                  mrelease = drelease.master
                  if drelease.master:
                     album_year_master = (mrelease.main_release.year)
                  else:
                     album_year_master = album_year_release
                  if album_year_release == 0 and album_year_master != 0:
                     album_year_release = album_year_master
                  if album_year_release == 0:
                     album_year_release_str = ""
                  else:
                     album_year_release_str = str(album_year_release)
                  if album_year_release != 0 and album_year_master == 0:
                     album_year_master = album_year_release
                  album_name = drelease.title.strip()
                  if new_title:
                     album_name = new_title
                  album_artist = current_artist.strip()
                  if special_title and album_year_release_str:
                     special_title = " " + special_title

                  album_newtitle = album_name

                  # finish
                  idx = 0
                  for flacfile in files:
                     if flacfile.endswith(".flac"):
                        filename = os.path.join(
                            currentDirectory, subdir, flacfile)
                        tags = music_tag.load_file(filename)
                        tags.remove_tag('year')
                        tags['album'] = album_newtitle
                        tags['year'] = str(album_year_release)
                        if album_comments != '':
                           tags['comment'] = album_comments
                        tags.save()
                        flactags = FLAC(filename)
                        album_description = ''
                        try:
                           album_description = flactags["subtitle"][0].strip() + ' '
                        except:
                           pass
                        special_title = album_year_release_str + " " + album_description + str(bitrate) + "kHz" + album_catno
                        flactags['VERSION'] = special_title
                        flactags['ORIGINALRELEASEDATE'] = str(album_year_master)
                        flactags['DATE'] = str(album_year_release)
                        album_subtitle =''
                        try:
                           album_subtitle = flactags['SET SUBTITLE']
                        except:
                           pass
                        flactags['DISC SUBTITLE'] = album_subtitle
                        flactags.save()

                  log_msg = " [yellow]Tags updated[/yellow]"
                  log_msg = log_msg + ' ' * 12
                  rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + album_newtitle + " [" + special_title + "]")
                  current_album = album_newtitle
               else:
                  log_msg = " [red]No Discogs tags[/red]".ljust(20)
                  log_msg = log_msg + ' ' * 9
                  rprint("[white]" + datetime.now().strftime("%H:%M:%S") +
                         "[/white]" + log_msg + current_artist + " - " + current_album)
   log_msg = " [green]Done.[/green]"
   rprint("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


if __name__ == "__main__":
   main()
