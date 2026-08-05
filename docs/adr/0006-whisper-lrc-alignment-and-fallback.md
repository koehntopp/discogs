# ADR 0006: Whisper Speech-to-Text LRC Lyrics Alignment, Time-Anchor Search, and Fallback Architecture

- **Status**: Accepted
- **Date**: 2026-08-05
- **Authors**: Discogs Project Maintainers

## Context

Managing synchronized lyrics (`.lrc` / FLAC `LYRICS` tags) across a local FLAC music library requires high-accuracy timestamp alignment. Existing lyrics from external databases (such as LRCLIB or Genius) often contain unsynchronized text, missing timestamps, out-of-order timestamps, or timing drift.

To provide automated, precise timestamp alignment and auto-generation for local FLAC tracks, we implemented `align_lyrics.py` using OpenAI Whisper speech-to-text with word-level timestamps.

---

## Decision

We establish the following architectural rules and alignment contracts for `align_lyrics.py`:

### 1. Exclusive Lyrics Tag Authority
* `align_lyrics.py` inspects exclusively the FLAC `LYRICS` tag.
* General comment metadata (`COMMENT`) and non-standard tags (`UNSYNCEDLYRICS`) are ignored to prevent arbitrary comment strings (e.g. `'LoKET 2014'`, rip logs, or URLs) from being misinterpreted as lyric text.

### 2. Alignment & Time-Anchor Search Mechanics
* **Time-Anchor Search (`anchor_slack = 15.0s`)**: For lines with existing timestamps (`original_ts`), search only Whisper words whose start time falls within `[original_ts - anchor_slack, original_ts + anchor_slack]`.
* **Greedy Forward Search**: For plain-text (un-timestamped) input, search a forward look-ahead window of `max(n×3, 20)` words from the current cursor position.
* **Timestamp Assignment**: Use the best Whisper word match timestamp (`words[best_pos].start`) whenever `best_score > 0`. The `--min-confidence` threshold (default `0.50`) is reserved for warnings, Rich diagnostic table output, and red UI highlighting, rather than discarding valid Whisper timestamps.

### 3. Input LRC Anchor Sanitization
* **Inversion Detection**: If input LRC timestamps jump backwards ($t_k < t_{k-1} - 2.0\text{s}$), flag the tag as corrupted and nullify the invalid `original_ts` anchors.
* **Flat Duplicate Block Detection**: If $\ge 3$ consecutive lines share the exact same timestamp, treat those anchors as corrupt/unaligned and nullify `original_ts` so the lines are re-aligned sequentially against Whisper speech audio.

### 4. Whisper Segment-Based Splitting
* Lyric blocks spanning multiple Whisper segments (natural breath/pause boundaries) are split into individually-timestamped sub-lines.
* Requires a minimum of 3 words per segment fragment and a fragment similarity threshold $\ge 0.3$ to avoid splitting on short filler sounds.

### 5. Proportional Interpolation & Duration Clamping
* **Linear Interpolation**: Untimed leading, middle, or trailing lines are space-interpolated smoothly between surrounding valid timestamps instead of repeating `last_ts`.
* **Audio Duration Clamping**: All output LRC timestamps are capped at the track's total audio duration (`FLAC.info.length - 0.5s`) to prevent trailing ad-lib lines from exceeding song runtime.

### 6. Auto-Generation for Un-Tagged FLAC Files
* When a FLAC file has no `LYRICS` tag, `align_lyrics.py` transcribes the track with Whisper, formats speech segments into timestamped LRC lines (`[MM:SS.xx] transcribed text`), displays the generated preview, and writes to `audio['LYRICS']` when `--write` is specified.

---

## Consequences

* **Pros**:
  * Guarantees unique, monotonically advancing timestamps for every line.
  * Handles badly drifting input tags (up to 15s offset) and corrupt duplicate anchors automatically.
  * Provides instant LRC generation for un-tagged tracks directly from audio.
* **Cons**:
  * Running Whisper transcription requires CPU/GPU compute time per track.
