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

## Tagging Suggestions

- Assign a Discogs release ID and a MusicBrainz ID for every album
- Add decent cover art
- Put source info (vendor, medium) in `DESCRIPTION` (e.g. `"Qobuz 24/96"`)
- For ambiguous titles or deluxe editions, put the disambiguation in `ORIGINAL_FILENAME`
- Use `SUBTITLE` for format variants (e.g. `"SACD"`, `"5.1"`)

## Typical Workflow

1. Tag FLAC files with a Discogs Release ID using Yate or similar
2. Drop files into `nzbdir` (staging)
3. Run `nzbfix.py` (or click Refresh in the web UI) to enrich tags, calculate DR, generate fingerprints, fetch lyrics, and organise files into the library
4. Use the web UI to browse, search, and manage the library

## Scripts

| Script | Purpose |
|--------|---------|
| `webui.py` | Web interface (FastAPI + HTMX) |
| `nzbfix.py` | Pipeline orchestrator |
| `fixtags.py` | Discogs API tag enrichment |
| `bliss.py` | File organisation + MP3 sync |
| `album_list.py` | Album inventory scan → CSV + DR chart |
| `update_lyrics.py` | Parallel lyrics fetch from lrclib.net (32 workers) |
| `calculate_dr.py` | Dynamic Range calculation |
| `calculate_fp.py` | AcoustID fingerprint generation |
| `convert_opus.py` | FLAC → Opus transcoding |
| `build_synology.sh` | Build Docker image tar for Synology upload |

All scripts use [uv](https://github.com/astral-sh/uv) and declare their own dependencies via PEP 723 headers — no manual `pip install` needed:

```bash
uv run fixtags.py /path/to/album
```

## Requirements

- Python ≥ 3.14 (managed automatically by uv)
- [TagLib 2.x](https://taglib.org/) — built from source in Docker; `brew install taglib --HEAD` on macOS
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
- [pytaglib](https://github.com/supermihi/pytaglib) — FLAC tag read/write via TagLib
- [drmeter](https://codeberg.org/janw/drmeter) — Dynamic Range calculation
- [pyacoustid](https://github.com/beetbox/pyacoustid) — AcoustID fingerprinting
- [lrclib.net](https://lrclib.net) — synced lyrics API
- [rsgain](https://github.com/complexlogic/rsgain) — ReplayGain tag calculation
- [FastAPI](https://github.com/fastapi/fastapi) + [HTMX](https://htmx.org) — web UI
- [structlog](https://github.com/hynek/structlog) — structured logging
