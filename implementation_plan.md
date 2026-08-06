# Implementation Plan: Capitalize first letter of each lyric line in `update_lyrics.py`

## Goal
Every stored line of lyrics (synced LRC and plain TXT) should start with a capital
letter. This must apply both to newly fetched lyrics and to lyrics already embedded
in FLAC files from a previous run — existing synced (LRC) lyrics get corrected in
place, not just left alone.

## Design

### New helpers (`update_lyrics.py`)
```python
LRC_LINE = re.compile(r'^(\[\d{2}:\d{2}\.\d{2}\])(.*)$')

def _capitalize_line(text: str) -> str:
    """Uppercase the first character of a line; no-op on empty or non-letter starts."""
    return text[0].upper() + text[1:] if text else text

def _capitalize_lrc(lrc: str) -> str:
    """Capitalize the lyric text following each [MM:SS.xx] timestamp.
    Header lines ([ar:..], [ti:..], etc.) don't match LRC_LINE and pass through untouched."""
    out = []
    for line in lrc.splitlines():
        m = LRC_LINE.match(line)
        out.append(m.group(1) + _capitalize_line(m.group(2)) if m else line)
    return '\n'.join(out)

def _capitalize_txt(text: str) -> str:
    return '\n'.join(_capitalize_line(line) for line in text.splitlines())
```

### Apply at every point lyrics text is finalized in `_fetch_one`
1. **Existing valid LRC** (`elif _is_lrc(existing_lyrics):`): after `_apply_headers`,
   also run `_capitalize_lrc`. If the result differs from what's on disk, return it
   with a save-triggering action (see below) instead of `skip`.
2. **Newly fetched synced lyrics** (`data.get('syncedLyrics')`): capitalize via
   `_capitalize_lrc` before the `existing_lyrics` comparison/return.
3. **Newly fetched plain lyrics** (`data.get('plainLyrics')`): capitalize via
   `_capitalize_txt` before returning.
4. **Fallback when nothing new was fetched but plain-text lyrics already exist on
   disk** (currently falls through to the final `return` using `existing_lyrics`
   verbatim): capitalize via `_capitalize_txt`/`_capitalize_lrc` as appropriate; if
   changed, trigger a save instead of `skip`.

### Action naming
Rename the `'header'` action to `'fix'` (it now covers both header-refresh and
capitalization corrections to already-embedded lyrics) — updates in `_fetch_one`
and in `main()`'s dispatch (`if action in ('new', 'fix', 'clear'):`) and log message
(`logger.success(f'Lyrics fixed: {title} ({artist})')` instead of the current
"LRC headers updated" text).

### Scope / non-goals
- Only the first character of each line is uppercased; nothing else in the line is
  altered (no lowercasing the rest, no touching punctuation-only or blank lines).
- LRC header lines (`[ar:]`, `[ti:]`, `[al:]`, `[length:]`) are never touched by the
  capitalization pass — confirmed via regex mismatch, not a special case.

## Documentation sync (per CLAUDE.md)
- `SPEC.md` — add a bullet under `update_lyrics.py` → Behaviour noting that stored
  lyric lines (new and pre-existing) are normalized to start with a capital letter.
- `docs/adr/0002-flac-tag-handling.md` — add a line under "§6 Lyrics Tag Management"
  noting the capitalization-normalization rule alongside the existing header
  preservation rule.

## Testing
Per CLAUDE.md's "No Production Data Testing" rule: copy 2–3 small FLAC files with
mixed-case LRC/TXT `LYRICS` tags (some already capitalized, some not, one with
invalid timestamps) into `/tmp/update_lyrics_test/`, run
`uv run update_lyrics.py /tmp/update_lyrics_test`, and inspect the resulting tags.

## Git commit
After the change is verified, commit `update_lyrics.py`, `SPEC.md`, and the ADR
update together with a descriptive message, per CLAUDE.md's mandatory-commit rule.
