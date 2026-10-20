# ADR 0009: Local LRC Realignment with `lrc_fix.py` (demucs, whisperx, Onset Snapping)

- **Status**: Accepted (supersedes ADR 0006)
- **Date**: 2026-10-19
- **Authors**: Discogs Project Maintainers

## Context

Lyrics fetched from lrclib.net, or typed in by hand, are often plain text or carry timestamps that
drift from the actual recording. Fixing the `LYRICS` tag means finding when each line is sung.

ADR 0006 solved this with `align_lyrics.py`: a single Whisper pass (`stable-whisper`, MLX, about 3 s
per track on Apple Silicon) over the full mix, with time-anchor search around the old timestamps.
`lrc_fix.py` takes a different route: it removes the instrumental parts before recognition, because
those are whisper's main hallucination trigger, and it only ever writes timestamps it can ground in a
recognized word. `align_lyrics.py` was deleted and replaced by `lrc_fix.py`, which began as a separate
project and was brought into this repository. This ADR
records why `lrc_fix.py` works the way it does. Usage and the flag reference are in
`README-lrc_fix.md`; the contracts it shares with `update_lyrics.py` (header lines, character and
capitalization normalization, the instrumental marker) are in ADR 0002 section 6 and are not repeated
here.

---

## Decision

### 1. Pipeline (per track)

1. **Isolate vocals** with demucs (`--two-stems vocals`). Instrumental sections are the main trigger for
   whisper hallucinating text, so the recognizer only ever sees the vocal stem. `--no-isolate-vocals`
   transcribes the full mix instead.
2. **Transcribe and force-align** with whisperx, giving word-level start times.
   `condition_on_previous_text=False`, so a hallucinated guess (typically over an instrumental intro) is
   never fed back as context and cascaded into more hallucinated text. whisper misdetects the language
   of some singing (Gaelic or dialect as Latin or Welsh) and whisperx has no alignment model for some
   languages; instead of failing, the track is transcribed again as `--fallback-language` (default
   `en`). Such transcripts are rough, which the sung-text check below catches. Better than reacting
   to the failure is knowing the language: `fixtags.py` writes the sung language per track from
   MusicBrainz into `LYRICS_LANGUAGE` (ADR 0002 section 5b), and `track_language` uses it before any
   work. `--language` wins; one language that whisper and whisperx can handle is forced (ISO 639-3 to
   whisper code from a table generated from whisper's own list, plus a few dialect fallbacks such as
   `ksh` to `de`); `zxx` and languages without a whisper or alignment model skip the track
   (transcribing Irish with a wrong-language model only produces a transcript the checks below
   would reject, after a minute of CPU); several languages or `mul`/`und` auto-detect. The tag is
   MusicBrainz data and can be wrong, hence `--ignore-language-tag`.
3. **Match** the known lyric lines against the transcript with `difflib.SequenceMatcher` over lowercase
   Unicode word tokens (`[^\W_]+`, with an internal apostrophe allowed; not ASCII-only, so Cyrillic,
   CJK and accented lyrics tokenize; the text is passed through `lrc_format.normalize_text` first so a
   curly apostrophe does not split `don't`). Only runs of two or more consecutive words are trusted for
   a line's time; a single matched word is a fallback, because one is easy to hit by chance.
4. **Snap to onsets**: each matched time is pulled back to the nearest librosa onset (computed on the
   same audio, `backtrack=True`) within 0.7 s before, falling back to one up to 0.2 s after, so it lands
   on the attack of the word, not mid-word. `--no-snap-onsets` skips this.
5. **Sanity check** when no line matched at all: silero-vad is run on the audio. No speech either means
   the tag is probably a mislabeled instrumental; the tag is left unchanged with a warning.
   `--no-vocal-check` skips this.

Alignment is deterministic and deliberately not LLM-based (see section 8).

### 2. Modes and file selection

- A file path is always processed. A directory is searched recursively; files with no usable lyrics
  (no `LYRICS` tag, empty after parsing, or a bare `Instrumental` placeholder) are excluded and not
  counted, so the number reported up front is what will actually run.
- Files whose tag is already LRC-timestamped are not realigned unless `--all`. They get a metadata-only
  pass instead: the `ar`/`ti`/`al`/`length` headers are refreshed from the FLAC's own tags and the
  timestamped body (including a hand-added marker such as `[00:00.00](Spoken Intro)`) is left untouched,
  with no demucs or whisperx involved.
- A bare instrumental placeholder is completed to the canonical marker block (ADR 0002 section 6),
  preserving any other header line.
- `--find-missing-lyrics` is a separate mode for files with no `LYRICS` tag at all: VAD alone, no
  transcription. No speech: the canonical instrumental marker is written. Speech found: the file is
  only logged as needing lyrics from elsewhere; nothing is written.

### 3. Unmatched lines and the quality gate

- A line the transcript cannot match gets an estimated time: interpolated between matched lines; before
  the first and after the last matched line, spread at the song's median seconds-per-line (at most 8 s,
  kept inside the track). A matched line that is not later than the previous one is treated as
  unmatched, and times are made strictly increasing at the 0.01 s resolution LRC can express. This
  replaced copying a neighbour's time, which piled a failed head or tail onto one timestamp.
- Estimated times are still guesses, so a result is written only if all three hold (`--no-quality-gate`
  bypasses them): at least `--min-match` (default 0.6) of the lyric lines that contain a word matched
  the transcript in order; at least `--min-sung` (default 0.5) of the lyric's consecutive word pairs
  occur anywhere in the transcript (`sung_ratio`, order independent); and `lrc_format.lrc_suspect_reasons` reports neither `one_timestamp` nor
  `shared_timestamps` (5 or more lines and at least 20% of them on one timestamp; tags of fewer than 3
  timestamped lines are not judged). Otherwise the tag is left unchanged with a `skip:` message.
  `lrc_count.py --suspects` uses the same function to report existing tags, so the gate and the report
  cannot disagree. See ADR 0002 section 6.
- The `--min-sung` check was added after `lrc_audit.py` (the audit of the suspect tags) showed that the
  line check alone accepts songs that are barely sung: with single common words matching enough lines,
  a dialect track with 7% of its word pairs in the transcript passed with 68% matched lines. The two
  checks answer different questions: the line match says the lines can be placed in order, the sung
  ratio says the words are there at all.

### 4. ASR cache

demucs and whisperx take about a minute per track on CPU, while their output depends only on the
audio, and only the lyric text changes between runs. Their output is therefore cached.

- **Where and what**: `~/.cache/lrc_fix/<discogs_id>_<disc>_<track>.json` (`--cache-dir`), holding the
  word timestamps and, once computed, the vocal onsets. Lyric text is never cached, so tag edits and
  `--min-match`/`--no-quality-gate` changes take effect immediately.
- **Key**: `DISCOGS_RELEASE_ID`, `DISCNUMBER` (default 1), `TRACKNUMBER` (`7/12` and `07` are track 7).
  A file without a numeric Discogs ID or a track number is never cached.
- **Validity**: an entry is used only if the whisper model, language, compute type, vocal isolation
  setting, and the FLAC's sample rate and total sample count all match the current run. The sample
  count is used instead of the modification time because every tag write changes the mtime, while a
  replaced rip that reuses the same Discogs ID and track number changes the sample count. A missing or
  corrupt file is a miss, never an error; writes go through a temp file and `os.replace`.
- **Rejected tracks are cached too** (written right after transcription, before the gate). They stay
  un-synced, so without this every run would redo their demucs and whisperx pass.
- **Partial entries**: onsets are computed lazily. An entry without them (the track was gated out, or
  `--no-snap-onsets` was used) costs one demucs pass when they are first needed, as does the VAD
  fallback, which needs the audio.
- **Language**: the key holds the requested `--language` only, so the existing cache stays valid; the
  entry records the language it was actually transcribed in (`language_used`), and is redone when the
  tag now names a different one. Entries without the field are trusted.
- `--no-cache` neither reads nor writes; `--refresh-cache` ignores existing entries and rewrites them;
  `--dry-run` still writes the cache because it only protects the `LYRICS` tag.

### 5. `LYRICS` tag ownership

- The tag is rewritten in place and parsed fresh from its current content on every run, with no backup,
  so a hand edit (fixing a misheard word, adding a line that repeats) takes effect on the next run. If
  a run goes wrong, the recovery is to delete the tag and re-fetch lyrics, not to restore from a copy.
  `--dry-run` prints the result and does not write the tag.
- Header, instrumental-marker, capitalization and character logic lives in `lrc_format.py`, shared with
  `update_lyrics.py`, and `[ar:]` comes from `ALBUMARTIST` falling back to `ARTIST`
  (`lrc_format.resolve_artist`). Two independent copies of this had drifted so that each tool kept
  "fixing" the other's output; sharing the code is what keeps them idempotent against each other.
- `lrc_fix.py` is the only writer of the `[re:]` creator tag (`https://github.com/koehntopp/lrc_fix`).
  It is stamped only when a run changes lyric content (a realignment, a completed instrumental marker),
  never for a metadata-only refresh. A file whose metadata and lyrics are already correct compares
  equal to its prior content and is not rewritten, instead of a stale `[re:]` forcing a rewrite on every
  run.

### 6. Dependency pins (load-bearing)

- `torch` and `torchaudio` `>=2.4,<2.6`: `>=2.4` because `transformers` needs it; `<2.6` because torch
  2.6 flips the `torch.load` `weights_only` default and breaks pyannote checkpoint loading, which
  whisperx's aligner uses.
- `transformers<5`: transformers 5.x calls `torch.accelerator` (added in torch 2.6) at import time, so
  `Wav2Vec2ForCTC` cannot be imported under the pinned torch.
- `requires-python >=3.10,<3.13`, so uv does not resolve onto a Python that has no wheels for this
  torch range.
- `numpy<2` is kept from the original project; the reason was not recorded there.
- Warnings from pyannote/lightning about checkpoint version mismatches are expected noise from
  whisperx's pinned assets and are silenced at the top of the file; they are not bugs to chase.

### 7. Deviations from ADR 0001

The formatting rules of ADR 0001 apply: `lrc_fix.py` is formatted and linted with the repository's ruff
configuration (tabs, single quotes). It deviates in three ways, all because it is a stand-alone ML tool
and is not run by `webui.py`:

- Python 3.10-3.12 (`requires-python` in its own PEP 723 header), not >= 3.14, because the pinned
  torch range has no wheels for newer Pythons.
- It prints progress with `print()` and its own `argparse` output instead of `log.py`/`structlog`, and
  has no JSON-over-stdout mode.
- Its dependency set is far larger than any other script's (demucs, whisperx, librosa, torch); models
  are downloaded on first run to `~/.cache/huggingface` and `~/.cache/torch`.

### 8. Deliberate non-choices (do not reintroduce without discussion)

- **No LLM in the alignment path.** An earlier version asked a local Ollama model for line-to-timestamp
  JSON. Local models proved unreliable at precise positional and numeric reasoning over a long
  transcript (they lose track, guess, or lock onto the wrong occurrence of a repeated phrase). Matching
  against actual recognized words grounds every timestamp and has no hallucination risk.
- **No `LYRICS_ORIGINAL` backup tag.** An earlier version kept the pre-fix tag and always realigned from
  it, to stay idempotent against the tool's own buggy output. Once those bugs were fixed it became a
  liability: it silently discarded any manual edit made between runs.
- **No estimated-time copying.** Unmatched lines are never given a neighbour's timestamp (section 3).

---

## Consequences

### Positive
* **Timestamps are grounded in audio**: every matched time comes from a recognized word on the isolated
  vocal stem, snapped to a real onset.
* **Safe by default**: a weak or implausible alignment leaves the existing tag untouched.
* **Fast re-runs**: tag edits and gate tuning cost seconds per track instead of a minute.
* **No drift against `update_lyrics.py`**: shared formatting means neither tool rewrites the other's output.
* **Fully local**: no cloud API or key is needed.

### Negative / Trade-offs
* **Slow and heavy**: about a minute per track on CPU on the first pass, a large dependency set, and
  model downloads on first run. Unlike `align_lyrics.py`'s MLX path there is no Apple Silicon fast path.
* **Estimated times remain guesses** for lines the transcript cannot match; the gate only limits how many.
* **Pins must be maintained**: the torch, transformers and numpy ranges will need revisiting when
  whisperx moves forward; the symptom of drift is an import error at the transcription step.
* **Cache growth**: a few tens of KB per track in `~/.cache/lrc_fix`, never pruned automatically.
