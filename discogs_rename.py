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

# calculate dynamic range
from drmeter import calc_drscore

# import config file containing APISEEDS apiseeds_key for lyrics (String with API token from https://happi.dev/panel )
#from config import apiseeds_key

def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   idx = 0
   dr_sum = 0
   dr_tracks = 0
   dr_dirty = False
   # calculate title DR (if possible)
   for p in Path(albumpath).rglob( '*.flac' ):
      DRMED = 0
      fullfilename = str(PurePosixPath(p))
      dr_tags = FLAC(fullfilename)
      m_tag = music_tag.load_file(fullfilename)
      current_album = str(m_tag['album'])
      current_artist = str(m_tag['albumartist'])

      try: 
         DRMED = int(dr_tags['DYNAMIC RANGE'][0])
      except:
         try:
            DR, Peak, RMS , DRMED= calc_drscore(fullfilename)
            dr_tags['DYNAMIC RANGE'] = str(round(DRMED)).zfill(2)
            dr_tags.save()
         except:
            dr_dirty = True
      idx += 1
      dr_tracks += 1
      dr_sum += DRMED
   if not dr_dirty:
      dr_album = round(dr_sum / dr_tracks)
   else:
      dr_album = 0

   for p in Path(albumpath).rglob( '*.flac' ):
      fullfilename = str(PurePosixPath(p))
      dr_tags = FLAC(fullfilename)       
      try:
         dr_album_tag = int(dr_tags['ALBUM DYNAMIC RANGE'][0])
         if dr_album_tag < 5:
            log_msg = " [red]DR < 5[/red]"
            log_msg = log_msg + ' ' * 18 
            rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + current_album)            
      except:
         dr_tags['ALBUM DYNAMIC RANGE'] = str(dr_album).zfill(2)
         dr_tags.save()
   
   return(dr_album)
   

def main():
   if len(sys.argv) != 2:
      print("path to FLAC files missing")
      exit(1)
   else:
      flacdir = sys.argv[1]

   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   current_album = ""
   current_artist = ""

   log_msg = " [green]Starting analysis[/green]"
   rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)


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

            # Do we have a new album to process?
            if (tag_artist != current_artist) or (tag_album != current_album):
               log_msg = " [red]Working on[/red]"
               log_msg = log_msg + ' ' * 14 + subdir
               rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)
               current_album = tag_album
               current_artist = tag_artist
               special_title = ""
               new_title = ""
               discogs_relnotes = ""

               # Dynamic range
               dr_album = calculate_dr(subdir)
               if dr_album != 0:
                  album_dr = " DR" + str(dr_album).zfill(2)
               else:
                  log_msg = " [red]Error calculating DR[/red]"
                  log_msg = log_msg + ' ' * 4 + current_artist + " - " + current_album
                  rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)
                  album_dr = ""
                     
               # get FLAC metadata
               audio = FLAC(filepath)
               bitrate = int(audio.info.sample_rate / 1000)

               # Look in the comments for either ##nodiscogs## (leave me alone) or ###<title>### (special title to assign)
               discogs_comments_raw = str(audio.vc)
               comment_pos = discogs_comments_raw.find('COMMENT')
               if comment_pos:
                  discogs_comments_raw = discogs_comments_raw[comment_pos:10000]
                  comment_pos = discogs_comments_raw.find('\')')
                  discogs_comments_raw = discogs_comments_raw[11:comment_pos]
                  # no Discogs release available? Skip album.
                  if "##nodiscogs##" in discogs_comments_raw:
                     log_msg = " [red]No Discogs tags[/red]"
                     log_msg = log_msg + ' ' * 9 
                     rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + current_album)
                     break
                  if discogs_comments_raw[0:3] == "###":
                     discogs_comments_raw = discogs_comments_raw[3:100]
                     comment_pos = discogs_comments_raw.find('###')
                     if comment_pos:
                        special_title = discogs_comments_raw[0:comment_pos]
                  # If you need to overwrite the Discogs album name enclose a new name between <newtitle></newtitle> tags 
                  tmp = re.findall(r'<newtitle>(.+?)</newtitle>',discogs_comments_raw)
                  if tmp:
                     new_title = tmp[0]

               # does it have a Discogs release assigned we can use for tagging?
               if ("DISCOGS_RELEASE_ID" in audio):
                  discogs_idstring = audio["DISCOGS_RELEASE_ID"]
                  discogs_id = (int(discogs_idstring[0]))
                  drelease = dclient.release(discogs_id)
                  # make Discogs API rate limit happy
                  time.sleep(3)
                  # get media type and catalog number (publisher names too long)
                  formats_json = json.dumps (drelease.formats[0])
                  formats = json.loads (formats_json)
                  album_media = (formats["name"]).strip()
                  labels_json = json.dumps (drelease.labels[0].data)
                  labels = json.loads (labels_json)
                  album_label = (labels["name"])
                  album_catno = " " + (labels["catno"])
                  # Add 'MFSL' before catalog number for Mobile Fidelity Sound Labs releases
                  if ("Vinyl" in album_media):
                     album_catno = " Vinyl" + album_catno
                  if ("SACD" in album_media):
                     album_catno = " SACD" + album_catno
                  if ("Mobile Fidelity" in album_label) and not ("MFSL" in album_catno):
                     album_catno = " MFSL" + album_catno
                  # Digital releases have no catalog number, often 'HDTracks' is in the Discogs Release Notes
                  if (('HDTracks' in special_title) or ('Tidal' in special_title) or ('Qobuz' in special_title) or ('Download' in special_title)):
                     album_catno = ""
                  if "none" in album_catno:
                     album_catno = ""
                  # get the release date from the master release which will be used for all files
                  # release date goes into the album name instead
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

                  # build the new album title from Discogs album name, release year, sample rate and catalog number
                  album_newtitle = album_name + " ("+ album_year_release_str + special_title + " " + str(bitrate) + "kHz" + album_dr + album_catno + ")"

                  # finish
                  if current_album != album_newtitle:
                     idx = 0
                     log_msg = " [yellow]Tags updated[/yellow]"
                     log_msg = log_msg + ' ' * 12 
                     rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + album_newtitle)
                     for flacfile in files:
                        if flacfile.endswith(".flac"):
                           filename = os.path.join(currentDirectory, subdir, flacfile)
                           tags = music_tag.load_file(filename)
                           tags.remove_tag('year')
                           tags['album'] = album_newtitle
                           tags['year'] = str(album_year_master)
                           tags.save()
                     current_album = album_newtitle
                  else:
                     log_msg = " [green]Tags OK[/green]"
                     log_msg = log_msg + ' ' * 17 
                     rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + current_album)
               else:
                  log_msg = " [red]No Discogs tags[/red]".ljust(20)
                  log_msg = log_msg + ' ' * 9
                  rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg + current_artist + " - " + current_album)
   log_msg = " [green]Done.[/green]"
   rprint ("[white]" + datetime.now().strftime("%H:%M:%S") + "[/white]" + log_msg)

if __name__ == "__main__":
    main()

