# ADR 0002: FLAC Tag Handling Contracts and Metadata Standards

- **Status**: Accepted
- **Date**: 2026-08-01 (Updated)
- **Authors**: Discogs Project Maintainers

## Context

In this project, FLAC files serve as the canonical source of truth for the entire music library and web UI. Tags are stored as Vorbis comment fields within FLAC files using `mutagen`.

A core design principle of this repository is **user tag authority**: users set core release metadata using dedicated tagging applications (e.g., Yate on macOS) anchored by the `DISCOGS_RELEASE_ID` tag. Automated scripts enrich and normalize tags (such as formatting album titles, computing Dynamic Range scores, generating AcoustID fingerprints, and embedding LRC lyrics) but must **never** arbitrarily overwrite or destroy user-defined tags.

To prevent metadata loss, tag key casing discrepancies, corrupted tag formatting, and duplicate header accumulation, a strict contract for reading, writing, formatting, and preserving FLAC tags is required.

---

## Decision

We establish the following binding rules and standards for all FLAC tag handling across scripts in this codebase:

### 1. Tag Key Names & Case Standard
* **Vorbis Comment Format**: All FLAC tag keys must be read and written using **UPPERCASE** string keys.
* **Standard Tag Inventory**:
  * **User Anchor Tag (Read-Only by scripts)**: `DISCOGS_RELEASE_ID` (anchors album to exact Discogs version).
  * **Ripping/Tagger Metadata (Read-Only by scripts)**: `ALBUMARTIST`, `ARTIST`, `TITLE`, `TRACKNUMBER`, `DISCNUMBER`, `CATALOGNUMBER`, `MUSICBRAINZ_ALBUMID`, `SUBTITLE`, `ORIGINAL FILENAME` (custom release title override).
  * **Enriched Metadata (Managed by `fixtags.py`)**: `ALBUM`, `VERSION`, `DATE`, `RELEASEDATE`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`.
  * **Structured Custom Metadata (Managed by `fixtags.py`)**: `ALBUM_MASTER_TITLE`, `ALBUM_MASTER_YEAR`, `ALBUM_RELEASE_TITLE`, `ALBUM_RELEASE_YEAR`, `ALBUM_MAX_RESOLUTION`, `ALBUM_EDITION`, `ALBUM_FORMAT`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`.
  * **User Overrides (Optional, read by scripts)**: `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`, `ORIGINAL FILENAME`.
  * **Calculated Metric Tags**:
    * **Track & Album Dynamic Range (`DYNAMIC_RANGE`, `ALBUM_DR`)**: Computed via EBU R 128 / `drmeter`. Track DR is written to `DYNAMIC_RANGE`. Album DR is the rounded arithmetic mean of all track DR scores in the album, written to `ALBUM_DR`.
    * **AcoustID Fingerprints (`ACOUSTID_FINGERPRINT`)**: Computed via `fpcalc` (Chromaprint / `pyacoustid`). Decoded to a UTF-8 `str` string before assigning to Mutagen FLAC tags to prevent `TypeError`. Written once to `ACOUSTID_FINGERPRINT` and skipped if already present.
  * **Lyrics (Managed by `update_lyrics.py`)**: `LYRICS`.

> [!WARNING]
> Tag keys containing spaces (such as `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`, `ACOUSTID FINGERPRINT`) violate the Vorbis Comment specification and must be read with fallback checks, and rewritten using standard compliant keys containing underscores (e.g. `DYNAMIC_RANGE`, `ALBUM_DR`, `ACOUSTID_FINGERPRINT`).

### 2. User Tag Authority & Catalog Number Fallbacks
* `DISCOGS_RELEASE_ID` is the authoritative anchor for release matching. If missing from an album directory, scripts must skip metadata enrichment for that directory.
* **Yate Catalog Numbers**: Catalog numbers are tagged in FLAC files by Yate using the `CATALOG NUMBER` space key. Scripts (`webui.py`, `album_list.py`) read catalog numbers using robust fallback checks across `CATALOGNUMBER`, `CATALOG NUMBER`, `CATALOG_NUMBER`, and `CATALOGNO`.
* **Non-Destructive Invariant**: Automated scripts (`fixtags.py`) do **not** fetch or overwrite user catalog numbers from external APIs, respecting User Tag Authority.

### 3. Discogs API Enrichment & Rate-Limiting Mechanics (`fixtags.py`)
* **Rate-Limit Resilience (`discogs_fetch`)**: `fixtags.py` wraps API calls with retries (up to 3 attempts, 60-second backoff) on HTTP 429 rate limits or `JSONDecodeError` empty response bodies. Sleeps 1 second after API requests to respect Discogs rate limits.
* **Master & Release Title Resolution**: Title resolution follows priority `ALBUM_TITLE_OVERRIDE` $\rightarrow$ `master.title` $\rightarrow$ `drelease.title`. `ALBUM` stores the clean master title without brackets. `ALBUM_MASTER_TITLE`, `ALBUM_RELEASE_TITLE`, and `ORIGINAL_TITLE` store exact Discogs release strings.
* **Master & Release Year Resolution**: `ALBUM_RELEASE_YEAR` stores pressing year; `ALBUM_MASTER_YEAR` stores original master release year. Written to `RELEASEDATE`, `DATE`, `YEAR`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR`.
* **Audio Resolution & Version Standard**: `ALBUM_MAX_RESOLUTION` scans max FLAC sample rate across all tracks in directory (e.g. `96kHz`, `44.1kHz`). `VERSION` stores plain-text release string `<release_year> <format> (<edition>)`.
* **Embedded Cover Art Resizing (`resize_covers`)**: Embedded `Picture` frames exceeding `cover_max_size` (default 1500px, from `config.py`) are resized down via PIL/Pillow Lanczos resampling (`Image.LANCZOS`), re-encoded as 90% JPEG quality, and re-embedded into FLAC files.
* **Stale Tag Cleanup**: Automatically removes stale managed optional tags (`ALBUM_EDITION`, `ALBUM_DR`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`) if no longer applicable to the release.

### 4. MusicBrainz Release Id Tag Contract
* Standard tag key `MUSICBRAINZ_ALBUMID` is displayed across reports (`albums.csv`) and the Web UI as **`MusicBrainz Release Id`**.
* Fallback reads check `MUSICBRAINZ_ALBUMID`, `MUSICBRAINZ ALBUM ID`, `MUSICBRAINZ_RELEASEGROUPID`, and `MUSICBRAINZ RELEASE GROUP ID`.

### 5. Album Tag Formatting (`ALBUM` and `VERSION`)
* `fixtags.py` and `migrate_tags.py` populate clean `ALBUM` and plain `VERSION` tags:
  * **`ALBUM` Tag:** Stores the clean master title only (no brackets or decoration), e.g., `Fatal Mistakes`.
  * **`VERSION` Tag:** Stores the plain-text release decoration string (without square brackets), e.g., `2021 CD (Deluxe Digital Album)` or `1988 CD`.
  * Example `ALBUM`: `Brothers in Arms`
  * Example `VERSION`: `2025 Blu-ray (40th Anniversary Edition)`
* `bliss.py` combines `clean(f"{ALBUM} {VERSION}".strip())` to compute directory names on disk, preserving 100% backward compatibility with existing folder names.

### 6. Lyrics Tag Management (`LYRICS`)
* **Format Distinction**: Synced LRC (`[MM:SS.xx]`) vs Plain Text TXT.
* **Header Preservation**: Rebuilds headers (`[ar:...]`, `[ti:...]`, `[al:...]`, `[length:...]`) via line-greedy regexes.
* **Capitalization Normalization**: The first non-whitespace character of every lyric line (new or already embedded) is uppercased, both for synced LRC (text following the `[MM:SS.xx]` timestamp) and plain TXT. LRC header lines are left untouched. Existing embedded lyrics that need only this fix are rewritten in place rather than skipped.
* **LRC Timestamp Whitespace Stripping**: Any whitespace between an `[MM:SS.xx]` timestamp and its lyric text is stripped (`[MM:SS.xx]Text`, not `[MM:SS.xx] Text`), applied via the same normalization pass.

### 7. Calculated Metric Tags
* Track DR (`DYNAMIC_RANGE`), Album DR (`ALBUM_DR`), AcoustID Fingerprints (`ACOUSTID_FINGERPRINT`).

---

## Consequences

### Positive
* **Deterministic & Resilient Enrichment**: Robust retry logic prevents 429 rate limit crashes during bulk metadata updates.
* **Embedded Image Optimization**: Keeps embedded cover art size within 1500px limits to optimize player loading speed.
* **User Tag Preservation**: Preserves Yate catalog numbers and user overrides without destructive API overwrites.

### Negative / Trade-offs
* `fixtags.py` requires an active Discogs API key configured in `config.py`.
