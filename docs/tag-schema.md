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
        string title "drelease.title, stripped -> ALBUM_RELEASE_TITLE"
        string master_title "master.title if a master release exists, else title -> ALBUM_MASTER_TITLE/ORIGINAL_TITLE"
        int year "drelease.year, used only if ALBUM_RELEASE_YEAR/DATE unset or invalid"
        string country "drelease.country -> ALBUM_RELEASE_COUNTRY, written only if present"
        string label "first drelease.labels entry's name -> ALBUM_RELEASE_LABEL, written only if present"
    }

    USER_OVERRIDE {
        string ALBUM_TITLE_OVERRIDE "= fixtags.py's album_override: wins over master_title in ALBUM.ALBUM when set"
        string ALBUM_ARTIST_OVERRIDE "= fixtags.py's album_artist_override: written straight into ALBUM.ALBUMARTIST when set"
    }

    ALBUM {
        string DISCOGS_RELEASE_ID PK "anchor, read-only by scripts"
        string ALBUMARTIST "= ALBUM_ARTIST_OVERRIDE when set, else left completely untouched"
        string ALBUM "= album_override (ALBUM_TITLE_OVERRIDE) if set, else clean master_title"
        string VERSION "year DRxx format (edition) (catalog); each part appended only if available"
        string DATE "= album_year_release (this pressing's year)"
        string RELEASEDATE "= album_year_release, same value as DATE"
        string YEAR "= album_year_release, legacy player-alias of DATE"
        string ORIGINALDATE "= album_year_master (original master release year)"
        string ORIGINALRELEASEDATE "= album_year_master, same value as ORIGINALDATE"
        string ORIGINAL_DATE "= album_year_master, legacy player-alias (space key)"
        string ORIGINAL_YEAR "= album_year_master, legacy player-alias (space key)"
        string ALBUM_MASTER_TITLE "= master_title, exact Discogs string, undecorated"
        string ALBUM_MASTER_YEAR "= album_year_master"
        string ALBUM_RELEASE_TITLE "= release_title, exact Discogs string, this pressing"
        string ALBUM_RELEASE_YEAR "= album_year_release"
        string ALBUM_MAX_RESOLUTION "max FLAC sample rate across every track in the directory"
        string ALBUM_EDITION "written only when present; also feeds VERSION's (edition) part"
        string ALBUM_FORMAT "= ALBUM_FORMAT tag, else SUBTITLE, else 'CD'"
        string ALBUM_RELEASE_COUNTRY "written only if Discogs returns a country"
        string ALBUM_RELEASE_LABEL "written only if Discogs returns a label"
        string ALBUM_DR "rounded mean of every TRACK's DYNAMIC_RANGE; written only if non-empty"
        string ORIGINAL_TITLE "= master_title, duplicate of ALBUM_MASTER_TITLE (legacy alias)"
        string SUBTITLE "ripper-set, read-only; also the ALBUM_FORMAT fallback source"
        string CATALOGNUMBER "+ CATALOG NUMBER/CATALOG_NUMBER/CATALOGNO fallbacks; feeds VERSION's (catalog) part"
        string MUSICBRAINZ_ALBUMID "+ MUSICBRAINZ ALBUM ID/MUSICBRAINZ_RELEASEGROUPID/MUSICBRAINZ RELEASE GROUP ID fallbacks"
    }

    TRACK {
        string TITLE "ripper-set, read-only"
        string ARTIST "ripper-set, read-only; may differ per track (e.g. compilation guests)"
        string TRACKNUMBER "ripper-set, read-only; 'n' or 'n/total'"
        string DISCNUMBER "ripper-set, read-only; 'n' or 'n/total'"
        string PART "= this track's own TITLE, always"
        string WORK "= this track's own SET_SUBTITLE, only when present on that track"
        string SET_SUBTITLE "user-set, per-track, on discs within multi-disc editions"
        string DYNAMIC_RANGE "EBU R128/drmeter score; + legacy 'DYNAMIC RANGE' fallback"
        string ACOUSTID_FINGERPRINT "fpcalc/Chromaprint; + legacy 'ACOUSTID FINGERPRINT' fallback"
    }

    LYRICS_BLOCK {
        string ar "header: artist, resolved from ALBUMARTIST falling back to ARTIST"
        string ti "header: this track's own TITLE"
        string al "header: this track's own ALBUM"
        string length "header: track duration as mm:ss"
        string la "= zxx (no linguistic content); instrumental tracks only"
        boolean instrumental_true "sentinel update_lyrics.py checks to skip re-fetching; instrumental tracks only"
        string lyric_lines "MM:SS.xx-prefixed synced LRC lines, or plain unsynced text"
    }
```

Modeled as: `DISCOGS_RELEASE` anchors one `ALBUM` (via `DISCOGS_RELEASE_ID`), which contains
many `TRACK`s and may be corrected by a `USER_OVERRIDE`; each `TRACK` optionally embeds a
`LYRICS_BLOCK`. `ALBUM`-level tags are written uniformly across the directory by `fixtags.py`;
`PART`/`WORK`/`DYNAMIC_RANGE`/`ACOUSTID_FINGERPRINT`/`LYRICS` are genuinely per-track.
