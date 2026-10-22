# ADR 0008: Roon-Specific Tag Conventions

- **Status**: Accepted
- **Date**: 2026-08-17
- **Authors**: Discogs Project Maintainers

## Context

Several tagging decisions in this project exist purely to shape how [Roon](https://roon.app)
displays the library, rather than to satisfy Discogs metadata fidelity or general
Vorbis-comment convention. Those decisions have so far been documented piecemeal
inside ADR 0002 (general FLAC tag handling) alongside unrelated mechanics. This
ADR consolidates them into one place, as the authoritative record of "why does
this tag exist" from Roon's display model specifically. It defers to ADR 0002 for
the underlying tag-inventory and write-ownership rules (uppercase keys, user-tag
authority, etc.) and does not restate them.

---

## Decision

### 1. `ALBUM` / `VERSION` — clean title vs. release decoration
* `fixtags.py` and `migrate_tags.py` populate `ALBUM` with the clean master
  title only (no brackets or decoration, e.g. `Brothers in Arms`) and `VERSION`
  with a plain-text release decoration string (e.g. `2025 DR09 Blu-ray (40th
  Anniversary Edition) (DGCD 12345)`).
* Roon renders `VERSION` as its "Version" line whenever multiple editions of
  the same album exist in the library, letting the user tell pressings apart
  (remaster, deluxe edition, high-resolution transfer, etc.) without cluttering
  the album title itself.
* `VERSION` also carries the album's `DR<xx>` Dynamic Range score and, in
  parentheses, its catalog number — both appended only when available.
  Roon's own UI doesn't surface either at a glance, so folding them into the
  Version line makes them visible without an extra lookup, at the cost of the
  directory rename (below) whenever `ALBUM_DR` changes.
* `bliss.py` combines the same pair (`clean(f"{ALBUM} {VERSION}")`) to compute
  on-disk directory names — a filesystem consequence of these Roon-facing
  values, not an independent naming decision. See ADR 0002 §5 for the full
  formatting contract.

### 2. `DISCSUBTITLE` and `Disc N` folders — box-set discs
Source: https://help.roonlabs.com/portal/en/kb/articles/box-sets-how-to-check-your-files
* A single Discogs release — and therefore a single `fixtags.py` `fixdir`
  invocation — can span an entire multi-disc box set (e.g. a studio album, a
  live disc, and bonus material under one `DISCOGS_RELEASE_ID`).
* **Disc numbers**: Roon wants `DISCNUMBER` on every track and `TRACKNUMBER`
  restarting at 1 on each disc.
* **Disc title**: Roon checks `DISCSUBTITLE`, `SETSUBTITLE`, `SET SUBTITLE`,
  `TSST`, `DISCNAME` in that order and calls `DISCSUBTITLE` the reliable one.
  `fixtags.py` writes `DISCSUBTITLE` per track from that track's own
  `SET SUBTITLE` (the user-set tag, e.g. `Studio Album`, `Live Recording`);
  removed if `SET SUBTITLE` is cleared there. ADR 0002 §5a has the mechanics.
* **Folders**: Roon expects one folder per box with one `CD1`/`Disc 1` subfolder
  per disc. `bliss.py` therefore places a multi-disc album's tracks in
  `<Album_Version>/Disc <n>/` (single-disc albums stay flat; ADR 0005 §1).
  Folders starting with a disc marker are merged into their parent by Roon,
  which is the intent here; a separate album folder never starts with one.
  Per-disc cover art (`folder.jpg` inside a disc folder) is possible with this layout.
* **Display rules and setting**: disc titles appear only when at least two discs
  have different titles, and only if Settings > Library > Import settings >
  "Metadata preferences for discs" is set to "Prefer file" (default "Prefer Roon").
  After retagging or moving, rescan the album; to regroup a split box, select
  all its albums and Rescan (Force Scan does not regroup).
* **`WORK`/`PART`**: earlier versions wrote them (`WORK` from `SET SUBTITLE`,
  `PART` from `TITLE`) on the assumption that Roon renders them as a group
  header and track label. Roon's box-set documentation does not mention them,
  so `fixtags.py` no longer writes them and removes them where set (the old
  writer is kept commented out).

---

## Consequences

### Positive
* **Correct Roon Version Display**: Multiple pressings/editions of the same
  album are distinguishable via `VERSION` without polluting `ALBUM`.
* **Box-Set Disc Identification**: Multi-disc box sets processed as a single
  Discogs release surface per-disc structure in Roon, via `DISCNUMBER`,
  `DISCSUBTITLE` and `Disc N` folders, without requiring multiple
  `DISCOGS_RELEASE_ID` lookups.

### Negative / Trade-offs
* `DISCSUBTITLE` depends on the user manually maintaining `SET SUBTITLE` per disc —
  there's no Discogs API field this can be derived from automatically.
* Disc titles show up in Roon only with the "Prefer file" import setting.
