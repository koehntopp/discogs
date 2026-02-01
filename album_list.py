# /// script
# dependencies = [
#   "rich",
#   "pytaglib",
#   "alive-progress",
#   "pandas",
#   "watchdog"
# ]
# ///

# import system libraries
import sys
import os
import re
from rich import print as rprint
from datetime import datetime
from pathlib import Path, PurePosixPath, PurePath
import time
from threading import Lock

from alive_progress import alive_bar

# import file monitoring
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# import music libraries

# https://github.com/supermihi/pytaglib
import taglib
import pandas as pd

# Define album-related tags to extract
ALBUM_TAGS = ['ALBUMARTIST', 'ALBUM', 'ALBUM DYNAMIC RANGE', 'ORIGINAL_TITLE', 
                'ORIGINALDATE', 'RELEASEDATE', 'CATALOGNUMBER',
                'DISCOGS_RELEASE_ID', 'MUSICBRAINZ_ALBUMID', 'SUBTITLE']

# Display names for CSV headers (user-friendly)
DISPLAY_NAMES = {
    'ALBUMARTIST': 'Album Artist',
    'ALBUM': 'Album',
    'ALBUM DYNAMIC RANGE': 'DR',
    'ORIGINAL_TITLE': 'Original Title',
    'ORIGINALDATE': 'Original Date',
    'RELEASEDATE': 'Release Date',
    'CATALOGNUMBER': 'Catalog',
    'DISCOGS_RELEASE_ID': 'Discogs',
    'MUSICBRAINZ_ALBUMID': 'MusicBrainz',
    'SUBTITLE': 'Version'
}

# Track directory path for each album (internal only, not in CSV)
ALBUM_TAGS_WITH_PATH = ALBUM_TAGS + ['_DIRECTORY_PATH']

# extract a single FLAC tag
def flactag(song, tag):
    try:
        return song.tags.get(tag, [""])[0]
    except (KeyError, IndexError):
        # timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
        return ""

# logging function
def timelog(txt1, txt2, color: str = 'white'):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint(f'[{color}]{datetime.now().strftime("%H:%M:%S")}[/{color}] ' + log_msg + txt2)

# Save dataframe with consistent column order and display names
def save_csv(df):
    # Only select columns that exist in the dataframe
    existing_tags = [tag for tag in ALBUM_TAGS if tag in df.columns]
    df_ordered = df[existing_tags].copy()
    # Rename columns to display names
    df_ordered.columns = [DISPLAY_NAMES.get(col, col) for col in df_ordered.columns]
    # Save with explicit flush and sync
    df_ordered.to_csv('albums.csv', index=False)
    # Force flush to disk
    import sys
    sys.stdout.flush()

def walkdirs(fixdir, bar):
       
   # Get first FLAC file
   first_flac = next((filename for filename in os.listdir(fixdir) if filename.endswith(".flac")), None)
   if not first_flac:
      return None
   
   tags = taglib.File(fixdir + "/" + str(PurePosixPath(first_flac)))
    
   # Extract all album-related tags into a dictionary
   album_data = {}
   for tag in ALBUM_TAGS:
        album_data[tag] = flactag(tags, tag)
   
   # Add directory path for tracking
   album_data['_DIRECTORY_PATH'] = fixdir
    
   # Update progress bar
   bar.title(f"{album_data['ALBUMARTIST']} - {album_data['ALBUM']} : ")
   bar()
    
   return album_data


def main():
    if len(sys.argv) != 2:
        from config import flacdir
    else:
        flacdir = sys.argv[1]

    flac_directories = []
    albums = []
    df = pd.DataFrame()
    data_lock = Lock()
    
    # Track recently updated albums to prevent duplicate handling
    recently_updated = {}
    UPDATE_DEBOUNCE_TIME = 2  # seconds

    # Find all directories containing FLAC files
    print("")
    timelog('Scanning directories in ', str(flacdir))
    print("")
    
    for root, dirs, files in os.walk(flacdir):
        for file in files:
            if file.endswith(".flac"):
                flac_directories.append(root)
                break

    # Initial scan and populate DataFrame
    with alive_bar(len(flac_directories), enrich_print=False, length=20) as bar:
        for directory in flac_directories:
            album_data = walkdirs(directory, bar)
            if album_data:
                albums.append(album_data)
            bar()

    with data_lock:
        df = pd.DataFrame(albums)
        save_csv(df)
    
    print("")
    timelog(f'Loaded {len(albums)} albums', 'Starting file monitoring...')
    print("")

    # Create file system event handler
    class AlbumChangeHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            if event.src_path.endswith('.flac'):
                self._handle_flac_change(event.src_path)

        def on_created(self, event):
            if event.is_directory:
                return
            if event.src_path.endswith('.flac'):
                self._handle_flac_change(event.src_path)

        def on_deleted(self, event):
            if event.is_directory:
                # Remove albums from deleted directory
                self._handle_directory_delete(event.src_path)
            elif event.src_path.endswith('.flac'):
                self._handle_flac_delete(event.src_path)

        def _handle_flac_change(self, filepath):
            # Find the directory containing the FLAC file
            directory = os.path.dirname(filepath)
            
            # Debounce: skip if we've updated this album recently
            current_time = time.time()
            album_key = directory  # Use directory as unique key
            if album_key in recently_updated:
                last_update = recently_updated[album_key]
                if current_time - last_update < UPDATE_DEBOUNCE_TIME:
                    return  # Skip this update, too soon
            
            # Create a dummy progress bar for the function
            class DummyBar:
                def title(self, msg):
                    pass
                def __call__(self):
                    pass
            
            album_data = walkdirs(directory, DummyBar())
            
            if album_data:
                with data_lock:
                    artist = album_data['ALBUMARTIST']
                    album = album_data['ALBUM']
                    new_path = album_data['_DIRECTORY_PATH']
                    
                    # Check if this album already exists (by artist + album + path)
                    mask = (df['ALBUMARTIST'] == artist) & (df['ALBUM'] == album) & (df['_DIRECTORY_PATH'] == new_path)
                    
                    if mask.any():
                        # Update existing entry - only update the first match to avoid duplicates
                        idx = df[mask].index[0]
                        for key, value in album_data.items():
                            df.at[idx, key] = value
                        timelog('[yellow]Updated[/yellow]', f"{artist} - {album}")
                    else:
                        # Check if album exists with a different path (moved album)
                        old_mask = (df['ALBUMARTIST'] == artist) & (df['ALBUM'] == album)
                        if old_mask.any():
                            # Remove old entries from different directories
                            df.drop(df[old_mask].index, inplace=True)
                            timelog('[red]Removed old[/red]', f"{artist} - {album}")
                        
                        # Add new entry
                        df.loc[len(df)] = album_data
                        timelog('[green]Added[/green]', f"{artist} - {album}")
                    
                    # Save to CSV
                    save_csv(df)
                    
                    # Update timestamp for this album
                    recently_updated[album_key] = current_time

        def _handle_directory_delete(self, directory):
            with data_lock:
                # Remove all albums from the deleted directory
                if '_DIRECTORY_PATH' in df.columns:
                    mask = df['_DIRECTORY_PATH'] == directory
                    if mask.any():
                        removed_count = mask.sum()
                        removed_albums = df.loc[mask, ['ALBUMARTIST', 'ALBUM']].values.tolist()
                        df.drop(df[mask].index, inplace=True)
                        timelog('[red]Removed[/red]', f"{removed_count} album(s) from deleted directory")
                        for artist, album in removed_albums:
                            rprint(f"  [red]✗[/red] {artist} - {album}")
                        save_csv(df)

        def _handle_flac_delete(self, filepath):
            # Check if all FLAC files are gone from this directory
            directory = os.path.dirname(filepath)
            flac_files = [f for f in os.listdir(directory) if f.endswith('.flac')] if os.path.exists(directory) else []
            
            if not flac_files:
                # Directory is now empty of FLAC files, remove albums from it
                with data_lock:
                    if '_DIRECTORY_PATH' in df.columns:
                        mask = df['_DIRECTORY_PATH'] == directory
                        if mask.any():
                            removed = df.loc[mask, ['ALBUMARTIST', 'ALBUM']].values.tolist()
                            df.drop(df[mask].index, inplace=True)
                            for artist, album in removed:
                                timelog('[red]Removed[/red]', f"{artist} - {album}")
                            save_csv(df)

    # Set up file system observer
    handler = AlbumChangeHandler()
    observer = Observer()
    observer.schedule(handler, path=flacdir, recursive=True)
    observer.start()

    try:
        timelog('Monitoring active', f'Press Ctrl+C to stop')
        print("")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n")
        timelog('Monitoring stopped', f'Final count: {len(df)} albums')
        observer.join()

if __name__ == '__main__':
    main()
