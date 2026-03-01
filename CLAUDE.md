# CLAUDE.md — Discogs Music Library Manager

## Project Overview

A collection of Python scripts to manage a local FLAC music library using Discogs metadata. The core philosophy: all tags are set by the user via a Discogs tagger (e.g. Yate), and no script is allowed to overwrite user-set tags arbitrarily. The Discogs Release ID anchors the metadata and ensures exact version identification.

## Project Structure

```
discogs/
├── nzbfix.py           # Pipeline orchestration (runs all steps)
├── fixtags.py          # Discogs metadata enrichment & tag normalization
├── bliss.py            # File/folder organization + MP3 sync copies
├── album_list.py       # Real-time album inventory (watchdog + CSV + chart)
├── update_lyrics.py    # Fetch & embed LRC/TXT lyrics from lrclib.net
├── calculate_dr.py     # Dynamic Range (DR) calculation per track/album
├── calculate_fp.py     # AcoustID acoustic fingerprint generation
├── 51check.py          # Detect 5.1 surround or mono versions
├── lyricscloud.py      # Experimental word cloud from lyrics
├── config.py           # API keys and directory paths (not committed)
├── config_demo.py      # Config template
├── pyproject.toml      # Project config (Ruff linter/formatter settings)
└── requirements.txt    # Python dependencies
```

## Configuration

Copy `config_demo.py` to `config.py` and fill in:
- `api_key` — Discogs API token from https://www.discogs.com/settings/developers
- `flacdir` — staging directory where newly tagged FLACs are dropped
- `flacroot` — organized library root (e.g. `/Volumes/FLAC/`)
- `mp3root` — MP3 mirror for mobile/car (e.g. `/Volumes/MP3/`)

**`config.py` must not be committed** — it contains credentials.

## Package Manager

Uses **uv** (requires Python >=3.14). Run scripts with:
```
uv run <script>.py [args]
```

Scripts declare their own dependencies via PEP 723 headers (`# /// script`), so `uv run` installs them automatically.

## Code Style (Ruff)

- Single quotes
- Tabs for indentation (tab-size = 4)
- 100 character line length
- Run formatter: `ruff format .`
- Run linter: `ruff check .`

## Script Details

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
- Watches directory for FLAC changes with watchdog (2s debounce)
- Rebuilds `albums.csv` with album metadata on each change
- Generates `albums_dr.png` DR distribution chart (matplotlib)
- Runs as a long-lived process

### `update_lyrics.py <directory>`
- Queries lrclib.net for synced (LRC) or plain (TXT) lyrics
- Writes to `LYRICS` FLAC tag
- Skips files without a Discogs tag

### `calculate_dr.py <directory>`
- Calculates DR score per track using `drmeter`
- Writes `DYNAMIC RANGE` (track) and `ALBUM DYNAMIC RANGE` (album average)

### `calculate_fp.py <directory>`
- Generates AcoustID fingerprints via `pyacoustid`
- Writes `ACOUSTID FINGERPRINT` tag

### `nzbfix.py`
- Orchestration: runs `dot_clean`, `calculate_dr.py`, `rsgain`, `calculate_fp.py`, `fixtags.py`, `update_lyrics.py` in sequence

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

These must be installed separately:
- **ffmpeg** — MP3 encoding in bliss.py
- **rsgain** — ReplayGain tag calculation (https://github.com/complexlogic/rsgain)
- **dot_clean** — Remove macOS metadata files (macOS built-in)

## Typical Workflow

1. Tag FLAC files with Discogs Release ID using Yate or similar tagger
2. Optionally add MusicBrainz ID, cover art, `SUBTITLE`, `DESCRIPTION`
3. Drop files into `flacdir` (staging)
4. Run `nzbfix.py` (or individual scripts) to enrich and organize
5. `album_list.py` monitors the library and maintains the CSV inventory

## Common Patterns in Code

- `timelog(txt1, txt2, color)` — timestamped colored log output (Rich)
- `flactag(song, tag)` — safe tag extraction with empty-string default
- `clean(text)` — filename sanitization (umlauts, special chars)
- `hasSubDirs(dir)` — checks if a directory has subdirectories
- All scripts use `alive-progress` or `tqdm` for progress display
- API calls include 1s sleep to respect rate limits
