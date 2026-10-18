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
* When `update_lyrics.py` fetches, updates, or verifies lyrics, it writes `{discogs_id}_{track}.{ext}` directly to `config_dir / 'lyrics'`. The file is written **only when its content differs**, so unchanged entries keep their modification time (a consumer can use it to detect changes); a tag without lyrics removes its entry, and a type switch removes the other extension.
* After a complete run, **stale entries are pruned**: for each Discogs ID seen in the run, files whose key no collected track has any more (for example after a `TRACKNUMBER` retag from `8` to `08`) are removed. Tracks whose lookup failed still count as present, so a failed lookup never deletes an entry. An ID is pruned only when all of its tracks in the run come from one directory and none was unreadable, and an interrupted run prunes nothing.
* **Known limitation**: the key has no disc number. On a multi-disc set whose `TRACKNUMBER` restarts per disc, every disc's track 1 shares `{discogs_id}_1` and the last one processed wins. The key is kept as is for compatibility with existing consumers; such an ID spans several directories, so it is never pruned.

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
