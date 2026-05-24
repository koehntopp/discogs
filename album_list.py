# /// script
# dependencies = [
#   "rich",
#   "pytaglib",
#   "alive-progress",
#   "pandas",
#   "watchdog",
#   "matplotlib"
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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# import file monitoring
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

# import music libraries

# https://github.com/supermihi/pytaglib
import taglib
import pandas as pd
from typing import Any

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
def flactag(song: taglib.File, tag: str) -> str:
    """Extract a single tag value from a FLAC file's metadata.

    Args:
        song: TagLib file object with loaded tags.
        tag: Tag key to retrieve (e.g. 'ALBUM', 'ARTIST').

    Returns:
        First value for the tag, or empty string if not found.
    """
    try:
        return song.tags.get(tag, [""])[0]
    except (KeyError, IndexError):
        # timelog("Tag Error:", tag + " -- " + song.tags["ALBUMARTIST"][0] + " - " + song.tags["ALBUM"][0])
        return ""

# logging function
def timelog(txt1: str, txt2: str, colour: str = 'white') -> None:
   """Print a timestamped log line with rich colour formatting.

   Args:
       txt1: Label text displayed in the given colour.
       txt2: Value text appended after the label.
       colour: Rich colour name applied to both the timestamp and label; defaults to 'white'.
   """
   log_msg = f'[{colour}]' + txt1 + f'[/{colour}]'
   log_msg = log_msg + ' ' * (40 - len(txt1))
   rprint(f'[white]{datetime.now().strftime("%H:%M:%S")}[/white] ' + log_msg + txt2)

# Save dataframe with consistent column order and display names
def save_csv(df: pd.DataFrame) -> None:
    """Write the album DataFrame to albums.csv and generate a DR distribution chart.

    Exports columns defined in ALBUM_TAGS using display-friendly header names from
    DISPLAY_NAMES. Also writes albums_dr.png (bar chart coloured red-to-green by DR
    value) when the 'ALBUM DYNAMIC RANGE' column is populated.

    Args:
        df: DataFrame containing album metadata with ALBUM_TAGS columns.
    """
    # Only select columns that exist in the dataframe
    existing_tags = [tag for tag in ALBUM_TAGS if tag in df.columns]
    df_ordered = df[existing_tags].copy()
    # Rename columns to display names
    df_ordered.columns = [DISPLAY_NAMES.get(col, col) for col in df_ordered.columns]
    # Save with explicit flush and sync
    df_ordered.to_csv('albums.csv', index=False)
    # Save DR distribution chart
    if 'ALBUM DYNAMIC RANGE' in df.columns:
        dr_series = df['ALBUM DYNAMIC RANGE'].fillna("").astype(str).str.strip()
        dr_series = dr_series[dr_series != ""]
        if not dr_series.empty:
            counts = dr_series.value_counts().sort_index()
            plt.figure(figsize=(10, 5))
            cmap = plt.get_cmap('RdYlGn')
            if len(counts) > 1:
                colors = [cmap(i / (len(counts) - 1)) for i in range(len(counts))]
            else:
                colors = [cmap(0.5)]
            counts.plot(kind='bar', color=colors)
            plt.title('Albums per DR value')
            plt.xlabel('Album DR')
            plt.ylabel('Number of albums')
            plt.tight_layout()
            plt.savefig('albums_dr.png', dpi=150)
            plt.close()
    save_html(df)
    # Force flush to disk
    import sys
    sys.stdout.flush()


def save_html(df: pd.DataFrame) -> None:
    import json

    album_count = len(df)

    artist_headers = ['Album Artist', 'Albums', 'Avg DR']
    artist_rows: list = []
    if 'ALBUM DYNAMIC RANGE' in df.columns and 'ALBUMARTIST' in df.columns:
        dr_numeric = pd.to_numeric(df['ALBUM DYNAMIC RANGE'], errors='coerce')
        artist_dr = (
            df.assign(_dr=dr_numeric)
            .groupby('ALBUMARTIST')['_dr']
            .agg(Albums='count', avg_dr='mean')
            .reset_index()
            .rename(columns={'ALBUMARTIST': 'Album Artist', 'avg_dr': 'Avg DR'})
            .sort_values('Album Artist')
        )
        artist_dr['Avg DR'] = artist_dr['Avg DR'].round(1)
        artist_rows = artist_dr[artist_headers].values.tolist()

    artist_count = len(artist_rows)
    artist_headers_js = json.dumps(artist_headers)
    artist_rows_js = json.dumps(artist_rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Albums</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/handsontable/styles/handsontable.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/handsontable/styles/ht-theme-classic.min.css">
  <style>
    html,body{{height:100%;margin:0}}
    .wrap{{padding:0;height:100%;box-sizing:border-box;background:#f5f5f5}}
    .toolbar{{display:flex;gap:8px;align-items:center;padding:6px 8px}}
    .tab-btn{{padding:6px 14px;border-radius:6px 6px 0 0;border:1px solid #ccc;border-bottom:none;background:#eee;cursor:pointer;font-size:13px}}
    .tab-btn.active{{background:#fff;font-weight:bold}}
    .tab-content{{display:none}}
    .tab-content.active{{display:block}}
    #hot-albums,#hot-artists{{width:100%;height:calc(100vh - 76px)}}
    button#reload{{padding:6px 12px;border-radius:6px;border:1px solid #ccc;background:#fff;cursor:pointer}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="toolbar">
      <button class="tab-btn active" data-tab="albums">Albums ({album_count})</button>
      <button class="tab-btn" data-tab="artists">Artists by DR ({artist_count})</button>
      <button id="reload">Reload CSV</button>
      <span id="status" style="color:#666;font-size:13px;margin-left:4px">Ready</span>
    </div>
    <div id="tab-albums" class="tab-content active"><div id="hot-albums"></div></div>
    <div id="tab-artists" class="tab-content"><div id="hot-artists"></div></div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/handsontable/dist/handsontable.full.min.js"></script>
  <script>
    function parseCSVRow(row) {{
      const cells = [];
      let cur = '', inQuotes = false;
      for (let i = 0; i < row.length; i++) {{
        const ch = row[i];
        if (ch === '"') {{
          if (inQuotes && row[i+1] === '"') {{ cur += '"'; i++; }}
          else inQuotes = !inQuotes;
        }} else if (ch === ',' && !inQuotes) {{ cells.push(cur); cur = ''; }}
        else cur += ch;
      }}
      cells.push(cur);
      return cells;
    }}

    async function loadCSV(url) {{
      const res = await fetch(url, {{cache: 'no-store'}});
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const txt = await res.text();
      const lines = txt.replace(/\\r/g,'').split('\\n').filter(Boolean);
      if (!lines.length) return {{headers:[], rows:[]}};
      return {{ headers: parseCSVRow(lines[0]).map(h => h.trim()), rows: lines.slice(1).map(parseCSVRow) }};
    }}

    function defaultWidth(h) {{
      const k = (h||'').toLowerCase();
      if (k.includes('artist')) return 120;
      if (k.includes('title')) return 120;
      if (k === 'dr' || k === 'avg dr') return 50;
      if (k === 'albums') return 60;
      if (k.includes('date')) return 50;
      if (k === 'discogs' || k === 'musicbrainz' || k === 'catalog' || k === 'version') return 70;
      return 120;
    }}

    let hotAlbums = null, hotArtists = null;

    async function renderAlbums() {{
      const status = document.getElementById('status');
      try {{
        status.textContent = 'Loading albums.csv...';
        const {{headers, rows}} = await loadCSV('albums.csv');
        if (hotAlbums) {{ try {{ hotAlbums.destroy(); }} catch(e) {{}} }}
        hotAlbums = new Handsontable(document.getElementById('hot-albums'), {{
          data: rows, colHeaders: headers, rowHeaders: false,
          width: '100%', height: 'calc(100vh - 76px)',
          licenseKey: 'non-commercial-and-evaluation',
          themeName: 'ht-theme-classic', readOnly: true,
          filters: true, dropdownMenu: true, columnSorting: true,
          manualColumnResize: true, colWidths: headers.map(defaultWidth), stretchH: 'all'
        }});
        status.textContent = 'Loaded ' + rows.length + ' rows';
      }} catch(e) {{ status.textContent = 'Error: ' + e.message; }}
    }}

    function renderArtists() {{
      const headers = {artist_headers_js};
      const rows = {artist_rows_js};
      if (hotArtists) {{ try {{ hotArtists.destroy(); }} catch(e) {{}} }}
      hotArtists = new Handsontable(document.getElementById('hot-artists'), {{
        data: rows, colHeaders: headers, rowHeaders: false,
        width: '100%', height: 'calc(100vh - 76px)',
        licenseKey: 'non-commercial-and-evaluation',
        themeName: 'ht-theme-classic', readOnly: true,
        filters: true, dropdownMenu: true, columnSorting: true,
        manualColumnResize: true, colWidths: headers.map(defaultWidth), stretchH: 'all'
      }});
    }}

    document.querySelectorAll('.tab-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        if (btn.dataset.tab === 'albums' && hotAlbums) hotAlbums.render();
        if (btn.dataset.tab === 'artists' && hotArtists) hotArtists.render();
      }});
    }});

    document.getElementById('reload').addEventListener('click', renderAlbums);

    renderAlbums();
    renderArtists();
  </script>
</body>
</html>"""

    with open('albums.html', 'w', encoding='utf-8') as f:
        f.write(html)

def walkdirs(fixdir: str, bar: Any) -> dict[str, str] | None:
   """Read album metadata from the first FLAC file found in a directory.

   Args:
       fixdir: Path to a directory expected to contain FLAC files.
       bar: Progress bar object supporting .title(str) and __call__().

   Returns:
       Dictionary of tag values keyed by ALBUM_TAGS names plus '_DIRECTORY_PATH',
       or None if no FLAC files are present in the directory.
   """

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


def main() -> None:
    """Scan a FLAC directory tree, write a CSV inventory, then monitor for changes.

    Reads the root directory from config.flacdir or a single positional command-line
    argument. Performs an initial full recursive scan, saves albums.csv and
    albums_dr.png, then starts a watchdog observer that updates the CSV whenever FLAC
    files are added, modified, or deleted. Runs until Ctrl-C.
    """
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
        def on_modified(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            if event.src_path.endswith('.flac'):
                self._handle_flac_change(event.src_path)

        def on_created(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            if event.src_path.endswith('.flac'):
                self._handle_flac_change(event.src_path)

        def on_deleted(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                # Remove albums from deleted directory
                self._handle_directory_delete(event.src_path)
            elif event.src_path.endswith('.flac'):
                self._handle_flac_delete(event.src_path)

        def _handle_flac_change(self, filepath: str) -> None:
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
                def title(self, msg: str) -> None:
                    pass
                def __call__(self) -> None:
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

        def _handle_directory_delete(self, directory: str) -> None:
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

        def _handle_flac_delete(self, filepath: str) -> None:
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
