# import system libraries
import subprocess
import json
import time
import sys
import os

# import music libraries
import discogs_client
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
import music_tag

# import Discogs file containing api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

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

   # walk through directory given as ARGV and all subdirs
   currentDirectory = os.getcwd()
   for (subdir, dirs, files) in os.walk(flacdir):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            tag = music_tag.load_file(filepath)
            tag_album = str(tag['album'])
            tag_artist = str(tag['albumartist'])
            # Do we have a new album to process?
            if (tag_artist != current_artist) or (tag_album != current_album):
               current_album = tag_album
               current_artist = tag_artist
               special_title = ""
               discogs_relnotes = ""
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
                     message = "[Skipped, no Discogs release] - "
                     print (message + current_artist + " - " + current_album)
                     break
                  if discogs_comments_raw[0:3] == "###":
                     discogs_comments_raw = discogs_comments_raw[3:100]
                     comment_pos = discogs_comments_raw.find('###')
                     if comment_pos:
                        special_title = discogs_comments_raw[0:comment_pos]
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
                  if album_year_release == 0:
                     album_year_release_str = ""
                  else:
                     album_year_release_str = str(album_year_release)
                  mrelease = drelease.master
                  if drelease.master:
                     album_year_master = (mrelease.main_release.year)
                  else:
                     album_year_master = album_year_release
                  album_name = drelease.title.strip()
                  album_artist = current_artist.strip()
                  if special_title and album_year_release_str:
                     special_title = " " + special_title
                  # build the new album title from Discogs album name, release year, sample rate and catalog number
                  album_newtitle = album_name + " ("+ album_year_release_str + special_title + " " + str(bitrate) + " kHz" + album_catno + ")"
                  if current_album != album_newtitle:
                     message = "[Tags updated for]            - "
                     for flacfile in files:
                        if flacfile.endswith(".flac"):
                           filename = os.path.join(currentDirectory, subdir, flacfile)
                           tags = music_tag.load_file(filename)
                           tags.remove_tag('year')
                           tags['album'] = album_newtitle
                           tags['year'] = str(album_year_master)
                           tags.save()
                  else:
                     message = "[Tags OK for        ]         - "
               else:
                  message = "[Skipped, no Discogs tags]    - "
                  album_newtitle = current_album
               print (message + current_artist + " - " + album_newtitle)
               message = ""

if __name__ == "__main__":
    main()

