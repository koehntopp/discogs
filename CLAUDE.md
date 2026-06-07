# CLAUDE.md — Discogs Music Library Manager

## Project Overview

A collection of Python scripts to manage a local FLAC music library using Discogs metadata, with a FastAPI/HTMX web UI. The core philosophy: all tags are set by the user via a Discogs tagger (e.g. Yate), and no script is allowed to overwrite user-set tags arbitrarily. The Discogs Release ID anchors the metadata and ensures exact version identification.

## Project Structure

```
discogs/
├── webui.py            # FastAPI/HTMX web interface
├── nzbfix.py           # Pipeline orchestration (runs all steps)
├── fixtags.py          # Discogs metadata enrichment & tag normalization
├── bliss.py            # File/folder organization + MP3 sync copies
├── album_list.py       # Album inventory scan (CSV + DR chart)
├── update_lyrics.py    # Fetch & embed LRC/TXT lyrics from lrclib.net
├── calculate_dr.py     # Dynamic Range (DR) calculation per track/album
├── calculate_fp.py     # AcoustID acoustic fingerprint generation
├── convert_opus.py     # FLAC → Opus transcoding
├── 51check.py          # Detect 5.1 surround or mono versions
├── lyricscloud.py      # Experimental word cloud from lyrics
├── log.py              # Shared structlog setup (imported by all scripts)
├── config.py           # API keys and directory paths (not committed)
├── config_demo.py      # Config template
├── Dockerfile          # Multi-stage build (TagLib 2.x + rsgain from source)
├── docker-compose.yml          # Local / Docker Desktop deployment
├── docker-compose-synology.yml # Synology NAS deployment
└── pyproject.toml      # Project config (Ruff linter/formatter settings)
```

## Configuration

Copy `config_demo.py` to `config/config.py` and fill in:
- `discogs_api_key` — Discogs API token from https://www.discogs.com/settings/developers
- `flacroot` — organized library root (container path, e.g. `/flac/`)
- `mp3root` — MP3 mirror for mobile/car
- `nzbdir` — staging directory for newly tagged FLACs
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
docker compose up --build        # local
docker compose -f docker-compose-synology.yml up   # Synology
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
- Log level: set `LOG_LEVEL` env var (default: INFO)

## Script Details

### `webui.py`
- FastAPI + HTMX web interface on port 8000 (default)
- Album table with search, sort, DR colouring, tagger links, Discogs/MusicBrainz icons
- Buttons: Refresh (album scan), Lyrics, Bliss (organise), Sync (rclone), Log, Settings
- Album list reloads automatically after a successful refresh
- Live log modal with auto-scroll; log text is selectable

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
- Queries lrclib.net for synced (LRC) or plain (TXT) lyrics
- Writes to `LYRICS` FLAC tag
- Newly found lyrics logged at SUCCESS level (green)
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
- **rclone** — Remote sync (FLAC library backup)
- **dot_clean** — Remove macOS metadata files (macOS built-in, not in Docker)

## Common Patterns in Code

- `from log import logger, success` — shared structlog setup
- `flactag(song, tag)` — safe tag extraction with empty-string default
- `clean(text)` — filename sanitization (umlauts, special chars)
- `hasSubDirs(dir)` — checks if a directory has subdirectories
- API calls include 1s sleep to respect rate limits
