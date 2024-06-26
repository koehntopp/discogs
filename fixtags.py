# import system libraries
import json
import time
import sys
import os
import re
import glob
import traceback
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
import requests
from urllib.parse import quote, urlencode

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

from mutagen.flac import FLAC

# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
# https://github.com/KristoforMaynard/music-tag
import music_tag

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# import DRMETER https://github.com/janw/drmeter/
from drmeter.algorithm import dynamic_range
from drmeter.models import AudioData
import soundfile as sf


# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (45 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)


# calculate song and album dynamic range and write tags to files
def calculate_dr(albumpath):
   # assumption: folder only contains a single album
   dr_sum = 0
   dr_tracks = 0
   dr_dirty = False
   # calculate title DR (if possible)
   for p in Path(albumpath).rglob('*.flac'):
      fullfilename = str(PurePosixPath(p))
      dr_tags = FLAC(fullfilename)
      try:
         drsong = int(dr_tags['DYNAMIC RANGE'][0])
      except (TypeError, KeyError):
         drsong = 0
      try:
         with sf.SoundFile(fullfilename) as data:
            result = dynamic_range(AudioData.from_soundfile(data))
            DR = round(result.overall_dr_score)
      except:
         traceback.print_exc()
         print(fullfilename)
         dr_dirty = True
         DR = 0
      if int(DR) != drsong and DR != 0:
         timelog(
            'DR old ' + str(drsong).zfill(2) + ' --> new ' + str(DR).zfill(2), str(dr_tags['TITLE'])
         )
         dr_tags['DYNAMIC RANGE'] = str(DR).zfill(2)
         dr_tags.save()
      if DR > 0:
         dr_tracks += 1
         dr_sum += DR
   if dr_tracks > 0:
      dr_album = round(dr_sum / dr_tracks)
   else:
      dr_album = 0
   return dr_album


def get_lrclyrics(flactags):
   # try to find better lyrics data for one song
   duration = str(round(flactags.info.length))
   try:
      albumtitle = flactags['ORIGINAL_TITLE'][0]
   except KeyError:
      albumtitle = flactags['ALBUM'][0]
   # query lrclib.net https://github.com/tranxuanthang/lrcget
   url_template = 'https://lrclib.net/api/get?{}'
   params = {
      'artist_name': flactags['ALBUMARTIST'][0],
      'track_name': flactags['TITLE'][0],
      'album_name': albumtitle,
      'duration': duration,
   }
   url = url_template.format(urlencode(params, safe='()', quote_via=quote))
   lyricsdata = ''
   lyricstype = 'none'
   try:
      response = requests.get(url)
      data = response.json()
      if data['syncedLyrics']:
         lyricsdata = data['syncedLyrics']
         lyricstype = 'lrc'
      elif data['plainLyrics']:
         lyricsdata = data['plainLyrics']
         lyricstype = 'plain'
   except:
      lyricsdata = ''
   return lyricsdata, lyricstype


# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir):
   global lrc_total
   flac_files = 0
   lrctotal = 0
   nototal = 0
   lrcnew = 0
   txttotal = 0
   txtnew = 0
   current_album = ''
   current_artist = ''
   current_discogs_id = 12345
   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)

   # find all directories containing flac files below fixdir
   files = glob.glob(os.path.join(fixdir, '**', '*.flac'), recursive=True)
   paths = list(set(map(os.path.dirname, files)))
   pathbar = tqdm(range(len(paths)))
   for i in pathbar:
      shortpath = (
         (PurePath(paths[i]).name[:40] + '..')
         if len(PurePath(paths[i]).name) > 40
         else PurePath(paths[i]).name
      )
      # timelog('Analyzing ', shortpath)
      firstflac = next(Path(paths[i]).rglob('*.flac'), None)
      dynamicrange = calculate_dr(paths[i])
      tags = FLAC(firstflac)
      discogs = True
      try:
         discogs_idstring = tags['DISCOGS_RELEASE_ID']
         discogs_id = int(discogs_idstring[0])
      except:
         discogs = False
      # if we found discogs tags to work with go ahead
      if discogs:
         tag_album = str(tags['album'])
         tag_artist = str(tags['albumartist'])
         bitrate = int(tags.info.sample_rate / 1000)
         drelease = dclient.release(discogs_id)
         # make Discogs API rate limit happy
         time.sleep(3)
         album_catno = ''
         album_label = ''
         try:
            labels_json = json.dumps(drelease.labels[0].data)
            labels = json.loads(labels_json)
            album_label = labels['name']
            album_catno = ' ' + (labels['catno'])
         except:
            print(tag_album)
            print(labels_json)
         try:
            album_name = tags['ORIGINAL FILENAME'][0].strip()
         except:
            album_name = drelease.title.strip()
         album_artist = tags['ALBUMARTIST'][0]
         # get the release date from the master release which will be used for all files
         # release date goes into the album name instead
         album_year_release = drelease.year
         mrelease = drelease.master
         if drelease.master:
            album_year_master = mrelease.main_release.year
         else:
            album_year_master = album_year_release
         if album_year_release == 0 and album_year_master != 0:
            album_year_release = album_year_master
         if album_year_release == 0:
            album_year_release_str = ''
         else:
            album_year_release_str = str(album_year_release)
         if album_year_release != 0 and album_year_master == 0:
            album_year_master = album_year_release
         try:
            album_description = tags['SUBTITLE'][0].strip() + ' '
         except KeyError:
            album_description = ''
         album_newtitle = (
            album_name
            + ' ('
            + album_year_release_str
            + ' '
            + album_description
            + str(bitrate)
            + 'kHz'
            + ')'
         )
         songs = 0
         # write new tags to files
         for subdir, dirs, files in os.walk(paths[i]):
            for filename in files:
               filepath = paths[i] + os.sep + filename
               if filepath.endswith('.flac'):
                  mtags = music_tag.load_file(filepath)
                  mtags.remove_tag('YEAR')
                  mtags.save()
                  tags = FLAC(filepath)
                  try:
                     lyrics = tags['LYRICS'][0].strip()
                  except KeyError:
                     lyrics = ''
                  if lyrics == '' or not re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
                     lrc, lrctype = get_lrclyrics(tags)
                     if lrctype == 'lrc':
                        tags['LYRICS'] = lrc
                        lrcnew += 1
                        lrctotal += 1
                        tqdm.write(
                           '           LRC lyrics added for '
                           + tags['TITLE'][0]
                           + ' ('
                           + album_artist
                           + ')'
                        )
                     elif lrctype == 'plain' and lyrics == '':
                        tags['LYRICS'] = lrc
                        txtnew += 1
                        txttotal += 1
                        tqdm.write(
                           '           TXT lyrics added for '
                           + tags['TITLE'][0]
                           + ' ('
                           + album_artist
                           + ')'
                        )
                     else:
                        if lyrics != '':
                           txttotal += 1
                        else:
                           nototal += 1
                  else:
                     if re.match(r'\[\d\d\D\d\d\D\d\d\]', lyrics):
                        lrctotal += 1
                  try:
                     subtitle = tags['SET SUBTITLE'][0].strip()
                  except KeyError:
                     subtitle = ''
                  tags['DISCSUBTITLE'] = subtitle
                  tags['YEAR'] = str(album_year_release)
                  tags['RELEASEDATE'] = str(album_year_release)
                  tags['DATE'] = str(album_year_master)
                  tags['ORIGINALDATE'] = str(album_year_master)
                  tags['VERSION'] = album_description.strip()
                  tags['ALBUM'] = album_newtitle
                  tags['ORIGINAL_TITLE'] = album_name
                  tags['ALBUM DYNAMIC RANGE'] = str(dynamicrange).zfill(2)
                  tags.save()
                  flac_files += 1
      else:
         timelog('No Discogs tags found in ', shortpath)
   timelog('Finished analysis', fixdir)
   tqdm.write(
      '         '
      + str(flac_files)
      + ' FLAC files processed, '
      + str(lrcnew)
      + ' LRC lyrics and '
      + str(txtnew)
      + ' TXT lyrics added'
   )
   tqdm.write(
      '         '
      + str(flac_files)
      + ' FLAC files processed, '
      + str(lrctotal)
      + ' LRC lyrics and '
      + str(txttotal)
      + ' TXT lyrics present, '
      + str(nototal)
      + ' files without lyrics'
   )


def main():
   if len(sys.argv) != 2:
      from config import flacdir
   else:
      flacdir = sys.argv[1]

   timelog('Starting analysis', flacdir)

   walkdirs(flacdir)


if __name__ == '__main__':
   main()
