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
  * **Ripping/Tagger Metadata (Read-Only by scripts)**: `ARTIST`, `TITLE`, `TRACKNUMBER`, `DISCNUMBER`, `CATALOGNUMBER`, `MUSICBRAINZ_ALBUMID`, `SUBTITLE`, `SET SUBTITLE` (user-set, per-track, on discs within multi-disc editions — see §5a). `ALBUMARTIST` is normally in this category too, but `fixtags.py` overwrites it when `ALBUM_ARTIST_OVERRIDE` is set (see §5).
  * **Enriched Metadata (Managed by `fixtags.py`)**: `ALBUM`, `VERSION`, `DATE`, `RELEASEDATE`, `ORIGINALDATE`, `ORIGINALRELEASEDATE`.
  * **Structured Custom Metadata (Managed by `fixtags.py`)**: `ALBUM_MASTER_TITLE`, `ALBUM_MASTER_YEAR`, `ALBUM_RELEASE_TITLE`, `ALBUM_RELEASE_YEAR`, `ALBUM_MAX_RESOLUTION`, `ALBUM_EDITION`, `ALBUM_FORMAT`, `ALBUM_RELEASE_COUNTRY`, `ALBUM_RELEASE_LABEL`.
  * **Per-Track Structured Metadata (Managed by `fixtags.py`)**: `PART`, `WORK` — unlike everything else in this table, set independently per track rather than uniformly across the album directory. See §5a.
  * **User Overrides (Optional, read by scripts)**: `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`.
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
  * **`VERSION` Tag:** Stores the plain-text release decoration string: `<year> DR<xx> <format> (<edition>) (<catalog number>)`, e.g., `2021 DR11 CD (Deluxe Digital Album) (XLCD313X)` or `1988 DR09 CD`. `DR<xx>` (two-digit, zero-padded) and the parenthesized catalog number are each appended only when available — `ALBUM_DR` (or the deprecated `ALBUM DYNAMIC RANGE` fallback) for DR, and `CATALOGNUMBER`/`CATALOG NUMBER`/`CATALOG_NUMBER`/`CATALOGNO` (first present) for the catalog number.
  * Example `ALBUM`: `Brothers in Arms`
  * Example `VERSION`: `2025 DR09 Blu-ray (40th Anniversary Edition) (DGCD 12345)`
* `bliss.py` combines `clean(f"{ALBUM} {VERSION}".strip())` to compute directory names on disk, preserving 100% backward compatibility with existing folder names.
* **`ALBUM_ARTIST_OVERRIDE`**: A manual correction for a wrong `ALBUMARTIST`, not a Discogs-derived value — `fixtags.py` doesn't fetch or track any artist data from Discogs. When set, it's written straight into `ALBUMARTIST` (uniformly across the album directory, like `ALBUM`/`VERSION`), permanently replacing whatever was there; left completely untouched when absent. No other script consults `ALBUM_ARTIST_OVERRIDE` directly — `bliss.py`, `album_list.py`, and `webui.py` all read `ALBUMARTIST` itself, which `fixtags.py` keeps corrected.

### 5a. Per-Track Box-Set Grouping (`PART` and `WORK`)
* `fixtags.py` writes `PART` and `WORK` **per track**, inside the same per-file
  loop that saves each FLAC — not as part of the uniform album-level tag set
  applied identically to every file in the directory. This matters because a
  single `fixdir` invocation can span an entire multi-disc box set treated as
  one Discogs release, where each disc's own identity still needs to be
  distinguishable.
  * **`PART`**: always set to that track's own `TITLE`.
  * **`WORK`**: set to that track's own `SET SUBTITLE` — a tag the user sets
    manually, per disc, within multi-disc editions — but only when
    `SET SUBTITLE` is present on that specific track; removed if it's later
    cleared on that track.
* Roon renders `WORK` as a shared header it groups tracks under, and `PART`
  as the individual track label shown beneath it — letting discs of a
  box set (e.g. "Disc 1: Studio Album", "Disc 2: Live") appear as distinct,
  identifiable groups in Roon even though this codebase treats the whole box
  set as one flat album directory. See ADR 0008 for the full set of
  Roon-specific tagging decisions.

### 6. Lyrics Tag Management (`LYRICS`)
* **Shared Formatting (`lrc_format.py`)**: The `[ar:]/[ti:]/[al:]/[length:]`
  header build/refresh logic, the instrumental marker format, and
  capitalization normalization live once, in `lrc_format.py`, imported as a
  sibling module by both `update_lyrics.py` and `lrc_fix.py` (and, for just
  the classification constants, `lrc_count.py`). Two independent copies of
  this logic previously drifted silently (see Artist Source below) — sharing
  the code makes that structurally impossible instead of a bug to catch by
  hand. `lrc_format.py` is pure string-in/string-out with no mutagen/FLAC
  dependency; each caller still owns its own tag reads.
* **Artist Source**: the "artist" used everywhere — the lrclib.net search
  query, the `[ar:]` LRC header, and log messages — is sourced from
  `ALBUMARTIST`, falling back to `ARTIST` only when `ALBUMARTIST` is empty
  (`lrc_format.resolve_artist`). This deliberately differs from §1's general
  read-only `ARTIST` metadata: a track's own `ARTIST` credit can carry
  rip-specific billing (e.g. `Roy Orbison With Guests` on a live album where
  `ALBUMARTIST` is the plain `Roy Orbison`) that lrclib.net's artist index
  doesn't recognize, causing otherwise-findable lyrics to 404.
* **Format Distinction**: Synced LRC (`[MM:SS.xx]`) vs Plain Text TXT.
* **Header Preservation**: `update_lyrics.py` owns only the `ar`/`ti`/`al`/`length` header lines and updates their values **in place**, wherever they already sit in the tag; any id-tag line it doesn't own (e.g. a `[re:...]` line written by an external re-alignment tool, or `[by:...]`/`[offset:...]`) is left completely untouched, in its original position, rather than stripped and rebuilt at a fixed offset. Managed headers that are entirely missing are inserted at the top. This in-place merge (as opposed to a prior strip-and-rebuild design) is required so `update_lyrics.py` converges to a stable tag instead of perpetually re-ordering headers against any other tool that also writes id-tag lines to `LYRICS`.
* **Capitalization Normalization**: The first non-whitespace character of every lyric line (new or already embedded) is uppercased, both for synced LRC (text following the `[MM:SS.xx]` timestamp) and plain TXT. LRC header lines are left untouched. Existing embedded lyrics that need only this fix are rewritten in place rather than skipped.
* **LRC Timestamp Whitespace Stripping**: Any whitespace between an `[MM:SS.xx]` timestamp and its lyric text is stripped (`[MM:SS.xx]Text`, not `[MM:SS.xx] Text`), applied via the same normalization pass.
* **Instrumental Track Marking**: When lrclib.net's API response for a track sets `instrumental: true` (no synced/plain lyrics available), `update_lyrics.py` writes a fixed-format marker to `LYRICS` instead of leaving it empty:
  ```
  [ar:...]
  [ti:...]
  [al:...]
  [length:...]
  [la:zxx]
  [instrumental:true]
  [00:00.00](Instrumental)
  ```
  `[la:zxx]` is the standard ISO 639-2 "no linguistic content" LRC language code; `[instrumental:true]` is the sentinel `update_lyrics.py` checks on subsequent runs to skip re-fetching. Tracks already carrying this marker are left untouched without an lrclib.net API call.
* **Manual Instrumental Marking**: A user may hand-type an informal marker into the `LYRICS` tag matching `[MM:SS.xx][Instrumental]` or `[MM:SS.xx](Instrumental)` (case-insensitive, e.g. `[00:00.00][Instrumental]`) to mark a track instrumental without waiting on lrclib.net — the parenthesis form also catches an incomplete canonical block missing its `[la:zxx]`/`[instrumental:true]` sentinel lines. `update_lyrics.py` detects this pattern and rewrites it into the canonical marker block above — without making any network request — counted as a `'fix'` (syntax normalization) rather than a `'new'` write, since no new lyrics information is being added.

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
