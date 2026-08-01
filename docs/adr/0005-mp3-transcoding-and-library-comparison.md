# ADR 0005: MP3 Mirror Transcoding and Multi-Copy Library Comparison

- **Status**: Accepted
- **Date**: 2026-08-01
- **Authors**: Discogs Project Maintainers

## Context

The Discogs Music Library Manager includes two essential tools for managing and auditing music collections across storage volumes:
1. **MP3 Mirror Sync (`bliss.py --mp3`)**: Transcodes FLAC tracks under `flacroot` to a mirrored MP3 tree under `mp3root` using `ffmpeg`.
2. **Library Audit & Comparison (`compare_libraries.py`)**: Audits a reference/backup FLAC library against a target library to identify exact matches, renamed/moved directories, missing releases, and track count mismatches.

Past execution issues revealed:
- `bliss.py --mp3` threw `No such file or directory` errors when target directory structures under `mp3root` were not pre-created before `ffmpeg` execution.
- `ffmpeg` written C-level error logs directly to `stderr` without Python capturing them, obscuring which FLAC track or album failed transcoding.
- `compare_libraries.py` mapped albums via flat `{key: album}` dictionary comprehensions, causing multiple folders sharing the same `DISCOGS_RELEASE_ID` (such as box sets or multiple reissues of an album) to overwrite each other and collapse physical directory counts.

---

## Decision

We establish the following architectural rules for MP3 mirror transcoding and library comparison:

### 1. MP3 Mirror Sync (`bliss.py --mp3`)
* **Relative Path Resolution**: MP3 target paths MUST be resolved using `os.path.relpath(flacfilename, flacroot)` under `mp3root`.
* **Explicit Parent Directory Creation**: `mp3_path.parent.mkdir(parents=True, exist_ok=True)` MUST be called immediately before invoking `ffmpeg`, guaranteeing that `ffmpeg`'s output directory exists 100% of the time.
* **Captured `ffmpeg` Stderr & Explicit Error Logging**:
  * `subprocess.run(flac2mp3, capture_output=True, text=True)` MUST capture `ffmpeg` C-level error messages in Python.
  * When `ffmpeg` returns a non-zero exit code, `bliss.py` MUST log an explicit `logger.error` containing the track filename, album title, and `ffmpeg` error text.
* **Rich Progress Bar & Per-Album Success**:
  * `createMP3()` renders a Rich progress bar (`Progress(..., disable=not _is_tty)`) in TTY mode.
  * Emits `success(f'Transcoded {count} MP3 track(s) for album {album_name}')` upon completing each album that required MP3 transcoding.

### 2. Multi-Copy Library Comparison (`compare_libraries.py`)
* **List-Based Key Mapping**:
  * `compare_libraries.py` MUST use `ref_by_key = defaultdict(list)` to store albums by key.
  * Multiple folders or reissues sharing the same `DISCOGS_RELEASE_ID` (or box sets) MUST NOT collapse or overwrite each other in dictionary comprehension.
  * Every physical directory in the reference library MUST be preserved and paired by relative path or track counts.
* **Summary CLI Mode (`--stats` / `-s`)**:
  * `--stats` (`-s`) CLI option scans a library directory and logs total album count, total FLAC song count, and average tracks per album without running a comparison against a second library.

---

## Consequences

### Positive
* **100% Reliability for MP3 Mirror Sync**: Destination directories exist before `ffmpeg` runs, eliminating file creation failures.
* **Actionable Transcoding Diagnostics**: Any corrupted FLAC frame failure is explicitly logged with track filename and album title.
* **Accurate Library Audits**: Every physical album directory in a reference/backup volume is accounted for during library comparison.

### Negative / Trade-offs
* `bliss.py --mp3` requires pre-scanning album directories to render progress bars and group track conversions by album.
