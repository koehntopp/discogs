# lrc_fix

Sync lyrics to audio in FLAC files, locally.

Reads the `LYRICS` tag from a FLAC file — plain text or an existing
(possibly out-of-sync) LRC — and rewrites it with timestamps generated
straight from the audio. No cloud APIs, no LLM in the timing path: every
timestamp is grounded in an actual detected word and a real onset spike in
the waveform.

## How it works

1. **Isolate vocals** — [demucs](https://github.com/facebookresearch/demucs)
   separates the track into vocal/instrumental stems so instrumental
   sections never get fed to the speech recognizer (the #1 cause of
   hallucinated lyrics).
2. **Transcribe** — [whisperx](https://github.com/m-bain/whisperX)
   transcribes and force-aligns the isolated vocals, producing word-level
   timestamps.
3. **Align** — the correct lyric lines (from the tag) are matched against
   the ASR transcript with deterministic word-sequence matching
   ([`difflib`](https://docs.python.org/3/library/difflib.html)). Only runs
   of 2+ consecutive matched words are trusted, so a single coincidental
   word match can't lock in a bogus timestamp.
4. **Snap to onset** — each matched timestamp is pulled back to the nearest
   real vocal onset detected via
   [librosa](https://librosa.org/doc/latest/generated/librosa.onset.onset_detect.html),
   landing on the actual start of the word instead of somewhere in the
   middle of it.
5. **Write back** — the FLAC's `LYRICS` tag is rewritten with the new LRC
   content. Each run parses whatever the tag currently holds, so you can
   hand-edit it (fix a misheard word, add a line that repeats in the song
   but was only written once) and the edit takes effect next run. No backup
   is kept — if a run goes wrong, delete the tag and re-fetch lyrics (e.g.
   from [lrclib.net](https://lrclib.net)).
6. **Sanity-check outliers** — if alignment finds *zero* matches for every
   line (the given lyrics don't seem to be in the audio at all), that's run
   back through [silero-vad](https://github.com/snakers4/silero-vad) as a
   second opinion. No vocal activity detected either → the tag is probably
   mislabeled; a warning is printed and the tag is left untouched rather
   than writing an all-interpolated, meaningless LRC.

## Requirements

- macOS/Linux with Python and [`uv`](https://docs.astral.sh/uv/) installed.
- No manual dependency install needed — `lrc_fix.py` carries its
  dependencies as inline [PEP 723](https://peps.python.org/pep-0723/)
  metadata; `uv` resolves and caches them on first run.
- CPU works fine (slower); pass `--device cuda` if you have a GPU.

## Install

`lrc_fix.py` lives in this repository next to `lrc_format.py`, which it imports (the LRC header and
normalization logic it shares with `update_lyrics.py`), so run it from a checkout rather than copying the
single file:

```bash
git clone https://github.com/koehntopp/discogs.git && cd discogs
./lrc_fix.py --help
```

Design decisions: [ADR 0009](docs/adr/0009-lrc-fix-local-realignment.md).

## Usage

```bash
# single file
./lrc_fix.py song.flac

# every .flac under a directory, recursively - only plain-text/un-timed lyrics
./lrc_fix.py ~/Music/some_album/

# also reprocess files that already have LRC timestamps
./lrc_fix.py ~/Music/some_album/ --all

# preview without writing the tag
./lrc_fix.py song.flac --dry-run

# force language instead of relying on auto-detect
./lrc_fix.py song.flac --language en

# scan a directory for files with no LYRICS tag at all: VAD-tag real
# instrumentals, log the rest as needing lyrics fetched
./lrc_fix.py ~/Music/some_album/ --find-missing-lyrics
```

A file is skipped if it has no `LYRICS` tag, if the tag is empty after
stripping timestamps/header lines, or if it's just an instrumental
placeholder (`Instrumental`, `[Instrumental]`, etc.) — no need to run
demucs/whisperx when there's no lyric text to align.

When `path` is a directory, files are found recursively (including
subdirectories). By default, only files whose `LYRICS` tag is *not* already
LRC-timestamped are fully realigned — pass `--all` to reprocess
already-timestamped files too. Already-LRC files aren't just skipped,
though: their `[ar:]`/`[ti:]`/`[al:]`/`[length:]` header lines still get
checked and refreshed against the FLAC's own tags (a metadata-only pass,
no demucs/whisperx; `[re:]` is left alone here — see below), while the
existing timestamped body — including a
manually added marker like `[00:00.00](Spoken Intro)` — is left completely
untouched. Files with no usable lyrics (missing tag, empty, or an
instrumental placeholder) are excluded from the count regardless of `--all`,
so the number reported up front matches what will actually run. This
filtering doesn't apply when `path` is a single file: naming a file directly
always processes it. The tool logs `[i/N] <path>` as each file starts.

### Options

| Flag | Default | Description |
|---|---|---|
| `--whisper-model` | `medium` | whisperx/faster-whisper model size (`tiny`…`large-v3`) |
| `--language` | auto-detect | Force ASR language (ISO 639-1, e.g. `en`, `de`) |
| `--device` | `cpu` | `cpu` or `cuda` |
| `--compute-type` | `int8` | faster-whisper compute type |
| `--jobs` / `-j` | `min(4, cpu count)` | Parallel demucs jobs (each holds a model copy in memory) |
| `--dry-run` | off | Print the resulting LRC, don't write the tag |
| `--all` | off | Directory mode: also reprocess already-LRC-timestamped files |
| `--no-isolate-vocals` | off | Skip demucs separation, transcribe the full mix |
| `--no-snap-onsets` | off | Skip onset detection/snapping |
| `--no-vocal-check` | off | Skip the VAD fallback when alignment finds zero matches |
| `--min-match` | `0.6` | Minimum share of lyric lines (those with at least one word) that must match the transcript; a weaker alignment is skipped and the tag left unchanged |
| `--min-sung` | `0.5` | Minimum share of the lyric's consecutive word pairs that must occur in the transcript (order independent); a text that is mostly not sung is skipped and the tag left unchanged. `0` disables |
| `--fallback-language` | `en` | If whisperx has no alignment model for the language it detected, transcribe again as this language (`none` = fail as before) |
| `--no-quality-gate` | off | Write the alignment even when too few lines matched or the result piles lines onto one timestamp |
| `--find-missing-lyrics` | off | Scan for files with no `LYRICS` tag; VAD-tag instrumentals, log the rest |
| `--dump-words` | off | Print the raw ASR word/timestamp transcript (debugging) |
| `--cache-dir` | `~/.cache/lrc_fix` | Where demucs/whisperx results are cached |
| `--no-cache` | off | Neither read nor write the cache |
| `--refresh-cache` | off | Ignore existing cache entries and rewrite them |

## ASR cache

demucs and whisperx take about a minute per track on CPU, and their output depends only on the audio, not on the
lyric text. Each processed track therefore stores its word timestamps (and, once computed, the vocal onsets) in
`~/.cache/lrc_fix/<discogs_id>_<disc>_<track>.json`, so re-running after you edit the `LYRICS` tag, change
`--min-match` or use `--no-quality-gate` skips demucs and whisperx (`cache hit` in the output). Tracks the quality
gate rejected are cached too, since they stay un-synced and would otherwise be redone on every run.

- Files without a numeric `DISCOGS_RELEASE_ID` or without a `TRACKNUMBER` are never cached. `disc` defaults to 1;
  `7/12` and `07` both mean track 7.
- An entry is only used if the whisper model, `--language`, `--compute-type`, vocal isolation on/off, and the FLAC's
  sample rate and total sample count all match the current run; anything else is a miss. (The sample count, not the
  modification time, so tag edits do not invalidate it but a replaced rip does.) A missing or corrupt file is a miss.
- Onsets are cached once computed. An entry without them (the track was gated out earlier, or `--no-snap-onsets` was
  used) costs one demucs pass when they are first needed; the VAD fallback (no line matched) also needs the audio.
- `--dry-run` still writes the cache; it only protects the `LYRICS` tag.

Why these keys and validity checks: [ADR 0009](docs/adr/0009-lrc-fix-local-realignment.md) section 4.

## Quality gate

Lines the transcript cannot match get an estimated time: between two matched lines they are
interpolated; before the first and after the last matched line they are spread at the song's typical
seconds-per-line (at most 8 s apart, kept inside the track), so every line has its own, increasing
timestamp. (They used to copy the nearest matched line's time, which stacked a failed head or tail
onto one moment.) Estimated times are still guesses. A weak alignment (and, with junk in the source
text, a harmless plain tag replaced by misleading timestamps) is caught by two checks that leave the
tag untouched with a `skip:` message instead: fewer than `--min-match` of the lyric lines matched, fewer than `--min-sung` of the
lyric's word pairs occur in the transcript (single common words can match enough lines for a song that is not sung, such as a
dialect or foreign-language track), or the result would put 5 or more lines (and at least 20% of them) on one timestamp.
`--no-quality-gate` bypasses all three.
`lrc_count.py --suspects` lists existing tags that show these signs. Rationale and thresholds:
[ADR 0009](docs/adr/0009-lrc-fix-local-realignment.md) section 3.

## Characters

Lyric text is normalized with the shared `lrc_format.normalize_text` (curly quotes, dashes, ellipsis and odd spaces become ASCII; see ADR 0002 section 6), both in the written LRC and when matching lines against the transcript, so a curly apostrophe no longer splits `don’t` into two words.

## Notes

- First run downloads whisperx/demucs model weights from Hugging Face Hub,
  and silero-vad (only used for the VAD fallback / `--find-missing-lyrics`)
  from GitHub via `torch.hub` — all cached (`~/.cache/torch`,
  `~/.cache/huggingface`) so later runs are fast to start.
- whisper sometimes misdetects the language of Gaelic, Welsh-sounding or dialect singing (as Latin or Welsh), and whisperx has
  no alignment model for some languages. Instead of failing, `lrc_fix` then transcribes the track again as
  `--fallback-language` (default English); the words are rougher for such songs, and the `--min-sung` check refuses a result
  whose text is not heard.
- Dependency pins are load-bearing: `torch<2.6` (2.6 flips the `torch.load`
  `weights_only` default and breaks pyannote checkpoint loading) and
  `transformers<5` (5.x calls `torch.accelerator`, added in torch 2.6, so
  importing `Wav2Vec2ForCTC` fails under the pinned torch with "Could not
  import module 'Wav2Vec2ForCTC'").
- `--whisper-model large*` is rarely worth it here: since the correct
  lyrics text is already known, the alignment step only needs *usable*
  ASR output to match against, not maximally accurate transcription.
- Standard LRC header lines (`[ar:...]`, `[ti:...]`, `[al:...]`) in the tag
  are preserved as-is and never timestamped. Any of the three that's
  missing gets filled in from the file's own tags (when set): `[ar:]` from `ALBUMARTIST`, falling back to
  `ARTIST` only when it is empty (the same rule `update_lyrics.py` uses), `[ti:]` from `TITLE`, `[al:]`
  from `ALBUM`, `[length:]` from the audio duration.
- `[re:https://github.com/koehntopp/lrc_fix]` (the LRC spec's "creator" tag)
  only gets (re)stamped when a run actually changes lyric content — a
  realignment, a completed instrumental marker, etc. A metadata-only refresh
  (correcting `[ar:]`/`[ti:]`/`[al:]`/`[length:]`) leaves any existing
  `[re:]` line exactly as it was. This also keeps files idempotent: a file
  whose metadata and lyrics are both already correct compares equal to its
  prior content and is left untouched entirely, rather than a stale `[re:]`
  value alone forcing a rewrite on every run.

## License

Part of the discogs repository; this repository does not contain a license file yet.
