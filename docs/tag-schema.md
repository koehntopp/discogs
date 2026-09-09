# FLAC Tag Schema — ERD

A visual companion to [ADR 0002](adr/0002-flac-tag-handling.md) (the FLAC tag handling
contract) and [ADR 0008](adr/0008-roon-specific-tag-conventions.md) (Roon-specific tags).
Those documents are authoritative — this diagram is a derived reference, not a replacement.

```mermaid
erDiagram
    DISCOGS_RELEASE ||--o| ALBUM : anchors
    ALBUM ||--o{ TRACK : contains
    ALBUM ||--o| USER_OVERRIDE : "corrected by fixtags.py"
    TRACK ||--o| LYRICS_BLOCK : embeds

    DISCOGS_RELEASE {
        string id PK "= DISCOGS_RELEASE_ID, user-set anchor tag"
        string title
        string master_title
        int year
        string country
        string label
    }

    USER_OVERRIDE {
        string ALBUM_TITLE_OVERRIDE "overrides ALBUM_MASTER_TITLE in ALBUM"
        string ALBUM_ARTIST_OVERRIDE "overwrites ALBUMARTIST directly"
    }

    ALBUM {
        string DISCOGS_RELEASE_ID PK "anchor, read-only by scripts"
        string ALBUMARTIST "overwritten if ALBUM_ARTIST_OVERRIDE set"
        string ALBUM "clean master title, no decoration"
        string VERSION "year DRxx format (edition) (catalog)"
        string DATE
        string RELEASEDATE
        string ORIGINALDATE
        string ORIGINALRELEASEDATE
        string ALBUM_MASTER_TITLE
        string ALBUM_MASTER_YEAR
        string ALBUM_RELEASE_TITLE
        string ALBUM_RELEASE_YEAR
        string ALBUM_MAX_RESOLUTION
        string ALBUM_EDITION
        string ALBUM_FORMAT "default CD"
        string ALBUM_RELEASE_COUNTRY
        string ALBUM_RELEASE_LABEL
        string ALBUM_DR "rounded mean of track DYNAMIC_RANGE"
        string SUBTITLE "ripper-set, read-only"
        string CATALOGNUMBER "+ CATALOG NUMBER/CATALOG_NUMBER/CATALOGNO fallbacks"
        string MUSICBRAINZ_ALBUMID "+ 3 legacy-key fallbacks"
    }

    TRACK {
        string TITLE "ripper-set, read-only"
        string ARTIST "ripper-set, read-only, may differ per track"
        string TRACKNUMBER
        string DISCNUMBER
        string PART "= this track's own TITLE"
        string WORK "= this track's own SET_SUBTITLE, if set"
        string SET_SUBTITLE "user-set, per-disc, box-set grouping"
        string DYNAMIC_RANGE "EBU R128/drmeter; + legacy fallback"
        string ACOUSTID_FINGERPRINT "fpcalc/Chromaprint; + legacy fallback"
    }

    LYRICS_BLOCK {
        string ar "header: artist"
        string ti "header: title"
        string al "header: album"
        string length "header: mm:ss"
        string la "= zxx, instrumental tracks only"
        boolean instrumental_true "sentinel, instrumental tracks only"
        string lyric_lines "MM:SS.xx-prefixed LRC lines, or plain text"
    }
```

Modeled as: `DISCOGS_RELEASE` anchors one `ALBUM` (via `DISCOGS_RELEASE_ID`), which contains
many `TRACK`s and may be corrected by a `USER_OVERRIDE`; each `TRACK` optionally embeds a
`LYRICS_BLOCK`. `ALBUM`-level tags are written uniformly across the directory by `fixtags.py`;
`PART`/`WORK`/`DYNAMIC_RANGE`/`ACOUSTID_FINGERPRINT`/`LYRICS` are genuinely per-track.
