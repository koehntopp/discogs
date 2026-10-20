# FLAC Library Tools — CLI Specification

This document describes the command-line interface, configuration, tag contracts, and
data flows for every script in this repository.

---

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
| Discogs REST API   | fixtags, find_audiophile_upgrades | HTTPS    | 1 req/s (sleep 1.1 s)  |
| lrclib.net REST API| update_lyrics, lrclib_submitter | HTTPS    | PoW challenge token required for publish |
| OpenAI Whisper     | align_lyrics   | local    | —                    |
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
- [ADR 0006: Whisper Speech-to-Text LRC Lyrics Alignment, Time-Anchor Search, and Fallback Architecture](file:///Users/koehntopp/src/discogs/docs/adr/0006-whisper-lrc-alignment-and-fallback.md)
- [ADR 0007: LRCLIB Lyrics Submission & Proof-of-Work Challenge Solver Architecture](file:///Users/koehntopp/src/discogs/docs/adr/0007-lrclib-lyrics-submission-proof-of-work.md)
- [ADR 0008: Roon-Specific Tag Conventions](file:///Users/koehntopp/src/discogs/docs/adr/0008-roon-specific-tag-conventions.md)

Also see [docs/tag-schema.md](file:///Users/koehntopp/src/discogs/docs/tag-schema.md) — a Mermaid ERD of the FLAC tag relationships defined in ADR 0002/0008.

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
uv run fixtags.py [--configfile | DIRECTORY] [--languages-only] [--refresh-musicbrainz]
```

| Argument / Flag | Required | Description                                           |
|-----------------|----------|-------------------------------------------------------|
| `DIRECTORY`     | No       | Album directory (or root) to process.                 |
| `--configfile`  | No       | Use `config.flacdir` instead of a positional argument.|
| `--languages-only` | No    | Only write `LYRICS_LANGUAGE` from MusicBrainz: no Discogs lookups, no cover resizing, no other tag. Fast across a whole library (one cached MusicBrainz request per album). |
| `--refresh-musicbrainz` | No | Ignore cached MusicBrainz answers (30 days) and ask again. |

At least one of the two must be provided; otherwise help is printed.

**Behaviour:**

1. Walks `DIRECTORY` recursively to find all subdirectories containing FLAC files and initializes a Rich TTY progress bar (log messages render cleanly above the bar).
2. For each album directory, reads `DISCOGS_RELEASE_ID` from the first FLAC found.
3. Queries the Discogs API (1 s sleep per album) for release and master-release metadata.
4. Writes the following tags to every FLAC file in the directory if any value changed:
   - `RELEASEDATE`, `DATE`, `YEAR` — year of this specific pressing, from the Discogs release (Discogs master year only if the release has none); overwritten on every run when it disagrees, never read back from the tags
   - `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR` — year of the original master release
   - `ALBUM_MASTER_TITLE` — canonical master release title from Discogs
   - `ALBUM_MASTER_YEAR` — original release year
   - `ALBUM_RELEASE_TITLE` — specific release title
   - `ALBUM_RELEASE_YEAR` — pressing release year, taken only from the Discogs release's own year; not written (and removed) if Discogs has none
   - `ALBUM_EDITION` — edition information (e.g. Deluxe Edition, Remaster; extracted from `()` brackets in existing `ALBUM` titles if tag is missing)
   - `ALBUM_RELEASE_COUNTRY` — pressing release country
   - `ALBUM_RELEASE_LABEL` — pressing record label
   - `ALBUM_FORMAT` — format of the audio source (default "CD")
   - `ALBUM_MAX_RESOLUTION` — maximum sample rate of tracks in the folder (e.g., 44.1kHz, 96kHz)
   - `ALBUM_DR` — album dynamic range score (mirrored from ALBUM DYNAMIC RANGE)
   - `ALBUM` — clean master release title for players (e.g. `Brothers in Arms`). Taken from `ALBUM_TITLE_OVERRIDE` if present, otherwise clean `ALBUM_MASTER_TITLE` or `ORIGINAL_TITLE`.
   - `VERSION` — release decoration string for Roon version display: `<year> DR<xx> <format> (<edition>) (<catalog number>)` (e.g., `2025 DR09 Blu-ray (40th Anniversary Edition) (DGCD 12345)`). `DR<xx>` (two-digit, zero-padded) and the parenthesized catalog number are each appended only when available.
   - `ALBUMARTIST` — only when `ALBUM_ARTIST_OVERRIDE` is set: written verbatim (a manual correction, not derived from Discogs), permanently replacing whatever was there. Left completely untouched when the override is absent.
5. Writes the following tags **per track** (not uniformly — each file's own value, independent of step 4's album-wide set), for Roon box-set grouping (see ADR 0008):
   - `PART` — always that track's own `TITLE`.
   - `WORK` — that track's own `SET SUBTITLE` when present (a tag the user sets manually, per disc, within multi-disc editions); removed if `SET SUBTITLE` is later cleared on that track.
6. Writes `LYRICS_LANGUAGE` **per track** from MusicBrainz (`musicbrainz_client.py`, ADR 0002 section 5b): the sung language(s) of the track's work as ISO 639-3 codes (`eng`, `deu`, `ksh`, `gle`; `mul`/`und`/`zxx` as MusicBrainz uses them), repeated values for several languages. The release comes from the user-set `MUSICBRAINZ_ALBUMID`; a file is matched to its MusicBrainz track by `MUSICBRAINZ_RELEASETRACKID`, else by disc/track number when the title agrees (another edition of the album is left alone). A matched track without a sung language loses the tool-owned tag; a failed lookup changes nothing. Switch off with `musicbrainz_languages = False` in `config.py`.

**Tags read:** `DISCOGS_RELEASE_ID`, `MUSICBRAINZ_ALBUMID` (or `MUSICBRAINZ ALBUM ID`), `MUSICBRAINZ_RELEASETRACKID`, `DISCNUMBER`, `TRACKNUMBER`, `DATE`, `SUBTITLE`, `SET SUBTITLE`, `TITLE`,
`ALBUM_DR` (or deprecated `ALBUM DYNAMIC RANGE`), `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`,
`CATALOGNUMBER` (or `CATALOG NUMBER` / `CATALOG_NUMBER` / `CATALOGNO`)

**Tags written:** `RELEASEDATE`, `DATE`, `YEAR`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR`,
`ALBUM`, `VERSION`, `ALBUM_MASTER_TITLE`, `ALBUM_MASTER_YEAR`, `ALBUM_RELEASE_TITLE`,
`ALBUM_RELEASE_YEAR`, `ALBUM_EDITION`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`,
`ALBUM_FORMAT`, `ALBUM_MAX_RESOLUTION`, `ALBUM_DR`, `ALBUMARTIST` (only when `ALBUM_ARTIST_OVERRIDE` is set), `PART`, `WORK`, `LYRICS_LANGUAGE` (per-track)

**External services:** Discogs REST API — requires `api_key` in `config.py`; MusicBrainz web service (language only, 1 request per second, cached in `config_dir/musicbrainz/`).

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
2. For each FLAC:
   - The "artist" used for the lrclib.net query, the `[ar:]` LRC header, and log messages is sourced from `ALBUMARTIST`, falling back to `ARTIST` only when `ALBUMARTIST` is empty — not the track's own `ARTIST` credit, which can carry rip-specific billing (e.g. `Roy Orbison With Guests`) that lrclib.net's artist index won't match.
   - If the `LYRICS` tag already contains valid LRC-format content (timestamp pattern `[mm:ss.xx]`), refreshes the `[ar:]`/`[ti:]`/`[al:]`/`[length:]` headers and re-normalizes characters and line capitalization in place, without querying lrclib.net. **update_lyrics only ever replaces TXT or empty lyrics**: an existing LRC is never replaced by another source or deleted, only corrected in place. (A tag whose only timestamps have 3+ digit minutes, `[HH:MM:SS.xx]`, is not LRC and is handled like TXT; the former invalid-LRC replace-or-clear branch is gone.)
   - If the `LYRICS` tag already contains the instrumental marker (`[instrumental:true]`), skips it without querying lrclib.net.
   - Otherwise, Stage 1: Queries lrclib.net with artist, title, the FLAC's own `ALBUM` tag, and duration.
   - Stage 2: If Stage 1 returns 404, retries lrclib.net with artist, title, and duration (omitting album).
   - Stage 3/4: If the title ends in a bracketed group (e.g. `(Live at Wembley)`), repeats Stages 1-2 with that group stripped from the search title only; the tag keeps the full title.
   - **Failure handling**: a 429, 5xx or network error is not "not found". lrclib asks for sequential requests, so one `Pacer` shared by all 8 workers (which keep reading tags in parallel) lets only one lrclib request be in flight and starts them at least 0.5 s apart (120 requests/min). Only HTTP 429, a real rate limit, widens that spacing: it doubles (up to 8 s), `Retry-After` is honoured with up to 30% random jitter, and every 10 consecutive good answers shrink it by a quarter again. A 5xx or network error leaves the spacing alone and is retried after a plain backoff (1, 2, 4 s plus jitter, or the server's `Retry-After`); recovered ones are not logged. After 5 failures in a row of any kind with no success for 60 s lrclib is treated as down and the remaining tracks are deferred. A track whose request keeps failing (4 attempts) is marked `failed`: nothing is written or cleared for it (an existing invalid LRC is never deleted because of a server error) and no further title variants are tried. Failed tracks are retried after the main pass, after a 30 s and then a 60 s cool-down, with 2 workers each. Tracks still failing are listed by artist, title and path in a warning; the exit code stays 0 so `nzbfix.py` continues, and re-running picks them up again.
   - **Not found**: a track with no existing lyrics for which lrclib has no match (404 on every title variant) gets a plain warning `No lyrics found at lrclib: '<title>' (artist searched: '<ALBUMARTIST or ARTIST>', album: '<ALBUM>')`, so it can be corrected by hand (e.g. via `ALBUM_ARTIST_OVERRIDE`).
   - If lrclib.net's response flags the track `instrumental: true`, writes a fixed-format LRC marker (`[la:zxx]` / `[instrumental:true]` / `[00:00.00](Instrumental)`) instead of lyrics.
   - Otherwise writes synced LRC lyrics if available, otherwise plain-text lyrics when the tag was empty.
   - **Character normalization** (`lrc_format.normalize_text`, applied to new fetches, existing TXT and existing LRC alike, never to the `[ti:]`/`[ar:]`/`[al:]`/`[length:]`/`[re:]` header lines): typographic characters are mapped to ASCII (`’ ‘` to `'`, `“ ”` to `"`, hyphen variants and en/em dashes to `-`, `…` to `...`, non-breaking and thin spaces to a space, `´`/backtick between two letters to `'`) and invisible junk (zero-width space, BOM, word joiner, Hangul filler U+3164, object replacement U+FFFC) is removed; accented letters, other scripts and `♪`/`♡` are left alone. `lrc_fix.py` applies the same function to its output and folds apostrophes the same way when matching lyric lines against the transcript.
   - **Capitalization normalization**: every lyric line — newly fetched or already embedded — has its first non-whitespace character uppercased (LRC header lines are left untouched).
   - **Timestamp whitespace stripping**: for LRC lines, any whitespace between the `[MM:SS.xx]` timestamp and the lyric text is removed (`[MM:SS.xx]Text`, not `[MM:SS.xx] Text`).
   - **Instrumental via `LYRICS_LANGUAGE`**: if the track's `LYRICS_LANGUAGE` is exactly `zxx` (MusicBrainz: no vocals) and the `LYRICS` tag is empty or plain text, the canonical instrumental marker is written without an lrclib.net request and counted as `Instrumental`. An existing synced LRC is never replaced.
   - **Manual instrumental marking**: if the `LYRICS` tag contains a hand-typed `[MM:SS.xx][Instrumental]` marker (case-insensitive), it's normalized to the canonical instrumental block without an lrclib.net request, as if the API had reported `instrumental: true`.
3. Saves modified files immediately after each successful fetch or fix.
   **Lyrics cache** (`config_dir/lyrics/{discogs_id}_{track}.lrc|txt`, key unchanged, so on a multi-disc set with per-disc track numbers the discs share a key): written only when the content differs, so unchanged entries keep their modification time; after a complete run, entries whose key no track of that id has any more (e.g. after a `TRACKNUMBER` retag `8` to `08`) are removed. An id is pruned only if all its tracks in the run come from one directory and none was unreadable; tracks whose lookup failed keep their entry; an interrupted run prunes nothing.
4. Prints summary totals: LRC count, plain-text count, no-lyrics count, instrumental count, new and fixed write counts, the number of tracks still failed after the retry rounds, and the cache counts (written, unchanged, pruned).

**Tags read:** `LYRICS`, `DISCOGS_RELEASE_ID`, `ALBUMARTIST`, `ARTIST`, `TITLE`, `TRACKNUMBER`, `ALBUM`

**Tags written:** `LYRICS`

**Shared with `lrc_fix.py`:** header build/refresh, instrumental marker format, and capitalization normalization live in `lrc_format.py` (sibling module, no CLI of its own) — see ADR 0002 §6.

**External service:** lrclib.net REST API (`GET /api/get`). Requests identify the application with `User-Agent` and the public `Lrclib-App-Id` header from `lrclib_client.py` (client identification and rate limits: https://lrclib.net/docs#implementation-requirements-client-identification); an invalid id gives `401`, which is logged once and not retried. Requests are sent one at a time, at least 0.5 s apart (120 requests/min, two thirds of the ~180/min allowed for a registered app), and `Retry-After` is honored with up to 30% random jitter.

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

### `lrc_count.py` — Lyrics coverage report by album artist

**Purpose:** Scan a FLAC library and report lyrics coverage aggregated per album artist, to identify artists most in need of an LRC upgrade pass (e.g. via `align_lyrics.py`).

**Usage:**

```bash
uv run lrc_count.py [<flacdir>] [--output <file.csv>] [--tracks | --suspects [--hints]]
```

| Argument | Required | Description |
|---|---|---|
| `flacdir` | No | Root directory to scan (defaults to `config.flacroot`). |
| `--output` | No | Output CSV file path (defaults to stdout). Also writes a sibling `.xlsx` workbook with the same rows/columns next to it. |
| `--tracks` | No | Output one row per track instead of aggregated per-artist counts. |
| `--suspects` | No | List tracks whose synced LRC shows signs of a failed alignment (read-only report). Tracks whose only reasons are the hints `ends_early`/`junk_hearts` are left out. |
| `--hints` | No | With `--suspects`: also list the hint-only tracks. |

**Behaviour:**

1. Walks `flacdir` recursively to find all album directories.
2. For each track, classifies the `LYRICS` tag as instrumental (contains the `[instrumental:true]` marker), synced LRC (has `[MM:SS.xx]` timestamps), plain TXT, or absent (`none`); unreadable files count as `none`.
3. Default mode: aggregates counts across every album by `ALBUMARTIST` (falls back to `ARTIST`); writes CSV rows sorted by highest `txt` count first (ties broken alphabetically by `album_artist`).
4. `--tracks` mode: writes one row per track instead, with the decorated album title (`ALBUM` + `VERSION`, bliss.py's directory-naming convention; falls back to the directory basename if `ALBUM` is empty), sorted by album then disc/track number.

**Output columns (default):** `album_artist`, `lrc`, `txt`, `instrumental`, `no_lyrics`

**Output columns (`--tracks`):** `album_artist`, `album`, `song`, `lyrics_type`

5. `--suspects` mode: for every synced-LRC track runs `lrc_format.lrc_suspect_reasons` (the same function `lrc_fix.py` uses as its quality gate) and writes one row per track with at least one reason, most reasons first: `one_timestamp` (every line on one timestamp), `shared_timestamps` (5+ lines and at least 20% of the lines on one timestamp), `ends_early` (last timestamp before 50% of the track length) and `junk_hearts` (hearts in lyric lines; a line that is only `♪` is a legitimate music marker and is not flagged). `ends_early` and `junk_hearts` are hints, not proof: a long instrumental outro is legitimate, and a lyric often omits repeated choruses. The audit of the suspect tags found about a third of the list was `ends_early` alone and mostly harmless, so such tracks are only listed with `--hints`; `lrc_audit.py` judges them against the audio. Instrumental markers and LRCs with fewer than 3 timestamped lines are never judged. Heuristics catch pile-ups, not every bad alignment.

**Output columns (`--suspects`):** `album_artist`, `album`, `song`, `reasons`, `lines`, `problem_lines`, `last_timestamp`, `length`, `directory` (pass it to `lrc_fix.py`), `yate_link`

`problem_lines` (`lrc_format.lrc_problem_line_count`) counts the lyric lines that are wrong on their own: every line whose timestamp is shared by 3 or more lines, plus every line with a heart (counted once). A pair of lines on one timestamp is legal and not counted; `ends_early` describes the whole track and adds nothing, so a track flagged only for it shows 0. `yate_link` is a Yate deep link to the album directory, built like the web UI's tagger link (`tagger_scheme` + the directory with `flacroot` rebased onto `flacroot_local`); it is empty if those `config.py` keys are missing.

**Tags read:** `LYRICS`, `ALBUMARTIST`, `ARTIST`

**Tags written:** none (read-only)

---

### `lrc_fix.py` — Local LRC realignment (demucs + whisperx)

**Purpose:** Realign `LYRICS` tag timestamps to the actual audio, entirely
locally: demucs vocal isolation, whisperx transcription, difflib sequence
matching and a per-line dynamic-programming match against the known lyric lines, and librosa onset-snapping. No cloud
APIs, no LLM in the timing path. Supersedes the earlier `align_lyrics.py`
(deleted; see ADR 0006, now superseded, and ADR 0009).

Full usage and flags: `README-lrc_fix.md` (own documentation, not duplicated here).
Design decisions (pipeline, quality gate, ASR cache, dependency pins): ADR 0009.

**ASR cache:** the demucs/whisperx word timestamps (and vocal onsets) are cached per track in
`~/.cache/lrc_fix/<discogs_id>_<disc>_<track>.json` (`--cache-dir`, `--no-cache`, `--refresh-cache`), keyed by
whisper model, language, compute type, vocal isolation and the FLAC's sample count; lyric text is never cached.

**Unmatched lines:** a line the transcript cannot match gets an estimated time: interpolated between
matched lines, and spread at the song's median seconds-per-line (at most 8 s, kept inside the track
length) before the first and after the last matched line, so timestamps are distinct and strictly
increasing at 0.01 s resolution (a matched line not later than the previous one is treated as unmatched).
They used to copy the neighbouring line's time, which stacked a failed head or tail on one timestamp.

**Quality gate:** a weak alignment used to stamp many lines with one timestamp. `lrc_fix.py` skips a file, leaving its tag unchanged,
when fewer than `--min-match` (default 0.6) of its lyric lines matched the transcript (lines
without any word are not counted), when fewer than `--min-sung` (default 0.5) of the lyric's consecutive word pairs occur anywhere in the transcript (`lrc_fix.sung_ratio`, order independent; it catches songs that only share common words with the transcript), or when the result would have a `one_timestamp` or
`shared_timestamps` pile-up per `lrc_format.lrc_suspect_reasons`. `--no-quality-gate` bypasses
all checks. If whisperx has no alignment model for the detected language, `--fallback-language` (default `en`) makes it transcribe the track again in that language instead of failing. See ADR 0002 section 6 and ADR 0009.

**Language:** the per-track `LYRICS_LANGUAGE` tag (written by `fixtags.py` from MusicBrainz, ADR 0002 section 5b) forces the transcription language when it names one language that whisper and whisperx can handle; `zxx` and languages without a whisper or alignment model skip the track before any ML work; `--language` wins and `--ignore-language-tag` disables it (ADR 0009).

**Tags read:** `LYRICS`, `LYRICS_LANGUAGE`, `ALBUMARTIST`, `ARTIST`, `TITLE`, `ALBUM`

**Tags written:** `LYRICS`

**Dependencies:** `mutagen`, `whisperx`, `demucs`, `librosa`, `torch>=2.4,<2.6`, `torchaudio>=2.4,<2.6`, `numpy<2`, `transformers<5`

**Shared with `update_lyrics.py`:** header build/refresh, instrumental marker format, and capitalization normalization live in `lrc_format.py` — see ADR 0002 §6.

---

### `lrc_audit.py` — Are the suspect lyrics bad because of lrclib or because of our tools? (and repair by tier)

**Purpose:** For every track whose synced LRC looks like a failed alignment (the `lrc_count.py --suspects` test, `lrc_format.lrc_suspect_reasons`, hint-only tracks included), compare three sources: the tag (text, timestamps, and the `[re:]` header that says `lrc_fix` wrote it), lrclib.net today (fetched fresh, paced as in ADR 0007 section 4), and the audio (the demucs + whisperx transcript in the `lrc_fix` ASR cache). Each track gets a verdict and a flag whether today's `lrc_fix` would fix it. Except for `fix --apply`, it is read-only: `lrc_fix.py` runs with `--dry-run`, so no tag is written.

**Usage** (resumable; re-running continues where it stopped):

```bash
./lrc_audit.py run [--apply-fixes]      # prepare + transcribe + analyze (+ fix), e.g. overnight
./lrc_audit.py prepare [--root DIR]     # find the suspect tracks -> ~/.cache/lrc_audit/targets.jsonl
./lrc_audit.py transcribe [--limit N] [--offset N] [--extra stale-language|zxx|onsets]
./lrc_audit.py analyze [--skip-lrclib] [--refetch]
./lrc_audit.py fix [--tiers T] [--apply]   # list (default) or write the repairs of the chosen tiers
./lrc_audit.py revert                   # restore the tags that fix --apply replaced
```

| Option | Default | Description |
|---|---|---|
| `--work-dir` | `~/.cache/lrc_audit` | targets, lrclib answers, `transcribe.log`, `failed.txt`, `fixes.jsonl` |
| `--root` | `config.flacroot` | library root scanned by `prepare` |
| `--whisper-model`, `--language`, `--device`, `--compute-type`, `--jobs` | as `lrc_fix.py` | passed to `lrc_fix.py`; they must match between `transcribe`, `analyze` and `fix` (they are part of the cache key) |
| `--cache-dir` | `~/.cache/lrc_fix` | the `lrc_fix` ASR cache |
| `--ignore-language-tag` | off | passed to `lrc_fix`; also disables the `language_skipped` verdict |
| `--timeout` | 3600 | seconds per track before `lrc_fix` is given up on |
| `--no-caffeinate` | off | do not keep a Mac awake while transcribing |
| `--skip-lrclib` / `--refetch` | off | skip the lrclib comparison / ignore cached lrclib answers |
| `--apply` | off | `fix`: really write the repaired tags (without it `fix` only lists them) |
| `--apply-fixes` | off | `run`: finish with `fix --apply` |
| `--tiers` | `safe,instrumental,shifted,onetimestamp` | `fix`: comma-separated tiers to offer (`safe`, `instrumental`, `shifted`, `shifted-all`, `onetimestamp`) |
| `--extra` | (none) | `transcribe`: instead of the uncached tracks, run one extra ML pass over tracks that already have an answer (repeatable): `stale-language` (non-English tracks judged on a transcript that predates `LYRICS_LANGUAGE`, re-transcribed with `--refresh-cache`), `zxx` (MusicBrainz instrumentals that `lrc_fix` skips, transcribed with `--ignore-language-tag` to see whether anything is sung), `onsets` (tracks today's `lrc_fix` would fix whose cache lacks the vocal onsets) |
| `--report` / `--out` | `docs/lrc-suspects-audit.md` / `lrc_suspects_audit` | summary report / CSV and XLSX base name |

**Behaviour:** `transcribe` runs `lrc_fix.py --dry-run` once per uncached target in its own process (memory is released per track, a failure is logged to `failed.txt` and does not stop the run). After each track it also fetches lrclib (cached, paced; the pacer is replaced after a cool-down if lrclib's circuit breaker tripped, so one hiccup does not fail the rest of the run) and prints a comparison of the three sources: the tag (lines, words, who wrote it, suspect reasons), lrclib (synced or plain, lines, words, same timestamps as the tag, its own check), whisper (words, words per minute), the in-order line match, the share of the lyric's word pairs that are sung, the timing agreement, and the verdict with today's `lrc_fix` result (`would fix` / `would reject`, a simulation on the cached transcript); a verdict tally closes the run (cached tracks are only tallied). `analyze` needs no ML: it recomputes everything from the cached transcript, compares with lrclib, and writes `lrc_suspects_audit.csv`/`.xlsx` (one row per track, git-ignored; the xlsx has a `review` sheet and there is a `_review.csv` for the tracks whose lyrics are not (fully) in the audio and the failed transcriptions) and the summary report with the verdict rules and thresholds.

**Verdicts, in short:** no audio evidence (whisper heard almost nothing); `text_mismatch` / `text_partial` (under 20% / 20-50% of the lyric's word pairs are sung; order independent); for a tag that only ends early with sung text, the tag's own timestamps are compared with where whisper hears the lines (median distance up to 3 s: `ends_early_confirmed`, or `ends_early_borderline` when the tag ends at 45% of the track or later; larger: `timestamps_shifted`); `instrumental_has_lyrics` (checked first: `LYRICS_LANGUAGE` is `zxx` and whisper hears under 10 words per minute, or the track has no real language tag and whisper hears under 3; a track MusicBrainz calls sung is never one); stacked timestamps that `lrc_fix` still cannot align (`text_ok_not_alignable`), that lrclib has too (`lrclib_bad_timestamps`), that `lrc_fix` wrote while lrclib has no synced lyrics (`stacked_by_lrc_fix`), or where lrclib's are fine (`tag_worse_than_lrclib_*`); `transcription_failed` (a crash or timeout, with the reason taken from `lrc_fix`'s own `skip:`/`warning:` line rather than library warnings; a run where whisper returned no words at all is `no_audio_evidence`), `language_skipped` (the `LYRICS_LANGUAGE` tag makes `lrc_fix` skip the track: an instrumental, or a language without a whisper or alignment model; `transcribe` leaves such tracks out instead of calling `lrc_fix`) and `tag_changed` (edited or repaired since `prepare`).

**Repair tiers and `fix`:** every track gets at most one tier (`fix_tier`/`fix_action` columns), in this order. `instrumental`: an `instrumental_has_lyrics` track gets the canonical instrumental marker (ADR 0002 section 6; its other header lines are kept). `safe`: stacked timestamps, at least 50% of the word pairs sung, today's `lrc_fix` would write a clean result, words and onsets cached. `shifted`: the text is right but the timestamps are more than 10 s off the audio, with at least 80% line match and 70% sung, and `lrc_fix` would write a clean result (`shifted-all` is every other shifted track it can fix, opt-in). `onetimestamp`: a one-timestamp tag is realigned if `lrc_fix` can, otherwise its fake timing is dropped and the text kept as plain lyrics (a tag with every line at `00:00.00` and no transcript is dropped too). Realignment needs no ML (the demucs/whisperx/onset functions are blocked during `fix`); `fix` lists the repairs and `fix --apply` writes them after saving the old tag to `fixes.jsonl`. A realigned tag is re-read and restored at once if it is unchanged or still stacked. Every tag must still be what `prepare` audited. `revert` restores every tag from `fixes.jsonl` unless it was edited since. Nothing else is ever written to the library. `analyze` also reports, per suspect track, whether MusicBrainz data is missing (`musicbrainz_state`: `tagged`, `no_id`, `id_no_language`) and lists the albums in the report; nothing is written for it.

**Tags read:** `LYRICS`, `LYRICS_LANGUAGE`, `MUSICBRAINZ_ALBUMID`, `ALBUMARTIST`, `ARTIST`, `ALBUM`, `TITLE`, `DISCOGS_RELEASE_ID`, `DISCNUMBER`, `TRACKNUMBER`. **Tags written:** `LYRICS`, only by `fix --apply` / `revert`.

**External service:** lrclib.net `GET /api/get` (same lookup order, client headers and pacing as `update_lyrics.py`).

**Dependencies:** those of `lrc_fix.py`, plus `requests`, `rich`, `structlog`, `openpyxl`.

---

### `lrclib_submitter.py` — LRCLIB Lyrics Publisher

**Purpose:** Submits the `LYRICS` tag from a single `.flac` file to the LRCLIB API (`lrclib.net`), solving LRCLIB's Proof-of-Work (PoW) challenge automatically.

```
uv run lrclib_submitter.py TARGET_FLAC [OPTIONS]
```

| Argument / Option | Default | Description |
| --- | --- | --- |
| `TARGET` | (required) | Path to a single `.flac` file to publish. |
| `--dry-run` | off | Preview metadata payload and format without solving PoW or publishing. |

**Behaviour:**
1. Reads `TITLE`, `ARTIST`/`ALBUMARTIST`, `ALBUM`, audio duration (`FLAC.info.length`), and `LYRICS` tag from the FLAC file.
2. Checks whether lyrics are synced (contain `[MM:SS.xx]` timestamps) or plain text.
3. Requests a Proof-of-Work challenge from `POST https://lrclib.net/api/request-challenge`.
4. Solves the SHA-256 hash puzzle (`SHA256(prefix + nonce) < target`) to compute `X-Publish-Token: prefix:nonce`.
5. Sends `POST https://lrclib.net/api/publish` with JSON payload (`trackName`, `artistName`, `albumName`, `duration`, `syncedLyrics`/`plainLyrics`).
6. Logs structured success event (`logger.info("lyrics_published", ...)`) and displays Rich status notification.

**Dependencies:** `mutagen`, `requests`, `rich`, `click`, `structlog`

---

### `find_audiophile_upgrades.py` — Audiophile Album Upgrade Recommendations

**Purpose:** Scans `albums.csv`, identifies albums with format `CD` or `Qobuz`, queries the Discogs API (with rate limiting and persistent local caching) to discover higher-quality audiophile versions (SACD, SHM-CD, UDCD, UHQCD, MFSL, Gold CD, etc.) that are not already in the library, and outputs recommendations with links to CSV.

```bash
uv run find_audiophile_upgrades.py [OPTIONS]
```

| Argument / Option | Default | Description |
| --- | --- | --- |
| `--input`, `-i` | `config_dir/albums.csv` | Input CSV containing library inventory. |
| `--output`, `-o` | `config_dir/audiophile_upgrades.csv` | Target CSV path for upgrade recommendations. |
| `--cache`, `-c` | `config_dir/audiophile_cache.json` | Persistent JSON cache for Discogs API responses. |
| `--limit`, `-l` | `None` | Limit search to first N target CD/Qobuz albums. |
| `--offline` | `off` | Rely strictly on cached API responses without making network requests. |

**Behaviour:**
1. Loads library inventory from `albums.csv` and indexes existing album formats and Discogs Release IDs.
2. Filters albums with format `CD` or `Qobuz`.
3. Checks local cache (`audiophile_cache.json`) for cached Discogs release/master data.
4. If uncached, queries Discogs API with 1.1s rate limiting and exponential backoff retry on HTTP 429 errors.
5. Resolves candidate pressings via Discogs Master Release versions (`/masters/{master_id}/versions`).
6. Filters candidates matching audiophile format patterns (SACD, SHM-CD, MFSL, UHQCD, Gold CD, XRCD, K2 HD, Blu-spec CD, HDCD, HQCD, DVD-Audio, Blu-ray Audio) while excluding versions already in the user's library.
7. Outputs recommendations with Discogs URLs to `audiophile_upgrades.csv`.

**Dependencies:** `requests`, `rich`, `structlog`

---

## Typical workflow

```bash
# 1. Ingest a new album from downloads
uv run bliss.py --ingest /Volumes/FLAC/Downloads/NewAlbum/

# 2. Run the full enrichment pipeline on the ingested directory
uv run nzbfix.py /Volumes/flac/Artist/Album/

# 3. Align timestamps or auto-generate LRC lyrics with Whisper
uv run align_lyrics.py /Volumes/flac/Artist/Album/ --write

# 4. Submit verified lyrics to LRCLIB
uv run lrclib_submitter.py /Volumes/flac/Artist/Album/01_Track.flac

# 5. Rebuild the album inventory CSV
uv run album_list.py /Volumes/flac/

# 6. (Periodic) Sync the MP3 mirror
uv run bliss.py --mp3
```
