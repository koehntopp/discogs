# Discogs Music Library Manager

A collection of Python scripts and a web UI for managing a local FLAC music library using [Discogs](https://www.discogs.com) metadata.

**Core philosophy:** tags are set by the user via a dedicated tagger (e.g. [Yate](https://2manyrobots.com/yate/) on macOS). Scripts enrich and organise — they never overwrite user-set tags arbitrarily. The `DISCOGS_RELEASE_ID` tag anchors every album to an exact Discogs release, eliminating the ambiguity that automated taggers introduce.

## Why?

If you have multiple versions of the same album (original, remaster, SACD, Qobuz 24/96), automated music tools will happily collapse them into one. I've tried many; they've all mangled my collection at some point. Assigning a Discogs release ID to every album means I always know exactly which version I'm listening to, and can recover from any accidental tag overwrite as long as the release ID survives.

## Features

- **Web UI** — FastAPI + HTMX interface: browse your library, trigger scans, fetch lyrics, organise files, sync to remote
- **Configurable link buttons** — up to 5 toolbar buttons linking to any URL (favicons auto-cached)
- **Tag enrichment** — pulls release date, original release date, and format info from the Discogs API
- **File organisation** — moves FLACs into `Artist/Album/track_title.flac`, creates MP3 mirrors via ffmpeg
- **Dynamic Range scoring** — per-track and per-album DR values written as FLAC tags; DR column links to loudness-war.info
- **Lyrics** — parallel fetching (32 workers) from lrclib.net; LRC upgrade and invalid-LRC detection
- **AcoustID fingerprinting** — generates and stores acoustic fingerprints
- **rclone sync** — mirrors the FLAC library to a remote destination
- **Syslog forwarding** — optional structured log forwarding to a Synology log server
- **Docker support** — runs on Docker Desktop (Mac) or Synology NAS

## Quick Start

### Local (macOS)

```bash
brew install taglib --HEAD ffmpeg rsgain rclone
cp config_demo.py config/config.py   # fill in your paths and API key
uv run webui.py
```

Open http://localhost:8000

### Docker (local)

Create `docker-compose.yml` (gitignored — may contain credentials):

```yaml
services:
  discogs:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config:/config
      - /path/to/flac:/flac
    environment:
      - CONFIG_DIR=/config
      - PORT=8000
      - RCLONE_CONFIG=/config/rclone.conf
```

```bash
docker compose up --build
```

### Synology NAS

```bash
./build_synology.sh          # builds discogs-synology-amd64.tar
# Upload via Container Manager → Image → Add → Import from file
```

Then use `docker-compose-synology.yml` as a reference for container settings.

## Configuration

Copy `config_demo.py` to `config/config.py` and set:

| Key | Description |
|-----|-------------|
| `discogs_api_key` | From https://www.discogs.com/settings/developers |
| `flacroot` | Root of your organised FLAC library (container-internal path) |
| `mp3root` | MP3 mirror root |
| `nzbdir` | Staging directory for newly tagged FLACs |
| `flacroot_local` | Path as seen by the browser (for tagger deep links) |
| `flacroot_remote` | rclone destination remote (e.g. `ROCK:/mnt/flac`) |
| `rclone_source` | rclone source remote (e.g. `FLAC:/flac`) |
| `syslog_host` / `syslog_port` | Optional Synology log server |
| `log_file` | Log filename (written to `config_dir`) |

All config values are also editable via the Settings modal in the web UI.

`config.py` is gitignored — it contains credentials.

## Tagging Guidelines & Contract

- **Primary Anchor**: Assign `DISCOGS_RELEASE_ID` for every album using Yate or your preferred tagger (mandatory anchor for metadata enrichment).
- **Optional MusicBrainz Tags**: MusicBrainz IDs (`MUSICBRAINZ_ALBUMID`, `MUSICBRAINZ_ARTISTID`, `MUSICBRAINZ_TRACKID`) populated by your tagger are preserved.
- **Cover Art**: Embedded cover art is automatically resized if larger than 1500px.
- **Format Tag**: Set `ALBUM_FORMAT` for physical or digital source media (e.g. `"CD"`, `"SACD"`, `"Blu-ray"`, `"Vinyl"`). Defaults to `"CD"`.
- **Edition Tag**: Set `ALBUM_EDITION` for special pressings (e.g. `"Deluxe Edition"`, `"40th Anniversary Remaster"`).
- **User Overrides**:
  - `ALBUM_TITLE_OVERRIDE`: Custom title to override the Discogs master album title.
  - `ALBUM_ARTIST_OVERRIDE`: Custom artist name to override Discogs artist in player displays, bliss paths, and album lists.

## Typical Workflow

1. **Tag FLAC Files**: Assign `DISCOGS_RELEASE_ID` tag in Yate or your tagger (along with optional MusicBrainz tags and cover art).
2. **Stage Files**: Drop new album folders into `nzbdir` (staging directory).
3. **Run Pipeline (`nzbfix.py`)**: Run `./nzbfix.py` (or click Refresh in the web UI) to execute post-processing:
   - `dot_clean`: Strips macOS `.DS_Store` / `._*` AppleDouble junk.
   - Parallel tasks: `calculate_dr` (DR scores), `rsgain` (ReplayGain tags), `calculate_fp` (AcoustID fingerprints).
   - Sequential tasks: `fixtags` (Discogs metadata enrichment & player date tags), `update_lyrics` (LrcLib.net lyrics download).
4. **Organise & Mirror (`bliss.py`)**: Run `./bliss.py` to move FLACs into `Artist/Album/track.flac` structure in `flacroot` (with non-destructive overwrite protection) and generate optional MP3 mirrors.
5. **Browse & Manage (`webui.py`)**: Use the FastAPI/HTMX web UI to browse, search, and manage the library.

## Scripts

| Script | Purpose |
|--------|---------|
| `webui.py` | Web interface (FastAPI + HTMX) |
| `nzbfix.py` | Pipeline orchestrator (`dot_clean` → `calculate_dr` / `rsgain` / `calculate_fp` → `fixtags` → `update_lyrics`) |
| `fixtags.py` | Discogs API tag enrichment & date tag mapping |
| `bliss.py` | File organisation + MP3 sync (with overwrite protection) |
| `album_list.py` | Album inventory scan → CSV + DR chart |
| `update_lyrics.py` | Parallel lyrics fetch from lrclib.net (32 workers) |
| `calculate_dr.py` | Dynamic Range calculation |
| `calculate_fp.py` | AcoustID fingerprint generation |
| `migrate_tags.py` | Tag schema migration to discrete `ALBUM_*` tags |
| `dump_original_filenames.py` | Export albums with `ORIGINAL FILENAME` to CSV |
| `compare_libraries.py` | Compare directory trees & track counts between libraries |
| `build_synology.sh` | Build Docker image tar for Synology upload |

All Python scripts feature executable shebang lines (`#!/usr/bin/env -S uv run`) and declare dependencies via PEP 723 headers — run them directly from your shell:

```bash
./fixtags.py /path/to/album
./nzbfix.py /path/to/staging
./bliss.py
```

## Requirements

- Python ≥ 3.14 (managed automatically by uv)
- **ffmpeg**, **rsgain**, **rclone** — included in the Docker image; install separately for local use

## Logging

Structured logging via [structlog](https://github.com/hynek/structlog):
- Pretty coloured output when running in a terminal
- JSON to stdout when running as a subprocess (captured and re-logged cleanly by the web UI)
- JSON log file at `config_dir/log_file`
- Optional syslog forwarding: set `syslog_host` and `syslog_port` in config.py
- Set `LOG_LEVEL` env var to control verbosity (default: `INFO`)

## Libraries and Tools

- [discogs_client](https://github.com/joalla/discogs_client) — Discogs API
- [mutagen](https://github.com/quodlibet/mutagen) — FLAC audio tag read/write
- [drmeter](https://codeberg.org/janw/drmeter) — Dynamic Range calculation
- [pyacoustid](https://github.com/beetbox/pyacoustid) — AcoustID fingerprinting
- [lrclib.net](https://lrclib.net) — synced lyrics API
- [rsgain](https://github.com/complexlogic/rsgain) — ReplayGain tag calculation
- [FastAPI](https://github.com/fastapi/fastapi) + [HTMX](https://htmx.org) — web UI
- [structlog](https://github.com/hynek/structlog) — structured logging
