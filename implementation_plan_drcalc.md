# Implementation plan: calculate_dr.py uses drcalc

## Goal

Replace the Python `drmeter` + `soundfile` + `ProcessPoolExecutor` DR computation with the Rust
binary [drcalc](https://github.com/koehntopp/drcalc) (same algorithm, results identical on 287
tracks, about 4x faster, parallel, writes `DYNAMIC_RANGE` / `ALBUM_DR` itself).

## Facts checked

- `drcalc -w -q <dir>`: writes `DYNAMIC_RANGE` and `ALBUM_DR` (two-digit, zero padded, 0 never
  written), keeps other tags, does not rewrite files already holding the right values. `Disc N` /
  `CD N` folders belong to the parent album (same as `disc_layout`). Album DR = mean of rounded
  track DRs, rounded half-to-even (same as Python `round`), 0-DR tracks excluded.
- Exit code 1 if any file could not be analysed or tagged. Files under 12 s cannot be measured.
- It has no "skip tracks already tagged": it re-analyses every file on every run. The current script
  analyses only tracks without `DYNAMIC_RANGE`.
- Spaced legacy keys are not read or written (the current script does not use them either).
- Installed locally: `~/.local/bin/drcalc` 0.1.0. Releases: v0.1.0 with static Linux x86_64/arm64.
- Callers: `nzbfix.py` (runs `calculate_dr.py <dir>` as a subprocess, so the CLI stays) and the
  Docker image (needs the binary).

## Design

`calculate_dr.py` keeps its CLI (`uv run calculate_dr.py [DIR]`) and becomes a thin wrapper:

1. Find `drcalc` (`shutil.which`; error and exit 1 if missing).
2. Per album directory (grouped with `disc_layout.album_root_of_file`, as now), skip it when every
   track has a non-zero `DYNAMIC_RANGE` and every track has the correct `ALBUM_DR`... **see open
   question 1**.
3. Run `drcalc -w -q <dir>` and map the exit code (non-zero: `logger.error`, propagate non-zero).
4. Log drcalc stderr lines through `logger`.

Removed: `drmeter`, `soundfile` PEP 723 dependencies, `_track_dr`, the process pool, the manual tag
writing and the album mean (all done by drcalc). `mutagen` stays only if the skip check (question 1)
is kept.

Per-track lines (`DR 00 -> 11  Title`) and the per-album "Album DR updated" lines disappear unless
we parse `-f json`; see question 2.

## Open questions

1. **Skip already tagged tracks?** Re-analysing a full library or a big album on every
   `nzbfix` run costs time that the Python version avoids. Option A (recommended): keep a cheap
   pre-check with mutagen and call drcalc only on directories where some track lacks
   `DYNAMIC_RANGE` or `ALBUM_DR` is missing or wrong (needs the album mean, so it needs the track
   values only, which are in the tags). Option B: always run drcalc (simplest, about 4x faster per
   track anyway, but re-analyses everything).
2. **Logging detail.** Option A (recommended): run `drcalc -w -q` and log one line per album
   ("Album DR 11 for <dir>") from a follow-up tag read. Option B: use `-f json` and log per track
   and album from the report (more output, closer to today's lines).
3. **Docker image.** Add the drcalc release binary to the `Dockerfile` (download the static
   Linux binary by `ARG DRCALC_VERSION=0.1.0` and `TARGETARCH`, copy to `/usr/local/bin`). Needed
   for the Web UI reprocess button. OK to add?

## Files to change (after approval)

- `calculate_dr.py`: rewrite as above; ruff check/format.
- `Dockerfile`: install `drcalc`.
- `webui.py:1417`: credits table row `drmeter` -> `drcalc`.
- Docs (mandatory sync): `SPEC.md` (`calculate_dr.py` section, "External tools: drcalc"),
  `README.md` (setup requirement: `drcalc` on PATH, install line; credits at line 211),
  `CLAUDE.md` (component line), `docs/adr/0002-flac-tag-handling.md` (line 34: computed via
  `drcalc`, port of drmeter), `docs/tag-schema.md` line 65 (derivation note).

## Test (on a copy, never on /Volumes/FLAC)

Copy 2 albums (one multi-disc with `Disc N` folders) to a path under `/tmp`, strip `DYNAMIC_RANGE`
and `ALBUM_DR` from one, run old script on copy A and new script on copy B, diff the tags
(`metaflac --export-tags-to=-`). Expect identical values. Also re-run to confirm idempotence
(no file mtime change when nothing differs) and the exit code on a missing binary.

## Commit

One commit after tests and ruff pass, pushed with `git push github main`.
