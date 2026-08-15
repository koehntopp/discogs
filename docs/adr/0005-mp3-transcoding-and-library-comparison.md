# ADR 0005: Library Organization, MP3 Mirror Sync, and Pipeline Orchestration Architecture

- **Status**: Accepted
- **Date**: 2026-08-01 (Updated)
- **Authors**: Discogs Project Maintainers

## Context

The Discogs Music Library Manager includes core tools for managing and organizing music collections across local and network storage volumes:
1. **Library & File Organization (`bliss.py`)**: Reorganizes FLAC files into canonical directory structures and track filename patterns.
2. **MP3 Mirror Sync (`bliss.py --mp3`)**: Transcodes FLAC tracks under `flacroot` to a mirrored MP3 tree under `mp3root` using `ffmpeg`.
3. **Pipeline Orchestration (`nzbfix.py`)**: Post-download enrichment pipeline for new album ingest.

---

## Decision

We establish the following architectural rules for library organization, MP3 mirror transcoding, and pipeline orchestration:

### 1. `bliss.py` File and Directory Organization Contract
* **Canonical Destination Path**:
  Every FLAC file is moved into the canonical structure:
  `<flacroot>/<Artist>/<Album_Version>/<disc_zz>_<track_zz>_<Title>.flac`

* **Component Derivation & `clean()` Sanitization**:
  * **`<Artist>`**: Derived from `clean(ALBUM_ARTIST_OVERRIDE or ALBUMARTIST or ARTIST or "Unknown Artist")`.
  * **`<Album_Version>`**: Derived from `clean(f"{ALBUM} {VERSION}".strip())`. Combines clean master title and plain-text version tag.
  * **`<disc_zz>`**: 2-digit zero-padded `DISCNUMBER` (`01`, `02`). Splits total track strings (e.g. `1/2` $\rightarrow$ `01`). Defaults to `01`.
  * **`<track_zz>`**: 2-digit zero-padded `TRACKNUMBER` (`01`, `07`). Splits total track strings (e.g. `7/12` $\rightarrow$ `07`). Defaults to `00`.
  * **`<Title>`**: Derived from `clean(TITLE or "Unknown Title")`.

* **Sanitization Rules (`clean()`)**:
  * Transliterates German umlauts (`ä` $\rightarrow$ `ae`, `ö` $\rightarrow$ `oe`, `ü` $\rightarrow$ `ue`, `Ä` $\rightarrow$ `Ae`, `Ö` $\rightarrow$ `Oe`, `Ü` $\rightarrow$ `Ue`, `ß` $\rightarrow$ `ss`).
  * Strips non-alphanumeric punctuation via Unicode NFKD normalization.
  * Replaces whitespace runs with single underscores (`_`).

* **NFD Normalization & Collision Safety**:
  * Source vs destination path comparison MUST use `unicodedata.normalize('NFD', path.lower())` for HFS+/macOS case-folding safety.
  * Snapshot file lists (`flac_files = [str(PurePosixPath(p)) for p in ...]`) MUST be pre-buffered before move loops to prevent live generator re-discovery of moved files.
  * Target collision protection: `bliss.py` refuses to move a file if `tobefullname` already exists.

* **Subcommand Execution Modes**:
  * `--ingest DIR`: Ingests files from `DIR` into `flacroot`, reorganizes them, and cleans up empty source directories.
  * `--full`: Scans entire `flacroot` recursively.
  * `--mp3`: Syncs MP3 mirror tree under `mp3root`.
  * Default (`bliss.py` with no flags): Quick scan of root-level files inside `flacroot`.

### 2. Post-Download Pipeline Orchestration (`nzbfix.py`)
* **Sequential 6-Step Processing Order**:
  When `nzbfix.py <directory>` is executed (via CLI or Web UI reprocess button), it MUST execute the following 6 stages sequentially:
  1. **`dot_clean`**: Strips macOS `._*` resource fork sidecar files.
  2. **`calculate_dr.py`**: Computes track and album Dynamic Range scores (`DYNAMIC_RANGE`, `ALBUM_DR`).
  3. **`rsgain`**: Computes EBU R 128 ReplayGain tags (`REPLAYGAIN_TRACK_GAIN`, `REPLAYGAIN_ALBUM_GAIN`, etc.) using a temporary `rsgain.ini` preset (`TagMode=i`).
  4. **`calculate_fp.py`**: Computes AcoustID acoustic fingerprints (`ACOUSTID_FINGERPRINT`).
  5. **`fixtags.py`**: Queries Discogs API, enriches metadata, and resizes embedded cover art (`cover_max_size`).
  6. **`update_lyrics.py`**: Queries `lrclib.net` for synced/unsynced lyrics, embeds `LYRICS` tags, and exports sidecar files.
* **Signal Handling & Temporary Cleanup**:
  * Installs a `signal.SIGINT` (Ctrl+C) handler to terminate active `rsgain` child processes and unlink temporary `rsgain.ini` preset files on interrupt.

### 3. MP3 Mirror Sync (`bliss.py --mp3`)
* **Relative Path Resolution**: MP3 target paths MUST be resolved using `os.path.relpath(flacfilename, flacroot)` under `mp3root`.
* **Explicit Parent Directory Creation**: `mp3_path.parent.mkdir(parents=True, exist_ok=True)` MUST be called immediately before invoking `ffmpeg`, guaranteeing output directories exist.
* **Captured `ffmpeg` Stderr & Explicit Error Logging**:
  * `subprocess.run(flac2mp3, capture_output=True, text=True)` captures `ffmpeg` error output.
  * On non-zero exit codes, `bliss.py` logs an explicit `logger.error` containing track filename, album title, and `ffmpeg` error text.
* **Rich Progress Bar & Per-Album Success**:
  * Renders a Rich progress bar (`Progress(..., disable=not _is_tty)`) in TTY mode.
  * Emits `success(f'Transcoded {count} MP3 track(s) for album {album_name}')` upon completing each album.

---

## Consequences

### Positive
* **Deterministic Disk Layout**: `bliss.py` guarantees uniform `<Artist>/<Album_Version>/<disc_zz>_<track_zz>_<Title>.flac` path structures across the entire library.
* **Predictable 6-Step Ingest**: Every newly ingested album undergoes identical, deterministic enrichment (`dot_clean` $\rightarrow$ `DR` $\rightarrow$ `ReplayGain` $\rightarrow$ `AcoustID` $\rightarrow$ `Discogs` $\rightarrow$ `Lyrics`).
* **HFS+ Unicode Safety**: NFD normalization prevents case-folding loops on macOS/HFS+ filesystems.
* **100% Reliability for MP3 Mirror Sync**: Destination directories exist before `ffmpeg` runs.
