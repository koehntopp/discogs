# Plan: bliss moves files whose artist/album folder differs from the tags, including case-only differences

## Problem

`bliss.py /Volumes/flac` fails with `[Errno 17] File exists` for `Chris_De_Burgh/Eastern_Wind.../01_07_Sailor.flac`.
The tag says `Chris de Burgh`, the folder is `Chris_De_Burgh`. Two defects:

1. `move_flac_file()` calls `os.makedirs()` before comparing source and target. The target path does not
   exist for a case-sensitive lookup, but the share creates case-insensitively and answers `EEXIST`.
2. Both `move_flac_file()` and `movefiles()` compare with `NFD(path.lower())` (ADR 0005 §1). A case-only
   difference counts as "same path", so even without the error the folder would never be renamed.
   Wanted: the folder follows the tag, as for any other difference.

## Design

- **Exact comparison.** Compare `NFD(path)` without `.lower()`. NFD stays (HFS+ composes/decomposes names);
  the case folding goes. A path differing only in case is a move.
- **Case-only rename of a directory component** (artist, album, `Disc N`): a plain `makedirs` + `move`
  collides on a case-insensitive share. Rename the existing directory in place, via a temporary name
  (`Chris_De_Burgh` -> `Chris_De_Burgh.bliss-tmp` -> `Chris_de_Burgh`), once per directory, then the
  remaining per-file logic sees the files already in the right folder. Done in a new helper
  `fix_case(parent, wanted)`: looks up the real on-disk name with `os.listdir(parent)` (an exact, not
  `os.path.exists`, check), and if it equals `wanted` ignoring case but not exactly, does the two-step rename.
- **Case-only rename of a filename**: same two-step rename.
- **Order in `move_flac_file()`**: resolve case-only differences of artist, album and disc folders first
  (`fix_case`), then create missing directories, then move. No `makedirs` on a path whose parent was just
  renamed to a different case.
- **One code path.** `movefiles()` (no flag, `--full`) inlines its own copy of the same logic; make it call
  `get_target_path_and_filename()` + `move_flac_file()` like `ingestfiles()` does, so both modes behave
  identically. Keep its `success(f'Moving album ...')` log line.
- **Conflicting spellings in one run.** Two albums of the same artist tagged `Chris de Burgh` and
  `Chris De Burgh` would rename the folder back and forth. Before moving, group the run's files by casefolded
  artist directory; if a group has more than one spelling, log one `warning` naming the spellings and skip
  those files (the tags must be fixed first). Same for album directories.
- **Real collisions stay refused**: if the target file exists with a different case, log the existing
  "target file already exists" error as before.
- **No change** to the quick scan's file selection (root-level files plus flat multi-disc albums): it still
  does not look into artist folders, so a retag is picked up by `--full` or by ingest of the folder.

## Files

- `bliss.py`: `fix_case()` new, `move_flac_file()` and `movefiles()` changed, spelling-conflict check new.
- `SPEC.md` (bliss section): case-only differences are moved; conflicting spellings are skipped with a warning.
- `docs/adr/0005-mp3-transcoding-and-library-comparison.md` §1: replace the "NFD + lower" comparison rule
  with "NFD, case-sensitive; case-only renames via a temporary name".
- `README.md`: only if it describes the comparison (check; likely no change).
- `docs/tag-schema.md`: no change (no tag affected).

## Verification (never on `/Volumes/flac`)

On a scratch root on a different path (APFS there is case-insensitive like the share):
1. Album in `Art_De/Alb/` with tag `Art de`: `--full` renames the folder to `Art_de`, files intact; second run is a no-op.
2. Same via `bliss.py <dir>` ingest of the scratch library root (the failing case): no error.
3. Case-only filename difference is renamed.
4. Two albums with conflicting artist spellings: warning, nothing moved.
5. Multi-disc album (`Disc 2` vs `disc 2`) is renamed.
6. `uvx ruff format .` and `uvx ruff check .` clean, `uv run check_docs.py` passes.

Then commit and `git push github main`.

## Not doing

- Renaming the real library folder now: after the fix, `bliss.py --full` does it.
- Case-insensitive matching of artist folders to reuse an existing folder with a different case (the tag wins).
