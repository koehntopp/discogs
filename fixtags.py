# import system libraries
import time
import sys
import os
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
from tqdm import tqdm
from dataclasses import dataclass
from typing import Optional
import argparse

# import music libraries
# https://github.com/joalla/discogs_client
import discogs_client

# https://github.com/supermihi/pytaglib
import taglib

# import config file containing Discogs api_key (String with API token from https://www.discogs.com/en/settings/developers?lang_alt=en )
from config import api_key

# logging function
def timelog(txt1, txt2, colour: str = 'white'):
   log_msg = f'[{colour}]' + txt1 + f'[/{colour}]'
   log_msg = log_msg + ' ' * (40 - len(txt1))
   rprint(f'[white]{datetime.now().strftime("%H:%M:%S")}[/white] ' + log_msg + txt2)

# extract a single FLAC tag
def flactag(song, tag):
   try:
      return(song.tags[tag][0])
   except: 
      timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0], colour='red')
      return("")

@dataclass
class AlbumMetadata:
    title: str
    artist: str
    year_release: int
    year_master: int
    description: str = 'CD'
    dr_rating: str = ''
    sample_rate: int = 0
    discogs_title: str = ''
    
    @property
    def formatted_year(self) -> str:
        return str(self.year_release) + ' ' if self.year_release != 0 else ''
    
    @property
    def formatted_dr(self) -> str:
        return f" DR{self.dr_rating}" if self.dr_rating else ""
    
    def get_formatted_title(self) -> str:
        return f"{self.title} [{self.formatted_year}{self.description} {self.sample_rate}kHz{self.formatted_dr}]"

def extract_metadata(tags: taglib.File, drelease: discogs_client.models.Release) -> AlbumMetadata:
    samplerate = int(tags.sampleRate / 1000)
    discogs_name = drelease.master.title.strip()
    album_name = flactag(tags, 'ORIGINAL FILENAME').strip() or discogs_name
    album_artist = flactag(tags, 'ALBUMARTIST')
    
    album_year_release = drelease.year
    album_year_master = drelease.master.main_release.year if drelease.master else album_year_release
    
    if album_year_release == 0 and album_year_master != 0:
        album_year_release = album_year_master
    if album_year_release != 0 and album_year_master == 0:
        album_year_master = album_year_release
        
    description = flactag(tags, 'SUBTITLE').strip() or 'CD'
    dr_rating = flactag(tags, "ALBUM DYNAMIC RANGE").strip()
    
    return AlbumMetadata(
        title=album_name,
        artist=album_artist,
        year_release=album_year_release,
        year_master=album_year_master,
        description=description,
        dr_rating=dr_rating,
        sample_rate=samplerate,
        discogs_title=discogs_name
    )

# fix tags for a single album (in a single directory)
def fixdir(fixdir):
   flac_files = 0
   # initialize Discogs API
   dclient = discogs_client.Client('PyDiscogsTagger/0.1', user_token=api_key)
   first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
   if first_flac != None:
      first_flac_path = os.path.join(fixdir, first_flac)
   else:
      return
   tags = taglib.File(first_flac_path)
   discogs = True
   try:
      discogs_id = int(flactag(tags, 'DISCOGS_RELEASE_ID'))
   except:
      discogs = False
      return
   # if we found discogs tags to work with go ahead
   if discogs:
      metadata = extract_metadata(tags, dclient.release(discogs_id))
      album_newtitle = metadata.get_formatted_title()
      
      for p in Path(fixdir).rglob('*.flac'):
         fullfilename = str(PurePosixPath(p))
         tags = taglib.File(fullfilename)
         
         # Create new tags dictionary
         new_tags = {
            'RELEASEDATE': [str(metadata.year_release)],
            'DATE': [str(metadata.year_release)],
            'ORIGINALDATE': [str(metadata.year_master)],
            'ORIGINALRELEASEDATE': [str(metadata.year_master)],
            'ALBUM': [album_newtitle],
            'ORIGINAL_TITLE': [metadata.discogs_title]
         }
         
         # Check if any tags need updating
         needs_update = False
         for tag in ["YEAR", "DATE"]:
            if tag in tags.tags:
               needs_update = True
               break
                    
         for tag, value in new_tags.items():
            if tag not in tags.tags or tags.tags[tag] != value:
               needs_update = True
               break
            
         if needs_update:
            # Remove old tags
            for tag in ["YEAR", "DATE"]:
               tags.tags.pop(tag, None)
            
            # Update with new tags
            tags.tags.update(new_tags)
            tags.save()
            flac_files += 1
      
      if flac_files > 0:
         timelog(f"Updated {flac_files} files with new title: ", album_newtitle, colour='green')
      else:
         timelog("No changes needed for ", album_newtitle, colour='green')
   else:
      timelog('No Discogs tags found in ', shortpath, colour='red')

def main():
    parser = argparse.ArgumentParser(description='Fix FLAC file tags using Discogs metadata')
    parser.add_argument('--configfile', action='store_true', 
                       help='use flacdir from config.py instead of command line')
    parser.add_argument('directory', nargs='?', 
                       help='directory containing FLAC files to process')
    args = parser.parse_args()

    # If no arguments provided, show help
    if not any(vars(args).values()):
        parser.print_help()
        return

    if args.configfile or not args.directory:
        from config import flacdir
    else:
        flacdir = args.directory

    flac_directories = []
    for root, dirs, files in os.walk(flacdir):
        for file in files:
            if file.endswith(".flac"):
                flac_directories.append(root)
                break
    
    for directory in flac_directories:
        timelog('Starting to fix tags in ', directory)
        fixdir(directory)
    print("")

if __name__ == '__main__':
   main()
