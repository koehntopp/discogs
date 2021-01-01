import os
import json

import mutagen
from mutagen.flac import FLAC

from tinytag import TinyTag

import discogs_client
global dclient

def main():
   dclient = discogs_client.Client('xampleApplication/0.1')
   current_album = ""
   current_artist = ""
   for (subdir,dirs,files) in os.walk('flac'):
      for filename in files:
         filepath = subdir + os.sep + filename
         if filepath.endswith(".flac"):
            tag = TinyTag.get(filepath)
            if (tag.albumartist != current_artist) or (tag.album != current_album):
               current_album = tag.album
               current_artist = tag.albumartist
               audio = FLAC(filepath)
               if ("DISCOGS_RELEASE_ID" in audio):
                  discogs_idstring = audio["DISCOGS_RELEASE_ID"]
                  discogs_id = (int(discogs_idstring[0]))
                  drelease = dclient.release(discogs_id)
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
                  album_name = current_album
                  album_artist = current_artist
                  print (album_artist + " - " + album_name + " (" + str(album_year_release) + " " + album_media + " " + album_catno + ")")


if __name__ == "__main__":
    main()

