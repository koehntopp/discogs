# ADR 0002: FLAC Tag Handling Contracts and Metadata Standards

- **Status**: Accepted
- **Date**: 2026-08-01 (Updated)
- **Authors**: Discogs Project Maintainers

## Context

In this project, FLAC files serve as the canonical source of truth for the entire music library and web UI. Tags are stored as Vorbis comment fields within FLAC files using `mutagen`.

A core design principle of this repository is **user tag authority**: users set core release metadata using dedicated tagging applications (e.g., Yate on macOS) anchored by the `DISCOGS_RELEASE_ID` tag. Automated scripts enrich and normalize tags (such as formatting album titles, computing Dynamic Range scores, generating AcoustID fingerprints, and embedding LRC lyrics) but must **never** arbitrarily overwrite or destroy user-defined tags.

To prevent metadata loss, tag key casing discrepancies, corrupted tag formatting, and duplicate header accumulation, a strict contract for reading, writing, formatting, and preserving FLAC tags is required.

See [docs/tag-schema.md](../tag-schema.md) for a visual ERD of the tag relationships this ADR defines — a derived reference, not a replacement for the text below.

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
  * **Per-Track Structured Metadata (Managed by `fixtags.py`)**: `DISCSUBTITLE` — unlike everything else in this table, set independently per track rather than uniformly across the album directory. See §5a. (`PART`/`WORK` are no longer written; existing values are left alone.)
  * **Per-Track Language (Managed by `fixtags.py`, derived from MusicBrainz)**: `LYRICS_LANGUAGE`. See §5b.
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
* **Master & Release Year Resolution**: `ALBUM_RELEASE_YEAR` stores the pressing year and is taken **only** from the Discogs release's own year (`drelease.year`) on every run; no tag (`ALBUM_RELEASE_YEAR`, `DATE`, ...) and not the master year is ever read for it, so it always follows `DISCOGS_RELEASE_ID`. If the Discogs release has no year, `ALBUM_RELEASE_YEAR` is not written and any existing value is removed. `RELEASEDATE`, `DATE`, `YEAR` carry the same release year (falling back to the Discogs master year only when the release has none, so players still get a date). `ALBUM_MASTER_YEAR` stores the original master release year and is written to `ORIGINALDATE`, `ORIGINALRELEASEDATE`, `ORIGINAL DATE`, `ORIGINAL YEAR`. Every tag `fixtags.py` writes is Discogs-derived and overwritten when it disagrees; tool-written tags are never fed back in as input.
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

### 5a. Per-Track Box-Set Disc Title (`DISCSUBTITLE`)
* `fixtags.py` writes `DISCSUBTITLE` **per track**, inside the same per-file
  loop that saves each FLAC — not as part of the uniform album-level tag set
  applied identically to every file in the directory. This matters because a
  single `fixdir` invocation spans an entire multi-disc box set treated as
  one Discogs release, where each disc's own identity still needs to be
  distinguishable.
  * **`DISCSUBTITLE`**: set to that track's own `SET SUBTITLE` — a tag the user
    sets manually, per disc, within multi-disc editions — but only when
    `SET SUBTITLE` is present on that specific track; removed if it's later
    cleared on that track.
* Roon documents `DISCSUBTITLE` as the reliable disc-title tag (it also reads
  `SETSUBTITLE`, `SET SUBTITLE`, `TSST`, `DISCNAME`, in that order of priority
  after it). See ADR 0008 for the Roon-specific decisions, including the folder
  layout (`bliss.py`, ADR 0005) and the import setting this depends on.
* `PART` and `WORK` were written by earlier versions. They are no longer written
  or removed; the user sets them by hand while the effect in Roon is evaluated.
* A `Disc N` subfolder (ADR 0005) belongs to its parent album: `fixtags.py`
  processes the parent as one `fixdir`, so one Discogs lookup covers all discs.

### 5b. Lyrics Language (`LYRICS_LANGUAGE`)
* `fixtags.py` writes `LYRICS_LANGUAGE` **per track**: the language(s) sung on the track, as ISO 639-3 codes in MusicBrainz's terms (`eng`, `deu`, `ksh`, `gle`; `mul`, `und` and `zxx` = several / undetermined / no linguistic content, i.e. an instrumental), one value per language. Discogs has no language data (neither releases nor tracks), so this is the one tag derived from **MusicBrainz** rather than Discogs. It is anchored by the user-set `MUSICBRAINZ_ALBUMID` (User Tag Authority); the tag is tool-owned and never read back as input by `fixtags.py`.
* **Source**: the language of the work a recording performs (`work.languages`), obtained with one release lookup (`inc=recordings+recording-level-rels+work-rels`; without `recording-level-rels` the languages silently do not appear). There is deliberately **no fallback to the release-level language**: it is a single guess for the whole album and is wrong for mixed albums (an album tagged `eng` with Irish tracks). A track whose work has no language gets no tag.
* **Matching**: a file is matched to its MusicBrainz track by `MUSICBRAINZ_RELEASETRACKID`, else by disc/track number when the titles agree (similarity >= 0.6). A file that cannot be matched (another edition of the album) keeps whatever it has.
* **Writing**: set when it differs from MusicBrainz; removed when MusicBrainz knows the track but has no sung language; **left untouched when MusicBrainz could not be asked** (a failed lookup is "unknown", never "no language"). The bare Vorbis `LANGUAGE` is not used: a tagger or the user may own it.
* **Client rules**: identifying `User-Agent`, at most one request per second, retry with backoff on 429/5xx; answers cached per release for 30 days in `config_dir/musicbrainz/` so a library run is offline after the first pass. `fixtags.py --languages-only` writes only this tag (no Discogs lookups); `musicbrainz_languages = False` in `config.py` switches the lookup off.
* **Consumer**: `lrc_fix.py` forces the transcription language from this tag (ADR 0009), which removes whisper's language misdetection (Gaelic or dialect singing detected as Latin or Welsh). `update_lyrics.py` reads it too: a lone `zxx` marks a plain-text or empty `LYRICS` tag instrumental (section 6).

### 6. Lyrics Tag Management (`LYRICS`)
* **Shared Formatting (`lrc_format.py`)**: The `[ar:]/[ti:]/[al:]/[length:]`
  header build/refresh logic, the instrumental marker format, and
  capitalization normalization live once, in `lrc_format.py`, imported as a
  sibling module by both `update_lyrics.py` and `lrc_fix.py` (and, for just
  the classification constants, `lrc_count.py`). Two independent copies of
  this logic previously drifted silently (see Artist Source below) — sharing
  the code makes that structurally impossible instead of a bug to catch by
  hand. `lrc_format.py` is pure string-in/string-out with no mutagen/FLAC
  dependency; each caller still owns its own tag reads. The design of `lrc_fix.py`
  itself is in ADR 0009.
* **Artist Source**: the "artist" used everywhere — the lrclib.net search
  query, the `[ar:]` LRC header, and log messages — is sourced from
  `ALBUMARTIST`, falling back to `ARTIST` only when `ALBUMARTIST` is empty
  (`lrc_format.resolve_artist`). This deliberately differs from §1's general
  read-only `ARTIST` metadata: a track's own `ARTIST` credit can carry
  rip-specific billing (e.g. `Roy Orbison With Guests` on a live album where
  `ALBUMARTIST` is the plain `Roy Orbison`) that lrclib.net's artist index
  doesn't recognize, causing otherwise-findable lyrics to 404.
* **Format Distinction**: Synced LRC (`[MM:SS.xx]`) vs Plain Text TXT.
* **Unmatched Lines & Alignment Quality Gate**: `lrc_fix.py` gives a lyric line the transcript cannot match an estimated time: interpolated between matched lines, and spread at the song's median seconds-per-line (capped at 8 s, kept inside the track) before the first and after the last matched line, so timestamps are distinct and strictly increasing (they used to copy a neighbouring line's time and pile up on one moment). A weak alignment could still replace a harmless tag with mostly guessed timestamps, so `lrc_fix.py` writes a result only if at least `--min-match` (default 0.6) of the lyric lines that contain a word matched, at least `--min-sung` (default 0.5) of the lyric's consecutive word pairs occur in the transcript (`lrc_fix.sung_ratio`, order independent: single common words can match enough lines for a song that is not sung, as the audit of the suspect tags showed for dialect and foreign-language tracks), and the result has no `one_timestamp`/`shared_timestamps` pile-up (5 or more lines and at least 20% of them on one timestamp); otherwise the tag is left unchanged. The test for "looks broken" is `lrc_format.lrc_suspect_reasons`, shared with `lrc_count.py --suspects` (a read-only report of existing tags) so the gate and the report cannot disagree. Source-text junk (e.g. credit lines with hearts) is not removed: it comes from the lyrics provider, not from alignment.
* **Header Preservation**: `update_lyrics.py` owns only the `ar`/`ti`/`al`/`length` header lines and updates their values **in place**, wherever they already sit in the tag; any id-tag line it doesn't own (e.g. a `[re:...]` line written by an external re-alignment tool, or `[by:...]`/`[offset:...]`) is left completely untouched, in its original position, rather than stripped and rebuilt at a fixed offset. Managed headers that are entirely missing are inserted at the top. This in-place merge (as opposed to a prior strip-and-rebuild design) is required so `update_lyrics.py` converges to a stable tag instead of perpetually re-ordering headers against any other tool that also writes id-tag lines to `LYRICS`.
* **Overwrite Rule**: `update_lyrics.py` replaces only TXT or empty lyrics. An existing LRC is never replaced by another source or deleted; it is only corrected in place (headers, characters, capitalization) without an lrclib.net request. (The former invalid-LRC refetch-and-clear branch was removed; it was dead code.)
* **Character Normalization**: `lrc_format.normalize_text`/`normalize_lrc_text` map typographic characters to ASCII in lyric text only (never the `[ti:]`/`[ar:]`/`[al:]`/`[length:]`/`[re:]` header lines, which come from the user's tags): `’ ‘` to `'`, `“ ”` to `"`, `‐ ‑ ‒ – —` to `-`, `…` to `...`, non-breaking/thin spaces to a space, `´`/backtick between letters to `'`, and zero-width space, BOM, word joiner, Hangul filler and object replacement characters are removed. Accented letters, other scripts and `♪`/`♡` are left alone. It runs on new fetches and on existing TXT and LRC (rewritten in place as "Fixed"), and `lrc_fix.py` applies it to its output and when tokenizing lyric lines for matching (so `don’t` is one word, as in the transcript), which keeps the two tools' output byte-identical.
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
* **Instrumental via `LYRICS_LANGUAGE`**: when a track's `LYRICS_LANGUAGE` (section 5b) is exactly `zxx` (MusicBrainz: no linguistic content) and its `LYRICS` tag is empty or plain text, `update_lyrics.py` writes the canonical marker block without an lrclib.net request (lrclib can only return wrong lyrics for such a track) and counts it as `Instrumental` / `new`. `zxx` next to a real language, `mul`, `und` or no tag do nothing. An existing synced LRC is never replaced, whatever the tag says (many such tags are valid, and MusicBrainz can be wrong for tracks with wordless or spoken vocals); `lrc_audit.py` judges those against the audio.
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
