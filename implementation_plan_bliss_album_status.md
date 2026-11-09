# Plan: bliss announces moved albums, not every title

## Problem

`bliss.py` logs one line per moved title (`Ingested <title>` in `ingestfiles`), plus `Ingesting album <album>`
(info) when the album changes. `movefiles` logs `Moving album <album>` before the move. For a 15-track album that
is 16 lines; the web log modal is flooded.

## Change

- New small helper in `bliss.py`: an album tracker that counts moved/renamed files per album and emits
  **one** `success` line when the album changes and at the end of the run:
  `Moved album <Artist>/<Album> (<n> tracks)` (singular for 1 track). Albums where nothing moved log nothing.
- `ingestfiles`: remove the per-title `success('Ingested ...')` and the `Ingesting album ...` info line; count
  each `move_flac_file(...) == True` instead. Key = `<artist>/<album>` from the metadata dict.
- `movefiles`: replace `Moving album <album>` (logged before the move) with the same tracker, so both modes
  print the identical line, after the move and only if a file moved.
- Warnings/errors (refused moves, case renames, skipped spellings) stay per-file: they need the file name.
- Kept: the start line (`Ingesting FLAC files from ...`) and the final `Done.`.

## Files

- `bliss.py`.
- `SPEC.md` bliss section: one sentence on the log output. ADR 0005 and README: no change (check README).

## Verification

Scratch library (never `/Volumes/flac`): ingest 2 albums of 3 and 1 tracks -> exactly `Moved album A/B (3 tracks)`
and `Moved album C/D (1 track)`; a second run prints no album lines. `ruff format`, `ruff check`, `check_docs.py`,
then commit and `git push github main`.
