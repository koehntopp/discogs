# FLAC Library Tools — CLI Specification

This document describes the command-line interface, configuration, tag contracts, and
data flows for every script in this repository.

---
## Agent Guidelines & Approval Workflow

- **Mandatory Implementation Plans**: You MUST create an `implementation_plan.md` artifact for any change, regardless of how minor or trivial it seems. Do not skip the planning phase for simple tweaks or quick bug fixes.
- **No Unapproved Edits**: You are strictly prohibited from modifying any source code files, configurations, or running write/exec commands until the user has explicitly approved the implementation plan.
- **Discuss First**: Always discuss your proposed design choices with the user and wait for approval before shifting from the planning/research phase to the execution phase.
- **Mandatory Automatic Documentation Synchronization**: After every code change, specification and documentation files (`SPEC.md`, `README.md`, and ADRs in `docs/adr/`) MUST be automatically updated to reflect the new codebase state, ensuring documentation is never outdated.
- **Mandatory Meaningful Git Commits**: After completing every code change and verifying tests/linting, all modified files MUST be committed with a concise, descriptive, and meaningful Git commit message summarizing the work completed.
- **No Production Data Testing**: NEVER run verification tests or test code on active/production library data (e.g. `/Volumes/FLAC`). When required, copy a small subset of the target files to a temporary directory (e.g., `/tmp`) on a completely different root path before testing.



## Script Execution & Shebang

All standalone Python scripts begin with the `uv` shebang line:
```python
#!/usr/bin/env -S uv run
```
Scripts can be executed directly from the terminal (e.g. `./fixtags.py [args]` or `./bliss.py [args]`) or via `uv run <script>.py [args]`. Inline dependencies are managed automatically via PEP 723 metadata headers.

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

Tags are stored uppercase in Vorbis comment fields. The scripts use the following
tag names consistently:

| Tag                     | Set by        | Read by                          |
|-------------------------|---------------|----------------------------------|
| `ALBUMARTIST`           | ripping tool  | album_list, bliss, fixtags       |
| `ALBUM`                 | fixtags       | album_list, bliss, update_lyrics |
| `DISCOGS_RELEASE_ID`    | ripping tool  | fixtags, update_lyrics           |
| `MUSICBRAINZ_ALBUMID`   | ripping tool  | album_list                       |
| `DATE` / `RELEASEDATE`  | fixtags       | album_list                       |
| `ORIGINALDATE`          | fixtags       | album_list                       |
| `ORIGINALRELEASEDATE`   | fixtags       | —                                |
| `CATALOGNUMBER` / `CATALOG NUMBER` | Yate / ripping tool | album_list, webui |
| `SUBTITLE`              | ripping tool  | fixtags (album description)      |
| `DYNAMIC_RANGE`         | calculate_dr  | calculate_dr (replaces DYNAMIC RANGE) |
| `ALBUM_DR`              | calculate_dr  | fixtags (replaces ALBUM DYNAMIC RANGE) |
| `ACOUSTID_FINGERPRINT`  | calculate_fp  | calculate_fp (replaces ACOUSTID FINGERPRINT) |
| `LYRICS`                | update_lyrics | lyricscloud                      |
| `TITLE`                 | ripping tool  | bliss, update_lyrics             |
| `TRACKNUMBER`           | ripping tool  | bliss                            |
| `DISCNUMBER`            | ripping tool  | bliss                            |
| `ARTIST`                | ripping tool  | update_lyrics                    |
| **Structured Metadata:**|               |                                  |
| `ALBUM_MASTER_TITLE`    | fixtags       | album_list, bliss, update_lyrics |
| `ALBUM_MASTER_YEAR`     | fixtags       | —                                |
| `ALBUM_RELEASE_TITLE`   | fixtags       | —                                |
| `ALBUM_RELEASE_YEAR`    | fixtags       | —                                |
| `ALBUM_MAX_RESOLUTION`  | fixtags       | —                                |
| `ALBUM_EDITION`         | fixtags       | —                                |
| `ALBUM_FORMAT`          | fixtags       | —                                |
| `ALBUM_RELEASE_COUNTRY` | fixtags       | —                                |
| `ALBUM_RELEASE_LABEL`   | fixtags       | —                                |
| `ALBUM_TITLE_OVERRIDE`  | user          | fixtags (manual override)        |
| `ALBUM_ARTIST_OVERRIDE` | user          | fixtags (manual override)        |

> [!NOTE]
> Tags containing spaces (e.g. `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`, `ACOUSTID FINGERPRINT`) are deprecated to adhere to the Vorbis Comment standard of `[A-Z0-9_]` character limits. Existing files will be transitioned during script runs.

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
- [ADR 0004: Album List Caching and Direct Lyrics Export Architecture](file:///Users/koehntopp/src/discogs/docs/adr/0004-performance-caching-and-lyrics-export-architecture.md)
- [ADR 0005: MP3 Mirror Transcoding and Multi-Copy Library Comparison](file:///Users/koehntopp/src/discogs/docs/adr/0005-mp3-transcoding-and-library-comparison.md)

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
| `LOG_LEVEL`     | `SUCCESS` | Active log verbosity (`DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`). Set to `SUCCESS` (25) to suppress `INFO` logs. |
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
./album_list.py [-f | --force] [FLAC_DIR]
```

| Flag / Argument | Required | Description                                             |
|-----------------|----------|---------------------------------------------------------|
| `FLAC_DIR`      | No       | Root of the FLAC library. Falls back to `config.flacroot`.|
| `-f`, `--force` | No       | Force a full re-scan, bypassing `album_cache.json`.      |

**Behaviour:**

1. Walks `FLAC_DIR` recursively, discovering all subdirectories containing FLAC files.
2. Checks `album_cache.json` using the maximum modification time (`mtime`) across all FLAC tracks in each directory. Re-scans only modified or new albums (unless `--force` is given).
3. Writes `albums.csv` and `albums_dr.png` in `config_dir`.

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

1. Walks `DIRECTORY` recursively to find all subdirectories containing FLAC files and initializes a Rich TTY progress bar (log messages render cleanly above the bar).
2. For each album directory, reads `DISCOGS_RELEASE_ID` from the first FLAC found.
3. Queries the Discogs API (1 s sleep per album) for release and master-release metadata.
4. Writes the following tags to every FLAC file in the directory if any value changed:
   - `RELEASEDATE`, `DATE`, `YEAR` — year of this specific pressing
   - `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR` — year of the original master release
   - `ALBUM_MASTER_TITLE` — canonical master release title from Discogs
   - `ALBUM_MASTER_YEAR` — original release year
   - `ALBUM_RELEASE_TITLE` — specific release title
   - `ALBUM_RELEASE_YEAR` — pressing release year
   - `ALBUM_EDITION` — edition information (e.g. Deluxe Edition, Remaster; extracted from `()` brackets in existing `ALBUM` titles if tag is missing)
   - `ALBUM_RELEASE_COUNTRY` — pressing release country
   - `ALBUM_RELEASE_LABEL` — pressing record label
   - `ALBUM_FORMAT` — format of the audio source (default "CD")
   - `ALBUM_MAX_RESOLUTION` — maximum sample rate of tracks in the folder (e.g., 44.1kHz, 96kHz)
   - `ALBUM_DR` — album dynamic range score (mirrored from ALBUM DYNAMIC RANGE)
   - `ALBUM` — clean master release title for players (e.g. `Brothers in Arms`). Taken from `ALBUM_TITLE_OVERRIDE` if present, otherwise clean `ALBUM_MASTER_TITLE` or `ORIGINAL_TITLE`.
   - `VERSION` — release decoration string for Roon version display (no square brackets): `<year> <format>` or `<year> <format> (<edition>)` (e.g., `2025 Blu-ray (40th Anniversary Edition)`).

**Tags read:** `DISCOGS_RELEASE_ID`, `ORIGINAL FILENAME`, `DATE`, `SUBTITLE`,
`ALBUM_DR` (or deprecated `ALBUM DYNAMIC RANGE`), `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`

**Tags written:** `RELEASEDATE`, `DATE`, `YEAR`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR`,
`ALBUM`, `VERSION`, `ALBUM_MASTER_TITLE`, `ALBUM_MASTER_YEAR`, `ALBUM_RELEASE_TITLE`,
`ALBUM_RELEASE_YEAR`, `ALBUM_EDITION`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`,
`ALBUM_FORMAT`, `ALBUM_MAX_RESOLUTION`, `ALBUM_DR`

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
2. For each album, reads the `DYNAMIC_RANGE` tag (with fallback to deprecated `DYNAMIC RANGE`) from every FLAC.
   - If absent, computes the score via `drmeter` + `soundfile` and writes `DYNAMIC_RANGE` back.
3. Derives the album DR score as the rounded mean of all per-track scores.
4. Writes `ALBUM_DR` to every file in the album when the value changed.

**Tags read:** `DYNAMIC_RANGE` (or `DYNAMIC RANGE`), `ALBUM_DR` (or `ALBUM DYNAMIC RANGE`), `TITLE`, `ALBUM`

**Tags written:** `DYNAMIC_RANGE`, `ALBUM_DR`

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
2. For each FLAC, checks for an existing `ACOUSTID_FINGERPRINT` tag (with fallback to deprecated `ACOUSTID FINGERPRINT`).
3. If absent, runs `fpcalc` via `pyacoustid` and stores the result in `ACOUSTID_FINGERPRINT`.
4. Logs counts of generated vs total tracks per album.

**Tags read:** `ACOUSTID_FINGERPRINT` (or `ACOUSTID FINGERPRINT`)

**Tags written:** `ACOUSTID_FINGERPRINT`

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
2. For each album, extracts canonical Discogs master title (`ALBUM_MASTER_TITLE` $\rightarrow$ `ORIGINAL_TITLE`) as the primary clean album name for lrclib.net.
3. For each FLAC:
   - Skips if the `LYRICS` tag already contains LRC-format content (timestamp pattern `[mm:ss.xx]`).
   - Stage 1: Queries lrclib.net with artist, title, clean album name, and duration.
   - Stage 2: If Stage 1 returns 404, retries lrclib.net with artist, title, and duration (omitting album name).
   - Writes synced LRC lyrics if available, otherwise plain-text lyrics when the tag was empty.
4. Saves modified files immediately after each successful fetch.
5. Prints summary totals: LRC count, plain-text count, no-lyrics count, and new writes.

**Tags read:** `LYRICS`, `DISCOGS_RELEASE_ID`, `ARTIST`, `ALBUM_ARTIST_OVERRIDE`, `ALBUMARTIST`, `TITLE`, `ALBUM_MASTER_TITLE`, `ORIGINAL_TITLE`, `ALBUM_TITLE_OVERRIDE`, `ORIGINAL FILENAME`, `ALBUM`

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

### `migrate_tags.py` — FLAC structured tag schema migration

**Purpose:** Walk a FLAC library, extract metadata from existing tags and decorated album titles, and migrate all files to the structured underscore tag schema (`ALBUM_MASTER_TITLE`, `ALBUM_RELEASE_YEAR`, `ALBUM_FORMAT`, `ALBUM_EDITION`, `ALBUM_DR`, `DYNAMIC_RANGE`, `ACOUSTID_FINGERPRINT`). Includes live rich progress bar display.

**Usage:**

```bash
uv run migrate_tags.py [--write] [DIR]
```

| Argument | Required | Description |
|---|---|---|
| `DIR` | No | Root directory to scan (defaults to `config.flacroot`). |
| `--write` | No | Apply changes directly to FLAC files (default is dry-run mode). |

---

### `dump_original_filenames.py` — Export albums with ORIGINAL FILENAME tag

**Purpose:** Scan a FLAC library and export a CSV summary (`file_path`, `album_name`, `discogs_album_title`, `ORIGINAL FILENAME`) for all albums containing the `ORIGINAL FILENAME` tag.

**Usage:**

```bash
uv run dump_original_filenames.py [-o OUTPUT_CSV] [DIR]
```

| Argument | Required | Description |
|---|---|---|
| `DIR` | No | Root directory to scan (defaults to `config.flacroot`). |
| `-o`, `--output` | No | Output CSV file path (defaults to `albums_original_filename.csv`). |

---

### `compare_libraries.py` — Compare directory structure and track counts between libraries

**Purpose:** Walk a reference FLAC library (e.g. a backup copy) and compare its album directories and track counts against a target library (defaults to `config.flacroot`), generating a CSV report (`library_comparison.csv`).

**Usage:**

```bash
uv run compare_libraries.py /path/to/reference_library [--target /path/to/target_library] [-s] [-o library_comparison.csv]
```

| Argument | Required | Description |
|---|---|---|
| `reference_dir` | Yes | Path to the reference / backup FLAC library root. |
| `--target` | No | Path to target library root (defaults to `config.flacroot`). |
| `-s`, `--stats` | No | List total albums, FLAC song count, and average tracks/album for `reference_dir` instead of comparing. |
| `-o`, `--output` | No | Output CSV report path (defaults to `library_comparison.csv`). |

---

### `align_lyrics.py` — Whisper LRC timestamp alignment

**Purpose:** Read LRC or plain TXT lyrics from FLAC tags and use a local OpenAI Whisper
speech-to-text model to produce word-level timestamps. Each lyrics line is aligned against
the transcription to suggest improved `[MM:SS.xx]` timestamps.

**Usage:**

```bash
uv run align_lyrics.py [TARGET] [OPTIONS]
```

| Argument / Option | Default | Description |
|---|---|---|
| `TARGET` | `.` | Directory or single `.flac` file to process. |

| `--model`, `-m` | `base` | Whisper model size: `tiny` / `base` / `small` / `medium` / `large` / `turbo`. |
| `--device`, `-d` | `auto` | Torch device: `auto` (cuda → mps → cpu), `cpu`, `cuda`, `mps`. |
| `--write`, `-w` | off | Overwrite the `LYRICS` tag inside each FLAC file with the suggested LRC. Use `--dry-run` to preview first. |
| `--dry-run` | off | Show suggestions without writing any files (overrides `--write`). |
| `--min-confidence` | `0.5` | Threshold for Whisper alignment confidence (0.0–1.0). Matches below this threshold fall back to existing tag data. |
| `--recursive`, `-r` | off | Recurse into sub-folders. |
| `--anchor-slack` | `5.0` | For LRC input: search Whisper words within ±N seconds of each original timestamp. Increase if original timestamps are badly off. |
| `--no-split` | off | Disable delimiter-based splitting; keep ` / ` and ` \| ` delimiters intact. |
| `--no-segment-split` | off | Disable Whisper-segment-based splitting of large lyric blocks. |

**Behaviour:**

1. Scans `FOLDER` for `*.flac` files (optionally recursive).
2. For each file, reads the first populated lyrics tag in priority order: `LYRICS` → `UNSYNCEDLYRICS` → `COMMENT`.
3. Detects whether the lyrics are LRC (has `[MM:SS.xx]` timestamps) or plain TXT and parses accordingly; LRC header lines (`[ar:]`, `[ti:]`, etc.) are ignored.
4. **Delimiter splitting & Anchor Sanitization** (unless `--no-split`): lines containing ` / ` or ` | ` are expanded into individual sub-lines. Input LRC tags are validated for monotonicity and flat duplicate blocks ($\ge 3$ identical timestamps); corrupted or duplicate anchors are sanitized to ensure clean sequential alignment against speech audio.

5. Transcribes the FLAC with Whisper (`word_timestamps=True`) to obtain a flat word list with start/end timestamps and segment groupings.
6. **Whisper-segment splitting** (unless `--no-segment-split`): after alignment, any lyric line whose matched word window spans multiple Whisper segments (natural pause/breath boundaries) is split into individually-timestamped sub-lines. A minimum of 3 words per segment is required to avoid splitting on short filler segments. If the text cannot be cleanly partitioned (fragment similarity < 0.3), the line is kept intact.
7. **Alignment & Low-Confidence Fallback** — two strategies depending on input format:
   - *LRC (time-anchor)*: for each line, searches only Whisper words whose start time falls within `±anchor_slack` seconds of the original timestamp.
   - *Plain TXT (greedy)*: searches a forward look-ahead of `max(n×3, 20)` words from the cursor position; cursor advances past each match.
   - **Low-confidence fallback**: if Whisper alignment confidence is below `--min-confidence` (default 0.50), the existing tag timestamp (`original_ts`) is preserved instead of accepting an unreliable Whisper match. These lines are marked `(tag fallback)` in the comparison table.


8. Renders a Rich comparison table: original timestamp | suggested timestamp | Δ seconds | confidence score | lyric text.
9. For lines below `--min-confidence`, prints a per-line diagnostic table showing the lyric text alongside what Whisper actually transcribed in that time window (or `(nothing in window)` if Whisper produced no output there).
10. Prints a summary table and emits structured log events (`logger.info("timestamp_changed", ...)`) for all lines whose timestamps actually changed.
11. Displays a full suggested LRC preview (with `[ar:]`/`[ti:]`/`[al:]` headers from FLAC tags) in a syntax-highlighted panel. All lines are guaranteed to have a `[MM:SS.xx]` timestamp.
12. With `--write`, overwrites the `LYRICS` tag in each FLAC file with the suggested LRC string.

**Tags read:** `LYRICS`, `UNSYNCEDLYRICS`, `COMMENT`, `ARTIST`, `ALBUMARTIST`, `TITLE`, `ALBUM`

**Tags written:** `LYRICS` (when `--write` is specified)

**Dependencies:** `openai-whisper`, `torch`, `mutagen`, `rich`, `click`, `numpy`



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
