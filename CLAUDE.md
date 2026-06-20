# CLAUDE.md — Discogs Music Library Manager

## After Every Commit

After every commit, update CLAUDE.md and README.md to reflect current project state, then commit the docs update as a separate follow-up commit. Keep both files accurate and in sync with the code.

## Project Overview

A collection of Python scripts to manage a local FLAC music library using Discogs metadata, with a FastAPI/HTMX web UI. The core philosophy: all tags are set by the user via a Discogs tagger (e.g. Yate), and no script is allowed to overwrite user-set tags arbitrarily. The Discogs Release ID anchors the metadata and ensures exact version identification.

## Project Structure

```
discogs/
├── webui.py                    # FastAPI/HTMX web interface
├── nzbfix.py                   # Pipeline orchestration (runs all steps)
├── fixtags.py                  # Discogs metadata enrichment & tag normalization
├── bliss.py                    # File/folder organization + MP3 sync copies
├── album_list.py               # Album inventory scan (CSV + DR chart)
├── update_lyrics.py            # Fetch & embed LRC/TXT lyrics from lrclib.net (parallel, 32 workers)
├── calculate_dr.py             # Dynamic Range (DR) calculation per track/album
├── calculate_fp.py             # AcoustID acoustic fingerprint generation
├── convert_opus.py             # FLAC → Opus transcoding
├── 51check.py                  # Detect 5.1 surround or mono versions
├── lyricscloud.py              # Experimental word cloud from lyrics
├── log.py                      # Shared structlog setup (imported by all scripts)
├── config_demo.py              # Config template (copy to config/config.py)
├── Dockerfile                  # Multi-stage build (TagLib 2.x + rsgain from source)
├── docker-compose-synology.yml # Synology NAS deployment
├── build_synology.sh           # Build + export Docker image for Synology
├── templates/index.html        # Jinja2 template for web UI
├── templates/albums.html       # Album table partial
├── favicon/                    # Cached favicons for toolbar link buttons
└── rsgain.ini                  # rsgain configuration
```

**Not committed (gitignored):**
- `config.py` / `config/config.py` — credentials and paths
- `docker-compose.yml` — local deployment (may contain credentials)
- `deploy-linux.sh` — deployment script with internal IPs
- `*.tar`, `*.log`, `rclone.log`, `albums.csv`

## Configuration

Copy `config_demo.py` to `config/config.py` and fill in:
- `discogs_api_key` — Discogs API token from https://www.discogs.com/settings/developers
- `flacroot` — organized library root (container path, e.g. `/flac/`)
- `mp3root` — MP3 mirror for mobile/car
- `nzbdir` — staging directory for newly tagged FLACs
- `flacroot_local` — path as seen by the browser (for tagger links)
- `flacroot_remote` — rclone destination remote (e.g. `ROCK:/mnt/flac`)
- `rclone_source` — rclone source remote (e.g. `FLAC:/flac`)
- `rclone_checkers`, `rclone_buffer_size`, `rclone_transfers` — rclone tuning
- `syslog_host`, `syslog_port` — optional Synology log server
- `log_file`, `log_rotation`, `log_retention` — logging config

**`config.py` must not be committed** — it contains credentials.

## Package Manager

Uses **uv** (requires Python >=3.14). Run scripts with:
```
uv run <script>.py [args]
```

Scripts declare their own dependencies via PEP 723 headers (`# /// script`), so `uv run` installs them automatically.

## Docker

```bash
docker compose up --build                              # local (docker-compose.yml, gitignored)
docker compose -f docker-compose-synology.yml up       # Synology
./build_synology.sh [amd64|arm64]                      # build tar for manual Synology upload
```

The Dockerfile builds TagLib 2.x and rsgain from source (Ubuntu 22.04 only ships TagLib 1.x). TagLib headers and libs are installed to `/opt/taglib`; `CPLUS_INCLUDE_PATH`, `LIBRARY_PATH`, and `LD_LIBRARY_PATH` are set so pytaglib compiles against them on first `uv run`.

## Code Style (Ruff)

- Single quotes
- Tabs for indentation (tab-size = 4)
- 100 character line length
- Run formatter: `ruff format .`
- Run linter: `ruff check .`

## Logging

All scripts import from `log.py`:

```python
from log import logger          # structlog logger
from log import logger, success # also import success() for green entries
```

- `logger.info()` / `logger.warning()` / `logger.error()` — standard levels
- `success(msg)` — logs at custom SUCCESS level (25), renders green in the web UI
- When stderr is a TTY: pretty `ConsoleRenderer` output to stderr
- When running as a subprocess (piped): JSON to stdout, captured and re-logged by webui
- File logging: JSON to `config_dir/log_file` (configured in config.py)
- Optional syslog: set `syslog_host` and `syslog_port` in config.py (e.g. Synology log server)
- Log level: set `LOG_LEVEL` env var (default: INFO)

## Script Details

### `webui.py`
- FastAPI + HTMX web interface on port 8000 (default, override with `PORT` env var)
- Album table with search, sort, DR colouring, tagger links, Discogs/MusicBrainz/CoverArtArchive icons
- Toolbar buttons: Refresh, Lyrics, Bliss, Sync (rclone), Log, Settings, + 5 configurable link buttons
- Configurable link buttons (Settings → Link button #1–5): any URL, favicon auto-cached to `config_dir/link_favicon_N.ico`
- Kill button in log modal: terminates the active subprocess
- Album table: sorted by Album Artist, then Original Date, then Release Date; row striping by global index
- DR column links to dr.loudness-war.info search; Cover Art column links to albumartexchange.com
- Settings modal: all config.py values editable in UI; save rewrites config.py in place
- After bliss run: triggers automatic album rescan
- `_current_proc` / `_set_proc()` / `_clear_proc()` globals manage killable subprocesses

### `fixtags.py <directory>`
- Finds all FLACs with a `DISCOGS_RELEASE_ID` tag
- Queries Discogs API for release + master release metadata
- Rewrites `ALBUM` tag to: `Title [YEAR FORMAT BITRATE]`
- Sets: `DATE`, `ORIGINALRELEASEDATE`, `ORIGINAL_TITLE`
- Calculates and writes `ALBUM DYNAMIC RANGE` (average DR)
- Respects 1s delay between API calls

### `bliss.py [--mp3] [--full] [--ingest DIR]`
- Moves FLACs into `<flacroot>/<AlbumArtist>/<Album>/<disc>_<track>_<title>.flac`
- Creates synchronized MP3 copies via ffmpeg (VBR quality 2)
- Sanitizes filenames (umlauts converted, special chars removed)
- Skips files that already have current MP3 copies

### `album_list.py [directory]`
- Scans directory for FLAC files and writes `albums.csv`
- Generates `albums_dr.png` DR distribution chart (matplotlib)
- Called by webui on demand; not a long-lived process

### `update_lyrics.py <directory>`
- Queries lrclib.net for synced (LRC) or plain (TXT) lyrics using 32 parallel workers
- Detects and clears malformed LRC (3-part timestamps like `[100:40:39.00]`)
- Upgrades existing LRC to version with metadata headers if lrclib provides them
- Writes to `LYRICS` FLAC tag; newly found/upgraded lyrics logged at SUCCESS (green)
- Skips files without a Discogs tag

### `calculate_dr.py <directory>`
- Calculates DR score per track using `drmeter`
- Writes `DYNAMIC RANGE` (track) and `ALBUM DYNAMIC RANGE` (album average)

### `calculate_fp.py <directory>`
- Generates AcoustID fingerprints via `pyacoustid`
- Writes `ACOUSTID FINGERPRINT` tag

### `nzbfix.py`
- Orchestration: runs `dot_clean`, `calculate_dr.py`, `rsgain`, `calculate_fp.py`, `fixtags.py`, `update_lyrics.py` in sequence

### `convert_opus.py <directory>`
- Transcodes FLAC files to Opus format via ffmpeg

## Key FLAC Tags

| Tag | Source | Purpose |
|-----|--------|---------|
| `DISCOGS_RELEASE_ID` | User (tagger) | Required by most scripts |
| `ALBUMARTIST`, `ALBUM`, `TITLE` | User / fixtags.py | Core metadata |
| `DATE` | fixtags.py | Year of this specific release |
| `ORIGINALRELEASEDATE` | fixtags.py (master) | First ever release date |
| `ORIGINAL_TITLE` | fixtags.py | Discogs title before enrichment |
| `DYNAMIC RANGE` | calculate_dr.py | Per-track DR score |
| `ALBUM DYNAMIC RANGE` | fixtags.py | Album-average DR score |
| `ACOUSTID FINGERPRINT` | calculate_fp.py | Acoustic fingerprint |
| `LYRICS` | update_lyrics.py | LRC or TXT lyrics |
| `SUBTITLE` | User | Format variant (e.g. "SACD", "5.1") |
| `ORIGINAL_FILENAME` | User | Override filename if title is ambiguous |
| `DESCRIPTION` | User | Source/vendor info (e.g. "Qobuz 24/96") |

## External Tool Dependencies

These must be installed separately (included in Docker image):
- **ffmpeg** — MP3/Opus encoding
- **rsgain** — ReplayGain tag calculation (built from source in Docker)
- **rclone** — Remote sync (FLAC library backup); config at `$RCLONE_CONFIG` or `config_dir/rclone.conf`
- **dot_clean** — Remove macOS metadata files (macOS built-in, not in Docker)

## Common Patterns in Code

- `from log import logger, success` — shared structlog setup
- `flactag(song, tag)` — safe tag extraction with empty-string default
- `clean(text)` — filename sanitization (umlauts, special chars)
- `hasSubDirs(dir)` — checks if a directory has subdirectories
- API calls include 1s sleep to respect rate limits
- `config_read` / `config_write` in webui.py use regex `r'^(\w+)\s*=\s*(\S*)'` (note `\S*` not `\S+`) to match empty values
