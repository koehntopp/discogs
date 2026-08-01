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
  * **Calculated Metrics (Managed by `calculate_dr.py` & `calculate_fp.py`)**: `DYNAMIC_RANGE` (replaces deprecated space key `DYNAMIC RANGE`), `ALBUM_DR` (replaces deprecated space key `ALBUM DYNAMIC RANGE`), `ACOUSTID_FINGERPRINT` (replaces deprecated space key `ACOUSTID FINGERPRINT`).
  * **Lyrics (Managed by `update_lyrics.py`)**: `LYRICS`.

> [!WARNING]
> Tag keys containing spaces (such as `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`, `ACOUSTID FINGERPRINT`) violate the Vorbis Comment specification and must be read with fallback checks, and rewritten using standard compliant keys containing underscores (e.g. `DYNAMIC_RANGE`, `ALBUM_DR`, `ACOUSTID_FINGERPRINT`).

### 2. User Tag Authority & Catalog Number Fallbacks
* `DISCOGS_RELEASE_ID` is the authoritative anchor for release matching. If missing from an album directory, scripts must skip metadata enrichment for that directory.
* **Yate Catalog Numbers**: Catalog numbers are tagged in FLAC files by Yate using the `CATALOG NUMBER` space key. Scripts (`webui.py`, `album_list.py`) read catalog numbers using robust fallback checks across `CATALOGNUMBER`, `CATALOG NUMBER`, `CATALOG_NUMBER`, and `CATALOGNO`.
* **Non-Destructive Invariant**: Automated scripts (`fixtags.py`) do **not** fetch or overwrite user catalog numbers from external APIs, respecting User Tag Authority.

### 3. MusicBrainz Release Id Tag Contract
* Standard tag key `MUSICBRAINZ_ALBUMID` is displayed across reports (`albums.csv`) and the Web UI as **`MusicBrainz Release Id`**.
* Fallback reads check `MUSICBRAINZ_ALBUMID`, `MUSICBRAINZ ALBUM ID`, `MUSICBRAINZ_RELEASEGROUPID`, and `MUSICBRAINZ RELEASE GROUP ID`.

### 4. Album Tag Formatting (`ALBUM` and `VERSION`)
* `fixtags.py` and `migrate_tags.py` populate clean `ALBUM` and plain `VERSION` tags:
  * **`ALBUM` Tag:** Stores the clean master title only (no brackets or decoration), e.g., `Fatal Mistakes`.
    * **Title source priority:** `ALBUM_TITLE_OVERRIDE` $\rightarrow$ `ALBUM_MASTER_TITLE` $\rightarrow$ `ORIGINAL_TITLE` $\rightarrow$ clean `ALBUM`.
  * **`VERSION` Tag:** Stores the plain-text release decoration string (without square brackets), e.g., `2021 CD (Deluxe Digital Album)` or `1988 CD`.
    * Format: `<year> <format>` (or `<year> <format> (<edition>)` when an edition is specified).
    * **Year source:** `ALBUM_RELEASE_YEAR`.
    * **Format source:** `ALBUM_FORMAT` (falls back to `SUBTITLE`, defaults to "CD").
    * **Edition source:** `ALBUM_EDITION`.
  * Example `ALBUM`: `Brothers in Arms`
  * Example `VERSION`: `2025 Blu-ray (40th Anniversary Edition)`
* `bliss.py` combines `clean(f"{ALBUM} {VERSION}".strip())` to compute directory names on disk, preserving 100% backward compatibility with existing folder names (e.g. `Brothers_in_Arms_2025_Blu_ray_40th_Anniversary_Edition`).

### 5. Lyrics Tag Management (`LYRICS`)
* **Format Distinction**:
  * **Synced LRC**: Contains timestamp patterns (`[MM:SS.xx]`). Preferred over plain text.
  * **Plain Text TXT**: Embedded if synced LRC is unavailable and no prior lyrics exist.
* **LRC Header Preservation & Normalization**:
  * Synced LRC lyrics embed standard headers: `[ar:...]`, `[ti:...]`, `[al:...]`, `[length:...]`.
  * Header line matching must use line-greedy regexes (`^\[(ar|ti|al|by|length|offset):.*\]\s*$`) to safely strip and rebuild headers when metadata updates.

### 6. Calculated Metric Tags
* **Track & Album Dynamic Range (`DYNAMIC_RANGE`, `ALBUM_DR`)**:
  * Computed via EBU R 128 / `drmeter`. Track DR is written to `DYNAMIC_RANGE`.
  * Album DR is the rounded arithmetic mean of all track DR scores in the album, written to `ALBUM_DR`.
* **AcoustID Fingerprints (`ACOUSTID_FINGERPRINT`)**:
  * Computed via `fpcalc` (Chromaprint). Written once to `ACOUSTID_FINGERPRINT` and skipped if already present.

---

## Consequences

### Positive
* **Deterministic Tag Keying**: Eliminates key casing inconsistencies across different tools and platforms.
* **User Tag Preservation**: Preserves Yate catalog numbers and user overrides without destructive API overwrites.
* **Roon Compatible VERSION Tag**: Clean master title in `ALBUM` paired with plain-text release decoration in `VERSION` allows Roon and other music servers to group albums accurately while `bliss.py` preserves 1-to-1 disk folder layout compatibility.

### Negative / Trade-offs
* All new scripts manipulating FLAC files must adhere strictly to these tag key contracts and use safe `mutagen` extraction patterns.
