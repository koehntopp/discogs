# FLAC Library Tools — CLI Specification

This document describes the command-line interface, configuration, tag contracts, and
data flows for every script in this repository.

---

## Common conventions

### Configuration (`config.py`)

All scripts that accept an optional directory argument fall back to values in `config.py`
when no argument is supplied.

| Symbol     | Type   | Description                                              |
|------------|--------|----------------------------------------------------------|
| `api_key`  | `str`  | Discogs personal access token (required by fixtags.py)   |
| `flacdir`  | `str`  | Default root of the FLAC library tree                    |
| `flacroot` | `str`  | Root of the organized FLAC library tree (used by bliss)  |

### FLAC tag names

Tags are stored uppercase in Vorbis comment fields.  The scripts use the following
tag names consistently:

| Tag                    | Set by        | Read by                          |
|------------------------|---------------|----------------------------------|
| `ALBUMARTIST`          | ripping tool  | album_list, bliss, fixtags       |
| `ALBUM`                | fixtags       | album_list, bliss, update_lyrics |
| `ORIGINAL_TITLE`       | fixtags       | update_lyrics                    |
| `DISCOGS_RELEASE_ID`   | ripping tool  | fixtags, update_lyrics           |
| `MUSICBRAINZ_ALBUMID`  | ripping tool  | album_list                       |
| `DATE`                 | fixtags       | album_list                       |
| `RELEASEDATE`          | fixtags       | album_list                       |
| `ORIGINALDATE`         | fixtags       | album_list                       |
| `ORIGINALRELEASEDATE`  | fixtags       | —                                |
| `CATALOGNUMBER`        | ripping tool  | album_list                       |
| `SUBTITLE`             | ripping tool  | fixtags (album description)      |
| `DYNAMIC RANGE`        | calculate_dr  | calculate_dr                     |
| `ALBUM DYNAMIC RANGE`  | calculate_dr  | fixtags (in ALBUM tag string)    |
| `ACOUSTID FINGERPRINT` | calculate_fp  | calculate_fp                     |
| `LYRICS`               | update_lyrics | lyricscloud                      |
| `TITLE`                | ripping tool  | bliss, update_lyrics             |
| `TRACKNUMBER`          | ripping tool  | bliss                            |
| `DISCNUMBER`           | ripping tool  | bliss                            |
| `ARTIST`               | ripping tool  | update_lyrics                    |

### External services

| Service            | Script         | Protocol | Rate limit           |
|--------------------|----------------|----------|----------------------|
| Discogs REST API   | fixtags        | HTTPS    | 1 req/s (sleep 1 s)  |
| lrclib.net REST API| update_lyrics  | HTTPS    | none enforced        |
| AcoustID / fpcalc  | calculate_fp   | local    | —                    |
| rsgain             | nzbfix         | local    | —                    |
| ffmpeg             | bliss          | local    | —                    |

## Architectural Decision Records (ADRs)

Detailed architectural standards and design contracts are maintained in `docs/adr/`:
- [ADR 0001: General Python Conventions and Architectural Rules](file:///Users/koehntopp/src/discogs/docs/adr/0001-general-python-rules.md)
- [ADR 0002: FLAC Tag Handling Contracts and Metadata Standards](file:///Users/koehntopp/src/discogs/docs/adr/0002-flac-tag-handling.md)
- [ADR 0003: Web UI Architecture, Process Lifecycle, and JSON Log Streaming](file:///Users/koehntopp/src/discogs/docs/adr/0003-webui-architecture-and-subprocess-management.md)

---

## Scripts

---

### `webui.py` — Web Dashboard & Subprocess Controller

**Purpose:** Provide a FastAPI + HTMX dashboard for library inventory browsing, tagger links, DR color indicators, live log streaming, and batch script execution.

**Usage:**

```bash
uv run webui.py
```

| Environment Var | Default | Description |
|-----------------|---------|-------------|
| `PORT`          | `8000`  | HTTP port for the FastAPI server |
| `CONFIG_DIR`    | `.`     | Path to directory containing `config.py` and log files |
| `DISCOGS_CHILD` | *(unset)* | Set to `1` in child subprocesses to skip duplicate log file writes |

**Behaviour:**

1. Serves the album table UI rendered via Jinja2 templates (`templates/index.html`, `templates/albums.html`).
2. Triggers batch scripts (`fixtags`, `bliss`, `update_lyrics`, `nzbfix`) asynchronously.
3. Streams child subprocess `sys.stdout` JSON lines directly into the HTMX log modal.
4. Manages single active child process state (`_current_proc`); handles emergency termination via `POST /log/kill`.
5. Automatically fetches and caches favicons for up to 5 custom toolbar link buttons to `config_dir/link_favicon_N.ico`.
6. Provides an in-place Settings modal to edit `config.py` directly from the web browser.

---

### `album_list.py` — Live album inventory

**Purpose:** Scan a FLAC library into a CSV and keep it up to date via filesystem monitoring.

**Usage:**

```
uv run album_list.py [FLAC_DIR]
```

| Argument   | Required | Description                                             |
|------------|----------|---------------------------------------------------------|
| `FLAC_DIR` | No       | Root of the FLAC library.  Falls back to `config.flacdir`. |

**Behaviour:**

1. Walks `FLAC_DIR` recursively, reading one FLAC file per album directory.
2. Writes `albums.csv` and `albums_dr.png` in the current working directory.
3. Starts a watchdog observer; updates the CSV automatically on FLAC create / modify / delete events.
4. Runs indefinitely — press **Ctrl-C** to stop.

**Output files:**

| File           | Format  | Description                                     |
|----------------|---------|-------------------------------------------------|
| `albums.csv`   | CSV     | One row per album, columns from `DISPLAY_NAMES` |
| `albums_dr.png`| PNG 150 dpi | Bar chart of album count per DR value       |

**Tags read:** `ALBUMARTIST`, `ALBUM`, `ALBUM DYNAMIC RANGE`, `ORIGINAL_TITLE`,
`ORIGINALDATE`, `RELEASEDATE`, `CATALOGNUMBER`, `DISCOGS_RELEASE_ID`,
`MUSICBRAINZ_ALBUMID`, `SUBTITLE`

**Tags written:** none

---

### `fixtags.py` — Discogs metadata enrichment

**Purpose:** Normalise FLAC tags using data fetched from the Discogs API.

**Usage:**

```
uv run fixtags.py [--configfile | DIRECTORY]
```

| Argument / Flag | Required | Description                                           |
|-----------------|----------|-------------------------------------------------------|
| `DIRECTORY`     | No       | Album directory (or root) to process.                 |
| `--configfile`  | No       | Use `config.flacdir` instead of a positional argument.|

At least one of the two must be provided; otherwise help is printed.

**Behaviour:**

1. Walks `DIRECTORY` recursively to find all subdirectories containing FLAC files.
2. For each album directory, reads `DISCOGS_RELEASE_ID` from the first FLAC found.
3. Queries the Discogs API (1 s sleep per album) for release and master-release metadata.
4. Writes the following tags to every FLAC file in the directory if any value changed:
   - `RELEASEDATE`, `DATE` — year of this specific pressing
   - `ORIGINALDATE`, `ORIGINALRELEASEDATE` — year of the original master release
   - `ALBUM` — formatted as `"<title> [<year> <desc> <kHz>DR<dr>]"`
   - `ORIGINAL_TITLE` — canonical Discogs title

**Tags read:** `DISCOGS_RELEASE_ID`, `ORIGINAL FILENAME`, `DATE`, `SUBTITLE`,
`ALBUM DYNAMIC RANGE`

**Tags written:** `RELEASEDATE`, `DATE`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`,
`ALBUM`, `ORIGINAL_TITLE`

**External service:** Discogs REST API — requires `api_key` in `config.py`.

---

### `calculate_dr.py` — Dynamic Range calculation

**Purpose:** Compute and store the EBU R 128 / DR-meter Dynamic Range score for each track and album.

**Usage:**

```
uv run calculate_dr.py [FLAC_DIR]
```

| Argument   | Required | Description                                             |
|------------|----------|---------------------------------------------------------|
| `FLAC_DIR` | No       | Root of the FLAC library.  Falls back to `config.flacdir`. |

**Behaviour:**

1. Walks `FLAC_DIR` recursively to find all album directories.
2. For each album, reads the `DYNAMIC RANGE` tag from every FLAC.
   - If absent, computes the score via `drmeter` + `soundfile` and writes it back.
3. Derives the album DR score as the rounded mean of all per-track scores.
4. Writes `ALBUM DYNAMIC RANGE` to every file in the album when the value changed.

**Tags read:** `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`, `TITLE`, `ALBUM`

**Tags written:** `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`

**External tools:** none (pure Python via `drmeter` / `soundfile`)

---

### `calculate_fp.py` — AcoustID fingerprint generation

**Purpose:** Compute and store AcoustID acoustic fingerprints for every FLAC track.

**Usage:**

```
uv run calculate_fp.py [FLAC_DIR]
```

| Argument   | Required | Description                                             |
|------------|----------|---------------------------------------------------------|
| `FLAC_DIR` | No       | Root of the FLAC library.  Falls back to `config.flacdir`. |

**Behaviour:**

1. Walks `FLAC_DIR` recursively to find all album directories.
2. For each FLAC, checks for an existing `ACOUSTID FINGERPRINT` tag.
3. If absent, runs `fpcalc` via `pyacoustid` and stores the result.
4. Logs counts of generated vs total tracks per album.

**Tags read:** `ACOUSTID FINGERPRINT`

**Tags written:** `ACOUSTID FINGERPRINT`

**External tools:** `fpcalc` (Chromaprint) must be installed and on `$PATH`.

---

### `update_lyrics.py` — Lyrics fetcher

**Purpose:** Download and embed synced (LRC) or plain-text lyrics for every FLAC track.

**Usage:**

```
uv run update_lyrics.py [FLAC_DIR]
```

| Argument   | Required | Description                                             |
|------------|----------|---------------------------------------------------------|
| `FLAC_DIR` | No       | Root of the FLAC library.  Falls back to `config.flacdir`. |

**Behaviour:**

1. Walks `FLAC_DIR` recursively to find all album directories.
2. For each album, reads `ORIGINAL_TITLE` from the first FLAC as the album name.
3. For each FLAC:
   - Skips if the `LYRICS` tag already contains LRC-format content (timestamp pattern `[mm:ss.xx]`).
   - Queries lrclib.net with artist, title, album, and duration.
   - Writes synced LRC lyrics if available, otherwise plain-text lyrics when the tag was empty.
4. Saves modified files immediately after each successful fetch.
5. Prints summary totals: LRC count, plain-text count, no-lyrics count, and new writes.

**Tags read:** `LYRICS`, `DISCOGS_RELEASE_ID`, `ORIGINAL_TITLE`, `ARTIST`, `TITLE`

**Tags written:** `LYRICS`

**External service:** lrclib.net REST API (`GET /api/get`)

---

### `bliss.py` — Library organiser & MP3 mirror

**Purpose:** Reorganise FLAC files into a canonical directory/filename structure and maintain a parallel MP3 mirror.

**Usage:**

```
uv run bliss.py [--ingest DIR | --full | --mp3]
```

| Flag / Argument | Description                                                              |
|-----------------|--------------------------------------------------------------------------|
| *(none)*        | Quick scan: reorganise only files directly in `flacroot` (non-recursive). |
| `--ingest DIR`  | Move all FLACs from `DIR` into `flacroot`, then clean up empty dirs.     |
| `--full`        | Recursively reorganise the entire `flacroot` tree.                        |
| `--mp3`         | Delete stale MP3 dirs, then transcode any missing ones with ffmpeg.      |

**Directory structure enforced:**

```
<flacroot>/<ALBUMARTIST>/<ALBUM>/<DISCNUMBER>_<TRACKNUMBER>_<TITLE>.flac
<mp3root>/<ALBUMARTIST>/<ALBUM>/<DISCNUMBER>_<TRACKNUMBER>_<TITLE>.mp3
```

All path components are sanitised by `clean()`: punctuation removed, spaces replaced
with underscores, German umlauts transliterated.

**Tags read:** `TITLE`, `ALBUM`, `ALBUMARTIST`, `DISCNUMBER`, `TRACKNUMBER`

**Tags written:** none

**External tools:** `ffmpeg` with `libmp3lame` (required for `--mp3`).

**Hardcoded paths** (edit globals at top of file):

| Variable   | Default               |
|------------|-----------------------|
| `flacroot` | `/Volumes/flac/`      |
| `mp3root`  | `/Volumes/MP3/`       |
| `opusroot` | `/Volumes/Opus/`      |

---

### `nzbfix.py` — Post-download pipeline

**Purpose:** Run the full enrichment pipeline on a newly downloaded/ripped album directory.

**Usage:**

```
uv run nzbfix.py [FLAC_DIR]
```

| Argument   | Required | Description                                              |
|------------|----------|-----------------------------------------------------------|
| `FLAC_DIR` | No       | Directory to process.  Falls back to `config.flacdir`.   |

**Pipeline executed (in order):**

1. `dot_clean <dir>` — remove macOS resource-fork files
2. `calculate_dr.py <dir>` — compute per-track and album DR
3. `rsgain easy -m MAX --skip-existing <dir>` — calculate ReplayGain tags
4. `calculate_fp.py <dir>` — generate AcoustID fingerprints
5. `fixtags.py <dir>` — enrich tags from Discogs
6. `update_lyrics.py <dir>` — fetch and embed lyrics

**Tags written:** all tags written by the above scripts (see individual entries).

**External tools:** `dot_clean` (macOS), `rsgain`, `ffmpeg`, `fpcalc`.

---

### `lyricscloud.py` — Lyrics word-cloud generator *(experimental)*

**Purpose:** Generate a word-cloud image from embedded lyrics in a FLAC library.

**Usage:**

```
uv run lyricscloud.py
```

No command-line arguments.  The source directory and mask/colour image paths are
**hardcoded** — edit `main()` before use.

**Behaviour:**

1. Reads all `LYRICS` tags from FLAC files under the configured directory.
2. Generates a word cloud shaped by a mask image, with custom stopwords.
3. Saves two output images in the current working directory.

**Output files:**

| File                  | Description                                      |
|-----------------------|--------------------------------------------------|
| `swiftie_cloud.png`   | Plain word-cloud PNG                             |
| `swiftie_colour.png`  | Three-panel matplotlib figure (cloud, recoloured, mask) |

**Hardcoded inputs** (edit `main()` to change):

| Variable            | Default                           |
|---------------------|-----------------------------------|
| `flacdir`           | `/Volumes/FLAC/Taylor_Swift`      |
| mask image          | `swiftie_mask.png` (current dir)  |
| colour image        | `RG_6K.png` (current dir)        |

**Tags read:** `LYRICS`

**Tags written:** none

---

## Typical workflow

```
# 1. Ingest a new album from downloads
uv run bliss.py --ingest /Volumes/FLAC/Downloads/NewAlbum/

# 2. Run the full enrichment pipeline on the ingested directory
uv run nzbfix.py /Volumes/flac/Artist/Album/

# 3. Rebuild the album inventory CSV
uv run album_list.py /Volumes/flac/

# 4. (Periodic) Sync the MP3 mirror
uv run bliss.py --mp3
```
