import config.py

import os
import sys
import time
import json
import subprocess

import music_tag

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIT2

from tinytag import TinyTag

import discogs_client

import argparse
parser = argparse.ArgumentParser(description='Process some integers.')

def query_yes_no(question, default="yes"):
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

def main():
   if len(sys.argv) != 2:
      print ("path to FLAC files missing")
      exit(1)
   else:
      args = sys.argv[1]   
   # initialize 
   dclient = discogs_client.Client('xampleApplication/0.1', user_token = api_key)
   current_album = ""
   current_artist = ""
   currentDirectory = os.getcwd()
   for (subdir,dirs,files) in os.walk(args):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            tag = TinyTag.get(filepath)
            if (tag.albumartist != current_artist) or (tag.album != current_album):
               current_album = tag.album
               current_artist = tag.albumartist
               bitrate = int(tag.samplerate / 1000)
               audio = FLAC(filepath)
               if ("DISCOGS_RELEASE_ID" in audio):
                  discogs_idstring = audio["DISCOGS_RELEASE_ID"]
                  discogs_id = (int(discogs_idstring[0]))
                  drelease = dclient.release(discogs_id)
                  time.sleep(1)
                  mrelease = drelease.master
                  album_year_release = (drelease.year)
                  formats_json = json.dumps (drelease.formats[0])
                  formats = json.loads (formats_json)
                  album_media = (formats["name"])
                  labels_json = json.dumps (drelease.labels[0].data)
                  labels = json.loads (labels_json)
                  album_label = (labels["name"])
                  album_catno = (labels["catno"])
                  album_year_master = (mrelease.main_release.year)
                  album_name = drelease.title
                  album_artist = current_artist
                  album_newtitle = album_name + " (" + str(album_year_release) + " " + album_media + " " + str(bitrate) + " kHz " + album_catno + ")"
                  for flacfile in files:
                     if flacfile.endswith(".flac"):
                        filename = os.path.join(currentDirectory, subdir, flacfile)
                        tags = music_tag.load_file(filename)
                        tags.remove_tag('year')
                        tags['album'] = album_newtitle
                        tags['year'] = str(album_year_master)
                        tags.save()
               else:
                  if query_yes_no("No Discogs release assigned. Start Tagger?"):
                     directory = os.path.join(currentDirectory, subdir)
                     return_code = subprocess.call("/Applications/Yate.app/Contents/MacOS/Yate" + " \"" + directory + "\"", shell=True) 


if __name__ == "__main__":
    main()

