# ADR 0002: FLAC Tag Handling Contracts and Metadata Standards

- **Status**: Accepted
- **Date**: 2026-07-27
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
  * **Enriched Metadata (Managed by `fixtags.py`)**: `ALBUM`, `DATE`, `RELEASEDATE`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`.
  * **Structured Custom Metadata (Managed by `fixtags.py`)**: `ALBUM_MASTER_TITLE`, `ALBUM_MASTER_YEAR`, `ALBUM_RELEASE_TITLE`, `ALBUM_RELEASE_YEAR`, `ALBUM_MAX_RESOLUTION`, `ALBUM_EDITION`, `ALBUM_FORMAT`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`.
  * **User Overrides (Optional, read by scripts)**: `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`, `ORIGINAL FILENAME`.
  * **Calculated Metrics (Managed by `calculate_dr.py` & `calculate_fp.py`)**: `DYNAMIC_RANGE` (replaces deprecated space key `DYNAMIC RANGE`), `ALBUM_DR` (replaces deprecated space key `ALBUM DYNAMIC RANGE`), `ACOUSTID_FINGERPRINT` (replaces deprecated space key `ACOUSTID FINGERPRINT`).
  * **Lyrics (Managed by `update_lyrics.py`)**: `LYRICS`.

> [!WARNING]
> Tag keys containing spaces (such as `DYNAMIC RANGE`, `ALBUM DYNAMIC RANGE`, `ACOUSTID FINGERPRINT`) violate the Vorbis Comment specification and must be read with fallback checks, and rewritten using standard compliant keys containing underscores (e.g. `DYNAMIC_RANGE`, `ALBUM_DR`, `ACOUSTID_FINGERPRINT`).

### 2. User Tag Authority & Non-Destructive Invariant
* `DISCOGS_RELEASE_ID` is the authoritative anchor for release matching. If missing from an album directory, scripts must skip metadata enrichment for that directory.
* User-authored metadata (such as primary artist names, `ORIGINAL FILENAME`, or custom release IDs) must never be erased or overwritten with generic fallbacks.

### 3. Album Tag Formatting (`ALBUM`)
* `fixtags.py` normalizes the `ALBUM` tag string using a structured format:
  * If `ALBUM_EDITION` is absent: `"<title> [<year> <format>]"`
  * If `ALBUM_EDITION` is present: `"<title> [<year> <format> (<edition>)]"` (extra space and parentheses added only when an edition is specified).
  * **Title source priority:** `ALBUM_TITLE_OVERRIDE` $\rightarrow$ `ORIGINAL FILENAME` $\rightarrow$ `ORIGINAL_FILENAME` $\rightarrow$ `ALBUM_MASTER_TITLE` $\rightarrow$ `ORIGINAL_TITLE`.
  * **Year source:** `ALBUM_RELEASE_YEAR`.
  * **Format source:** `ALBUM_FORMAT` (falls back to `SUBTITLE`, defaults to "CD").
  * **Edition source:** `ALBUM_EDITION` (extracted from `()` brackets in existing `ALBUM` titles if tag is missing).
  * Example (no edition): `Brothers in Arms [2025 Blu-ray]`
  * Example (with edition): `Brothers in Arms [2025 Blu-ray (40th Anniversary Edition)]`
* `ALBUM` tag updates must only be written to FLAC files if the computed string actually differs from the existing tag value, avoiding unnecessary disk writes.

### 4. Lyrics Tag Management (`LYRICS`)
* **Format Distinction**:
  * **Synced LRC**: Contains timestamp patterns (`[MM:SS.xx]`). Preferred over plain text.
  * **Plain Text TXT**: Embedded if synced LRC is unavailable and no prior lyrics exist.
* **LRC Header Preservation & Normalization**:
  * Synced LRC lyrics embed standard headers: `[ar:...]`, `[ti:...]`, `[al:...]`, `[length:...]`.
  * Header line matching must use line-greedy regexes (`^\[(ar|ti|al|by|length|offset):.*\]\s*$`) to safely strip and rebuild headers when metadata updates, preventing duplicate headers on titles containing brackets (e.g. `[2024 Remaster]`).
* **Validation & Clearing**:
  * Malformed LRC timestamps (e.g., 3-part timestamps like `[100:40:39.00]`) must be automatically detected, stripped, or cleared to maintain player compatibility.

### 5. Calculated Metric Tags
* **Track & Album Dynamic Range (`DYNAMIC_RANGE`, `ALBUM_DR`)**:
  * Computed via EBU R 128 / `drmeter`. Track DR is written to `DYNAMIC_RANGE`.
  * Album DR is the rounded arithmetic mean of all track DR scores in the album, written to `ALBUM_DR`.
* **AcoustID Fingerprints (`ACOUSTID_FINGERPRINT`)**:
  * Computed via `fpcalc` (Chromaprint). Written once to `ACOUSTID_FINGERPRINT` and skipped if already present.

### 6. Helper Function Pattern (`flactag`)
* Reading tags from `taglib.File` must use safe fallback getters to avoid `KeyError` or `IndexError`:
  ```python
  def flactag(song: taglib.File, tag: str) -> str:
  	try:
  		return song.tags.get(tag, [''])[0]
  	except (KeyError, IndexError):
  		return ''
  ```
* File modification timestamps (`os.utime(flac_path, None)`) should be preserved or updated intentionally to prevent unnecessary re-syncing by file watchers or `rclone`.

---

## Consequences

### Positive
* **Deterministic Tag Keying**: Eliminates key casing inconsistencies (`album` vs `ALBUM`) across different tools and platforms.
* **Resilient Header Parsing**: Eliminates duplicate `[ti:...]` header proliferation in LRC lyrics fields.
* **Non-Destructive Workflows**: User-curated library tags and release IDs remain safe from accidental automated overwrites.
* **Efficient File Syncing**: Minimizes unnecessary `mtime` updates when tag values have not effectively changed.

### Negative / Trade-offs
* All new scripts manipulating FLAC files must adhere strictly to these tag key contracts and use safe `flactag` extraction patterns.
