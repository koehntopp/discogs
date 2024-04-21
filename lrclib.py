from urllib.parse import quote_plus, quote, urlencode
import requests
import json
from mutagen.flac import FLAC
`˚˚
def get_lrclyrics (flactags):
   duration = f"{int(flactags.info.length // 60):d}{int(flactags.info.length % 60):02d}"
   url_template = "https://lrclib.net/api/get?{}"
   params = {"track_name": flactags['TITLE'][0], "artist_name": flactags['ALBUMARTIST'][0], "album_name": flactags['ORIGINAL_TITLE'][0], "duration": duration}
   url = url_template.format(urlencode(params, safe="()", quote_via=quote))
   try:
      response = requests.get(url)
      data = response.json()
      lyricsdata = (data['syncedLyrics'])
      if lyricsdata is None:
         lyricsdata = ''
   except:
      lyricsdata = ''
   return lyricsdata

def main():
   filename = "/Volumes/Frank/00NZB/complete/Billy Joel - Live at The Great American Music Hall (Live at the Great American Music Hall - 1975) (2023) [24B-44.1kHz]/14. Delta Lady (VampFragment).flac"
   tags = FLAC(filename)
   lrc = get_lrclyrics(tags)
   print(lrc)

if __name__ == "__main__":
   main()
