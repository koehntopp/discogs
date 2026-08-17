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
  with a plain-text release decoration string (e.g. `2025 Blu-ray (40th
  Anniversary Edition)`).
* Roon renders `VERSION` as its "Version" line whenever multiple editions of
  the same album exist in the library, letting the user tell pressings apart
  (remaster, deluxe edition, high-resolution transfer, etc.) without cluttering
  the album title itself.
* `bliss.py` combines the same pair (`clean(f"{ALBUM} {VERSION}")`) to compute
  on-disk directory names — a filesystem consequence of these Roon-facing
  values, not an independent naming decision. See ADR 0002 §5 for the full
  formatting contract.

### 2. `WORK` / `PART` — per-track box-set grouping
* A single Discogs release — and therefore a single `fixtags.py` `fixdir`
  invocation — can span an entire multi-disc box set treated as one release
  (e.g. a Blu-ray box set combining a studio album, a live disc, and bonus
  material under one `DISCOGS_RELEASE_ID`). Nothing in the album-level tag set
  (§1 above, or ADR 0002's "Structured Custom Metadata") distinguishes one
  disc from another within such a release.
* `fixtags.py` writes two tags **per track** to solve this, independently of
  the uniform album-level tags:
  * **`WORK`** — copied from that track's own `SET SUBTITLE`, a tag the user
    sets manually, per disc, within multi-disc editions (e.g. `Disc 1: Studio
    Album`, `Disc 2: Live Recording`). Only written when `SET SUBTITLE` is
    present on that specific track; removed if it's later cleared there.
  * **`PART`** — always copied from that track's own `TITLE`, unconditionally.
* Roon renders `WORK` as a shared header it groups tracks under, and `PART` as
  the individual track label shown beneath that header — so discs of a box set
  appear as distinct, identifiable groups in Roon even though this codebase's
  own tooling (Discogs lookup, `bliss.py` directory layout) treats the whole
  release as one flat album directory. See ADR 0002 §5a for the write
  mechanics (per-track loop, stale-tag cleanup).

---

## Consequences

### Positive
* **Correct Roon Version Display**: Multiple pressings/editions of the same
  album are distinguishable via `VERSION` without polluting `ALBUM`.
* **Box-Set Disc Identification**: Multi-disc box sets processed as a single
  Discogs release still surface per-disc structure in Roon, via `WORK`/`PART`,
  without requiring the release to be split into multiple directories or
  multiple `DISCOGS_RELEASE_ID` lookups.

### Negative / Trade-offs
* `WORK` depends on the user manually maintaining `SET SUBTITLE` per disc —
  there's no Discogs API field this can be derived from automatically.
