import os 

import mutagen
from mutagen.flac import FLAC

from tinytag import TinyTag

def main():
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
               print(current_artist + " - " + current_album )
               audio = FLAC(filepath)
               if ("DISCOGS_RELEASE_ID" in audio):
                  discogs_id = audio["DISCOGS_RELEASE_ID"]
                  print (int(discogs_id[0]))
               if ("DISCOGS_RELEASE_ID" in audio):
                  discogs_id = audio["DISCOGS_RELEASE_ID"]
                  print (discogs_id)


if __name__ == "__main__":
    main()

