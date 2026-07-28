# ADR 0004: Album List Caching and Direct Lyrics Export Architecture

- **Status**: Accepted
- **Date**: 2026-07-28
- **Authors**: Discogs Project Maintainers

## Context

`album_list.py` is invoked periodically by `webui.py` (and after `bliss.py` runs) to regenerate `albums.csv` and `albums_dr.png`. Previously, `album_list.py` iterated through every single FLAC track in every album directory to read `LYRICS` tags and write `.lrc`/`.txt` files to `config_dir / 'lyrics'`.

This introduced two major inefficiencies:
1. `album_list.py` opened thousands of FLAC files unnecessarily on every scan, performing redundant disk I/O for unchanged albums.
2. Lyrics export logic was tied to library inventory scanning rather than `update_lyrics.py`, which is the primary authority for fetching and embedding lyrics.

---

## Decision

We establish the following architectural refactor:

### 1. Direct Lyrics Export in `update_lyrics.py`
* `update_lyrics.py` manages the lyrics cache in `config_dir / 'lyrics'`.
* When `update_lyrics.py` fetches, updates, or verifies lyrics, it writes `{discogs_id}_{track}.{ext}` directly to `config_dir / 'lyrics'` and removes stale/cleared lyric files.

### 2. Single-Track Scanning in `album_list.py`
* All track-by-track looping and lyrics disk writing are removed from `album_list.py`.
* `read_album()` reads **only the first FLAC track (`flacs[0]`)** per directory to extract album-level metadata (`ALBUMARTIST`, `ALBUM`, `ALBUM DYNAMIC RANGE`, `RELEASEDATE`, `DISCOGS_RELEASE_ID`, etc.).

### 3. Directory `mtime` Caching (`album_cache.json`)
* `album_list.py` maintains a persistent JSON cache in `config_dir / 'album_cache.json'`.
* If `os.path.getmtime(directory)` matches the cached modification time, `album_list.py` reuses the cached record immediately without reading FLAC files on disk.

---

## Consequences

### Positive
* **Sub-second Rescans**: Subsequent scans of unchanged libraries execute in **<0.5 seconds**.
* **Clean Separation of Concerns**: `update_lyrics.py` handles lyrics file persistence, while `album_list.py` acts purely as an inventory scanner.
