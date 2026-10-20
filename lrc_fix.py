#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#     "mutagen",
#     "whisperx",
#     "demucs",
#     "librosa",
#     "torch>=2.4,<2.6",
#     "torchaudio>=2.4,<2.6",
#     "numpy<2",
#     "transformers<5",
# ]
# ///
"""lrc_fix.py

Read the LYRICS tag from FLAC files (plain text or already-LRC-timestamped).
First isolate vocals with demucs (source separation) so instrumental
sections can't get mistaken for speech, then use whisperx to get real
word-level timestamps from the isolated vocals, then align the correct
lyric lines against that ASR transcript with deterministic word sequence
matching (difflib) to produce a synced LRC. The LYRICS tag is rewritten in
place, parsed fresh from its current content each run - so manual edits to
the tag (fixing a misheard word, adding a line that repeats but was only
written once) take effect on the next run. No backup is kept; if a run goes
wrong, delete the tag and re-fetch lyrics (e.g. from lrclib.net) instead.

Alignment is intentionally not LLM-based: local models are unreliable at
precise positional/numeric reasoning over a long transcript (they can lose
track, guess, or lock onto the wrong occurrence of a repeated phrase).
Sequence alignment grounds every timestamp in an actual matched ASR word.
If alignment finds zero matches at all, that's checked against silero-vad
as a second opinion before assuming the tag is just mislabeled.

The demucs/whisperx output (word timestamps, vocal onsets) depends only on
the audio, so it is cached per track in ~/.cache/lrc_fix/ (see --cache-dir,
--no-cache, --refresh-cache): re-running after editing the tag or changing
--min-match skips the slow part. Lyric text is never cached.

--find-missing-lyrics is a separate mode: scans for files with no LYRICS
tag at all and uses VAD alone (no transcription needed) to tag genuine
instrumentals automatically, while logging the rest as needing lyrics
fetched from elsewhere.

Usage:
    python lrc_fix.py song.flac
    python lrc_fix.py ~/Music/some_album/
    python lrc_fix.py ~/Music/some_album/ --whisper-model medium --dry-run
    python lrc_fix.py ~/Music/some_album/ --find-missing-lyrics

Requires: mutagen, whisperx, demucs (silero-vad is fetched via torch.hub)
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import tempfile
import warnings
from itertools import pairwise
from pathlib import Path

# Silence harmless version-mismatch / deprecation noise from whisperx's deps
# (torch.load weights_only default, pyannote/torch checkpoint version checks).
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)
logging.getLogger('pytorch_lightning').setLevel(logging.ERROR)
logging.getLogger('lightning_fabric').setLevel(logging.ERROR)
logging.getLogger('speechbrain').setLevel(logging.ERROR)

from mutagen.flac import FLAC

from lrc_format import ID_TAG_LINE as LRC_ID_TAG_RE
from lrc_format import (
	build_instrumental_marker,
	capitalize_line,
	lrc_suspect_reasons,
	normalize_text,
	refresh_headers,
	resolve_artist,
)
from lrc_format import is_bare_instrumental_placeholder as is_instrumental

DEFAULT_LINE_GAP = 4.0  # seconds per line when fewer than two lines matched
TRAILING_MARGIN = 0.5  # keep spread tail lines this far before the end of the track
FUZZY_MIN_LENGTH = 4  # words shorter than this are only matched exactly
FUZZY_WORD_CUTOFF = 0.8  # difflib similarity at which a misheard word counts as the lyric word
LINE_MIN_SHARE = 0.6  # share of a line's words a transcript stretch must hold to be a candidate
MAX_SPREAD_STEP = 8.0  # never spread head/tail lines further apart than this, in seconds

LRC_TIMESTAMP_RE = re.compile(r'^\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]\s*')


def find_flac_files(path: Path) -> list[Path]:
	if path.is_file():
		return [path] if path.suffix.lower() == '.flac' else []
	return sorted(path.rglob('*.flac'))


def read_lyrics_tag(flac: FLAC) -> str | None:
	values = flac.get('LYRICS')
	if not values:
		return None
	return '\n'.join(values)


def is_lrc(raw: str) -> bool:
	"""True if any line already carries an [mm:ss.xx]-style timestamp."""
	return any(LRC_TIMESTAMP_RE.match(line.strip()) for line in raw.splitlines())


def strip_lyric_lines(raw: str) -> tuple[list[str], list[str]]:
	"""Split raw LYRICS content into (id_tags, lyric_lines).

	id_tags are standard LRC header lines like [ar:...]/[ti:...]/[al:...] and
	are passed through unchanged, never timestamped. Any existing per-line
	timestamps on lyric lines are stripped so they get realigned from audio.
	"""
	id_tags = []
	lines = []
	for line in raw.splitlines():
		line = line.strip()
		if not line:
			continue
		# strip any (possibly stacked, from a prior buggy run) leading
		# timestamp(s) before classifying the line
		while True:
			stripped = LRC_TIMESTAMP_RE.sub('', line, count=1).strip()
			if stripped == line:
				break
			line = stripped
		if not line:
			continue
		if LRC_ID_TAG_RE.match(line):
			id_tags.append(line)
		else:
			lines.append(line)
	return id_tags, lines


def split_id_tags(raw: str) -> tuple[list[str], list[str]]:
	"""Like strip_lyric_lines, but never touches timestamps on body lines.

	Used for the metadata-only pass on files that are skipped for
	realignment because they're already LRC-timestamped (e.g. a manually
	added `[00:00.00](Spoken Intro)` marker) - the body must come back
	byte-for-byte identical, only the id-tag header lines get refreshed.
	"""
	id_tags = []
	body = []
	for line in raw.splitlines():
		line = line.strip()
		if not line:
			continue
		if LRC_ID_TAG_RE.match(line):
			id_tags.append(line)
		else:
			body.append(line)
	return id_tags, body


# LRC spec's [re:] tag identifies the player/editor that created the file.
# Only stamped when a run actually changes lyric content - see
# stamp_creator_tag / _strip_metadata_lines - never for a metadata-only
# refresh, so it isn't rewritten (and doesn't force every file in a
# directory to fail the idempotency check) just because ar/ti/al/length
# needed correcting.
CREATOR_TAG = 'https://github.com/koehntopp/lrc_fix'

# Keys ensure_id_tags manages directly (via lrc_format.refresh_headers), plus
# "re" (handled separately by stamp_creator_tag/_strip_metadata_lines rather
# than here).
_METADATA_KEYS = {'ar', 'ti', 'al', 'length', 're'}


def _flac_value(flac: FLAC, key: str) -> str:
	values = flac.get(key)
	return values[0] if values and values[0] else ''


def ensure_id_tags(id_tags: list[str], flac: FLAC) -> list[str]:
	"""Refresh [ar:]/[ti:]/[al:]/[length:] header lines from the FLAC's own
	tags/audio duration, via lrc_format.refresh_headers - shared with
	discogs/update_lyrics.py so that tool never needs to re-touch a file
	lrc_fix.py just wrote. [ar:] sources ALBUMARTIST, falling back to ARTIST
	only when ALBUMARTIST is empty (lrc_format.resolve_artist) - a track's own
	ARTIST can carry rip-specific billing lrclib.net's artist index won't
	match. Every other pre-existing id tag line - including [re:], [by:...],
	etc. - passes through unchanged, in original order; [re:] is handled
	separately, by stamp_creator_tag, and only when a run actually changes
	lyric content (see CLAUDE.md).
	"""
	artist = resolve_artist(_flac_value(flac, 'ALBUMARTIST'), _flac_value(flac, 'ARTIST'))
	title = _flac_value(flac, 'TITLE')
	album = _flac_value(flac, 'ALBUM')
	length = getattr(flac.info, 'length', None) or 0.0
	return refresh_headers(id_tags, artist, title, album, length)


_ID_TAG_KEY_RE = re.compile(r'^\[([a-zA-Z]+):')
_RE_TAG_KEY_RE = re.compile(r'^\[re:', re.IGNORECASE)


def stamp_creator_tag(id_tags: list[str]) -> list[str]:
	"""Replace any existing [re:] line with the canonical CREATOR_TAG one.

	Only call this when the run actually changed lyric content - see
	_strip_metadata_lines and its use at each write site. Calling it
	unconditionally would make [re:] flip on every metadata-only refresh,
	which is exactly the churn this split is meant to avoid.
	"""
	filtered = [line for line in id_tags if not _RE_TAG_KEY_RE.match(line)]
	return [*filtered, f'[re:{CREATOR_TAG}]']


def _strip_metadata_lines(text: str) -> list[str]:
	"""Lines that aren't ar/ti/al/length/re - i.e. the actual lyric body,
	plus any other id tags like [la:]/[instrumental:]/[by:...].

	Comparing this before/after is how each write site decides whether a
	run actually changed lyric content (and so [re:] should be (re)stamped)
	versus just refreshed metadata (and so [re:] should be left alone).
	"""
	result = []
	for line in text.splitlines():
		line = line.strip()
		if not line:
			continue
		m = _ID_TAG_KEY_RE.match(line)
		key = m.group(1).lower() if m else None
		if key in _METADATA_KEYS:
			continue
		result.append(line)
	return result


def separate_vocals(audio_path: Path, device: str, jobs: int, work_dir: Path) -> Path:
	"""Run demucs source separation and return the path to the vocals-only stem.

	Isolating vocals before transcription keeps instrumental sections from
	being mistaken for speech, which is whisper's main hallucination trigger.
	`jobs` parallelizes demucs's own chunked processing across CPU cores -
	each job holds a copy of the model in memory, so it's capped by default
	rather than using every core unconditionally.
	"""
	cmd = [
		sys.executable,
		'-m',
		'demucs',
		'--two-stems',
		'vocals',
		'-d',
		device,
		'-j',
		str(jobs),
		'-o',
		str(work_dir),
		str(audio_path),
	]
	proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
	if proc.returncode != 0:
		raise RuntimeError(f'demucs failed:\n{proc.stderr}')

	vocals_path = next(work_dir.rglob('vocals.wav'), None)
	if vocals_path is None:
		raise RuntimeError(f'demucs did not produce a vocals.wav under {work_dir}')
	return vocals_path


def has_speech(audio_path: Path) -> bool:
	"""True if silero-vad finds any speech activity at all in the audio.

	Used as a fallback check, not a primary signal: VAD is trained on
	speech, not singing-over-instrumentation, so it can miss quiet/heavily
	processed vocals. Only meaningful as a second opinion when something
	else (alignment finding zero matches, a missing LYRICS tag) already
	suggests the track might be instrumental.
	"""
	import torch

	torch.set_num_threads(1)
	model, utils = torch.hub.load(
		repo_or_dir='snakers4/silero-vad', model='silero_vad', trust_repo=True
	)
	get_speech_timestamps, _, read_audio, *_ = utils
	wav = read_audio(str(audio_path), sampling_rate=16000)
	timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
	return len(timestamps) > 0


LANGUAGE_TAG = (
	'LYRICS_LANGUAGE'  # written by fixtags.py from MusicBrainz, ISO 639-3, one value per language
)
# ISO 639-3 (the codes MusicBrainz uses) -> whisper's language code, for every language whisper
# knows. Generated from faster_whisper.tokenizer._LANGUAGE_CODES and pycountry; the repository's
# tests regenerate it and compare.
ISO3_TO_WHISPER = {
	'afr': 'af',
	'amh': 'am',
	'ara': 'ar',
	'asm': 'as',
	'aze': 'az',
	'bak': 'ba',
	'bel': 'be',
	'ben': 'bn',
	'bod': 'bo',
	'bos': 'bs',
	'bre': 'br',
	'bul': 'bg',
	'cat': 'ca',
	'ces': 'cs',
	'cym': 'cy',
	'dan': 'da',
	'deu': 'de',
	'ell': 'el',
	'eng': 'en',
	'est': 'et',
	'eus': 'eu',
	'fao': 'fo',
	'fas': 'fa',
	'fin': 'fi',
	'fra': 'fr',
	'glg': 'gl',
	'guj': 'gu',
	'hat': 'ht',
	'hau': 'ha',
	'haw': 'haw',
	'heb': 'he',
	'hin': 'hi',
	'hrv': 'hr',
	'hun': 'hu',
	'hye': 'hy',
	'ind': 'id',
	'isl': 'is',
	'ita': 'it',
	'jav': 'jw',
	'jpn': 'ja',
	'kan': 'kn',
	'kat': 'ka',
	'kaz': 'kk',
	'khm': 'km',
	'kor': 'ko',
	'lao': 'lo',
	'lat': 'la',
	'lav': 'lv',
	'lin': 'ln',
	'lit': 'lt',
	'ltz': 'lb',
	'mal': 'ml',
	'mar': 'mr',
	'mkd': 'mk',
	'mlg': 'mg',
	'mlt': 'mt',
	'mon': 'mn',
	'mri': 'mi',
	'msa': 'ms',
	'mya': 'my',
	'nep': 'ne',
	'nld': 'nl',
	'nno': 'nn',
	'nor': 'no',
	'oci': 'oc',
	'pan': 'pa',
	'pol': 'pl',
	'por': 'pt',
	'pus': 'ps',
	'ron': 'ro',
	'rus': 'ru',
	'san': 'sa',
	'sin': 'si',
	'slk': 'sk',
	'slv': 'sl',
	'sna': 'sn',
	'snd': 'sd',
	'som': 'so',
	'spa': 'es',
	'sqi': 'sq',
	'srp': 'sr',
	'sun': 'su',
	'swa': 'sw',
	'swe': 'sv',
	'tam': 'ta',
	'tat': 'tt',
	'tel': 'te',
	'tgk': 'tg',
	'tgl': 'tl',
	'tha': 'th',
	'tuk': 'tk',
	'tur': 'tr',
	'ukr': 'uk',
	'urd': 'ur',
	'uzb': 'uz',
	'vie': 'vi',
	'yid': 'yi',
	'yor': 'yo',
	'yue': 'yue',
	'zho': 'zh',
}
ISO3_ALIASES = {'nob': 'no', 'cmn': 'zh'}  # MusicBrainz spellings of Norwegian Bokmal and Mandarin
# Languages whisper does not know that are close enough to a supported one to transcribe as it.
LANGUAGE_FALLBACKS = {'ksh': 'de', 'gsw': 'de', 'bar': 'de', 'nds': 'de', 'sco': 'en'}
NO_ALIGN_MODEL_HINTS = ('No default align-model', 'could not be found')


def align_languages() -> set[str] | None:
	"""Languages whisperx has an alignment model for (it needs one for word times), or None if
	whisperx is not importable and this cannot be told."""
	try:
		from whisperx import alignment
	except ImportError:
		return None
	return set(alignment.DEFAULT_ALIGN_MODELS_TORCH) | set(alignment.DEFAULT_ALIGN_MODELS_HF)


def track_language(flac: FLAC, args: argparse.Namespace) -> tuple[str | None, str | None]:
	"""(language to force, reason to skip the track); (None, None) means auto-detect.

	--language always wins. Otherwise the LYRICS_LANGUAGE tag (sung language per track, from
	MusicBrainz) decides: one language that can be transcribed and aligned is forced, which avoids
	whisper's misdetections (Gaelic or dialect singing as Latin or Welsh); `zxx` is an instrumental;
	a language without a whisper model or without an alignment model cannot be done, so the track
	is skipped before any demucs/whisper work; several languages or `mul`/`und` auto-detect.
	"""
	if args.language:
		return args.language, None
	if getattr(args, 'ignore_language_tag', False):
		return None, None
	values = [str(v).strip().lower() for v in (flac.get(LANGUAGE_TAG) or []) if str(v).strip()]
	if not values:
		return None, None
	if values == ['zxx']:
		return None, 'MusicBrainz marks the track as instrumental (zxx)'
	if len(set(values)) > 1 or values[0] in ('mul', 'und', 'mis'):
		return None, None
	code = values[0]
	whisper = ISO3_TO_WHISPER.get(code) or ISO3_ALIASES.get(code) or LANGUAGE_FALLBACKS.get(code)
	if whisper is None:
		return None, f'language {code} is not supported by whisper'
	aligned = align_languages()
	if aligned is not None and whisper not in aligned:
		return None, f'no alignment model for language {whisper} ({code})'
	return whisper, None


def transcribe_words(
	audio_path: Path,
	whisper_model: str,
	device: str,
	compute_type: str,
	language: str | None,
	fallback_language: str | None = None,
) -> tuple[list[dict], str]:
	"""Word start times of the audio and the language that was used. If whisperx has no alignment model for the language it
	detected (it misdetects Gaelic or dialect singing as Latin or Welsh, and a few models cannot be
	downloaded), the audio is transcribed again as `fallback_language` instead of failing."""
	import whisperx

	# condition_on_previous_text=False avoids whisper's known failure mode of
	# feeding a hallucinated guess (e.g. from an instrumental intro) back in
	# as context and cascading it into further hallucinated text.
	asr_options = {'condition_on_previous_text': False}
	model = whisperx.load_model(
		whisper_model, device, compute_type=compute_type, language=language, asr_options=asr_options
	)
	audio = whisperx.load_audio(str(audio_path))
	result = model.transcribe(audio, language=language, print_progress=True)

	try:
		align_model, metadata = whisperx.load_align_model(
			language_code=result['language'], device=device
		)
	except Exception as exc:  # whisperx raises plain errors for a missing model
		if (
			not fallback_language
			or result['language'] == fallback_language
			or not any(hint in str(exc) for hint in NO_ALIGN_MODEL_HINTS)
		):
			raise
		print(
			f'   no alignment model for language {result["language"]}; '
			f'transcribing again as {fallback_language}'
		)
		result = model.transcribe(audio, language=fallback_language, print_progress=True)
		align_model, metadata = whisperx.load_align_model(
			language_code=result['language'], device=device
		)
	language_used = result['language']
	result = whisperx.align(
		result['segments'], align_model, metadata, audio, device, print_progress=True
	)

	words = []
	for segment in result['segments']:
		for w in segment.get('words', []):
			start = w.get('start')
			if start is None:
				continue
			words.append({'w': w['word'], 't': round(start, 2)})
	return words, language_used


# [^\W_]+ is "word characters minus underscore" - Unicode letters/digits from
# any script (Cyrillic, Greek, CJK, Hebrew, accented Latin, ...), not just
# ASCII a-z0-9. An internal apostrophe is allowed so contractions ("don't")
# and similar (French "l'amour") tokenize as one word instead of splitting.
_WORD_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)


def _tokenize(text: str) -> list[str]:
	# normalize_text first: a curly apostrophe must not split "don’t" into "don" + "t", while the
	# transcript's "don't" stays one word.
	return _WORD_RE.findall(normalize_text(text).lower())


def match_blocks(lyric_lines: list[str], words: list[dict]) -> list[float | None]:
	"""One difflib pass over the whole text: each lyric line's start time from a matched ASR word.

	Tokenizes both the ASR transcript and the lyric lines to plain lowercase
	words, then runs difflib's sequence matcher between them. A lone matched
	word is easy to hit by chance (e.g. a hallucinated phrase over an
	instrumental intro sharing a common word like "you" with some lyric
	line), so we only trust matching runs of 2+ consecutive words; lines that
	only ever get a single-word match fall back to that. Lines with no match
	at all come back as None (left for the caller to interpolate).
	"""
	asr_tokens: list[str] = []
	asr_times: list[float] = []
	for w in words:
		toks = _tokenize(w['w'])
		if not toks:
			continue
		asr_tokens.append(toks[0])
		asr_times.append(w['t'])

	lyric_tokens: list[str] = []
	lyric_owner: list[int] = []
	for i, line in enumerate(lyric_lines):
		for tok in _tokenize(line):
			lyric_tokens.append(tok)
			lyric_owner.append(i)

	strong: list[float | None] = [None] * len(lyric_lines)
	weak: list[float | None] = [None] * len(lyric_lines)
	if asr_tokens and lyric_tokens:
		matcher = difflib.SequenceMatcher(a=asr_tokens, b=lyric_tokens, autojunk=False)
		for block in matcher.get_matching_blocks():
			target = strong if block.size >= 2 else weak
			for k in range(block.size):
				a_idx = block.a + k
				b_idx = block.b + k
				line_idx = lyric_owner[b_idx]
				t = asr_times[a_idx]
				if target[line_idx] is None or t < target[line_idx]:
					target[line_idx] = t

	return [s if s is not None else weak[i] for i, s in enumerate(strong)]


def _asr_tokens(words: list[dict]) -> tuple[list[str], list[float]]:
	tokens: list[str] = []
	times: list[float] = []
	for w in words:
		toks = _tokenize(w['w'])
		if toks:
			tokens.append(toks[0])
			times.append(w['t'])
	return tokens, times


def match_per_line(lyric_lines: list[str], words: list[dict]) -> list[float | None]:
	"""Place each lyric line at the best matching stretch of the transcript, in order.

	match_blocks takes one difflib pass over the whole text, which locks onto the longest common
	block and loses lines when a chorus is repeated, the transcript has sections the text lacks, or
	the order differs a little. Here every line looks for its own candidates (a stretch of the
	transcript that holds most of its words in order), and a dynamic programme then picks one
	candidate per line, or none, so that the total match weight is highest and the chosen stretches
	never go backwards in time. A line repeated in the text takes successive occurrences in the
	song; transcript sections that no line claims are simply skipped.
	"""
	asr, asr_times = _asr_tokens(words)
	lines = [_tokenize(line) for line in lyric_lines]
	times: list[float | None] = [None] * len(lines)
	if not asr or not any(lines):
		return times
	vocabulary = sorted({tok for tokens in lines for tok in tokens})
	spelled: dict[str, str] = {}  # a misheard word is read as the lyric word it nearly is
	for tok in set(asr):
		if tok not in vocabulary and len(tok) >= FUZZY_MIN_LENGTH:
			close = difflib.get_close_matches(tok, vocabulary, 1, FUZZY_WORD_CUTOFF)
			if close:
				spelled[tok] = close[0]
	asr = [spelled.get(tok, tok) for tok in asr]
	positions: dict[str, list[int]] = {}
	for j, tok in enumerate(asr):
		positions.setdefault(tok, []).append(j)

	# candidates[i] = (first asr index, last asr index, weight)
	candidates: list[list[tuple[int, int, float]]] = []
	for tokens in lines:
		found: dict[int, tuple[int, float]] = {}
		k = len(tokens)
		if k:
			starts = sorted({j for tok in set(tokens) for j in positions.get(tok, [])})
			for j in starts:
				window = asr[j : j + k + 2]
				blocks = difflib.SequenceMatcher(
					a=window, b=tokens, autojunk=False
				).get_matching_blocks()
				if not blocks or blocks[0].a != 0:
					continue  # a stretch counts from its first matched word
				matched = sum(b.size for b in blocks)
				last = j + max(b.a + b.size for b in blocks if b.size) - 1
				if matched >= 2 and matched / k >= LINE_MIN_SHARE:
					weight = matched / k
				elif k <= 2 and matched == k:
					weight = 0.5 * matched / k  # a short line is easy to hit by chance
				else:
					continue
				if j not in found or weight > found[j][1]:
					found[j] = (last, weight)
		candidates.append([(j, last, w) for j, (last, w) in sorted(found.items())])

	# best[i][c] = (total weight, previous state) for choosing candidate c on line i
	states: list[tuple[int, int, float, int | None]] = []  # (line, cand idx, total, prev state)
	for i, cands in enumerate(candidates):
		new_states = []
		for c, (first, last, weight) in enumerate(cands):
			best_prev, best_total = None, 0.0
			for s, (_, _, total, _) in enumerate(states):
				prev_last = candidates[states[s][0]][states[s][1]][1]
				if prev_last < first and total > best_total:
					best_prev, best_total = s, total
			new_states.append((i, c, best_total + weight, best_prev))
		states.extend(new_states)
	if not states:
		return times
	cur: int | None = max(range(len(states)), key=lambda s: (states[s][2], -s))
	while cur is not None:
		i, c, _, prev = states[cur]
		times[i] = asr_times[candidates[i][c][0]]
		cur = prev
	return times


def match_line_times(lyric_lines: list[str], words: list[dict]) -> list[float | None]:
	"""Each lyric line's start time from an actual matched ASR word, None where nothing matched.

	Runs both matchers (match_per_line and the older whole-text match_blocks) and keeps the result
	that places more lines, the older one on a tie, so the redesign can only add matches.
	"""
	blocks = match_blocks(lyric_lines, words)
	per_line = match_per_line(lyric_lines, words)
	if sum(t is not None for t in per_line) > sum(t is not None for t in blocks):
		return per_line
	return blocks


def sung_ratio(lyric_lines: list[str], words: list[dict]) -> float | None:
	"""Share of the lyric's consecutive word pairs that occur anywhere in the transcript, or None
	if either side has fewer than two words.

	Unlike the in-order line match this ignores order and structure, so repeated sections, a
	shuffled line order or backing vocals ("ooh") do not hide that the text is sung. It is what
	tells a song whose words are heard from one that only shares a few common words with the
	transcript (a foreign or dialect song, or the wrong lyrics).
	"""
	lyric = [tok for line in lyric_lines for tok in _tokenize(line)]
	heard = []
	for w in words:
		toks = _tokenize(w['w'])
		if toks:
			heard.append(toks[0])
	if len(lyric) < 2 or len(heard) < 2:
		return None
	pairs = set(pairwise(heard))
	lyric_pairs = list(pairwise(lyric))
	return sum(p in pairs for p in lyric_pairs) / len(lyric_pairs)


def alignment_rejection(
	lyric_lines: list[str],
	raw_times: list[float | None],
	min_match: float,
	words: list[dict] | None = None,
	min_sung: float = 0.0,
) -> str | None:
	"""Why this alignment is too weak to write, or None if it is good enough.

	Unmatched lines later get an estimated time (_fill_and_clamp), so a mostly-unmatched
	alignment would replace a harmless tag with mostly guessed timestamps. Lines without any word
	token at all (a lone "♪" or "***") are not counted, so decoration in the source text cannot
	sink an otherwise good alignment. With `words` and `min_sung` it also refuses a text whose word
	pairs are mostly not in the transcript: single common words can match enough lines to pass the
	line check although the song is not what the text says.
	"""
	counted = [t for line, t in zip(lyric_lines, raw_times) if _tokenize(line)]
	if not counted:
		return None
	matched = sum(t is not None for t in counted)
	if matched / len(counted) < min_match:
		return (
			f'only {matched} of {len(counted)} lines matched '
			f'({matched / len(counted):.0%}, minimum {min_match:.0%})'
		)
	if words is not None and min_sung > 0:
		ratio = sung_ratio(lyric_lines, words)
		if ratio is not None and ratio < min_sung:
			return (
				f"only {ratio:.0%} of the lyric's word pairs are in the transcript "
				f'(minimum {min_sung:.0%})'
			)
	return None


def detect_onsets(audio_path: Path) -> list[float]:
	"""Detect vocal onset times (seconds) in an audio file via librosa.

	backtrack=True walks each detected onset back to the nearest preceding
	local energy minimum, i.e. the actual start of the attack rather than
	its peak - what we want a lyric line's timestamp to land on.
	"""
	import librosa

	y, sr = librosa.load(str(audio_path), sr=None, mono=True)
	onsets = librosa.onset.onset_detect(y=y, sr=sr, units='time', backtrack=True)
	return sorted(float(t) for t in onsets)


def snap_to_onsets(
	times: list[float | None],
	onsets: list[float],
	back_window: float = 0.7,
	fwd_window: float = 0.2,
) -> None:
	"""Snap each known (non-None) time to the nearest real onset just at/before it.

	Modifies `times` in place. Falls back to the nearest onset slightly after
	the estimate if none is found within the backward window, and leaves the
	estimate untouched if no onset is close enough either way.
	"""
	if not onsets:
		return
	for i, t in enumerate(times):
		if t is None:
			continue
		candidates = [o for o in onsets if t - back_window <= o <= t + fwd_window]
		if not candidates:
			continue
		before = [o for o in candidates if o <= t]
		times[i] = max(before) if before else min(candidates)


def finalize_times(
	times: list[float | None], onsets: list[float] | None = None, length: float | None = None
) -> list[float]:
	times = list(times)
	if onsets:
		snap_to_onsets(times, onsets)
	_fill_and_clamp(times, length)
	return times  # type: ignore[return-value]


def _fill_and_clamp(times: list[float | None], length: float | None = None) -> None:
	"""Give every unmatched line (None) a distinct, increasing time, in place.

	Matched lines are the anchors. One that is not later than the previous anchor (two lines
	snapped onto one onset, or a matcher that went backwards) is treated as unmatched, so the
	anchors strictly increase. Unmatched lines between anchors are interpolated; lines before the
	first anchor and after the last one are spread at the song's typical seconds-per-line instead
	of all copying the neighbouring anchor's time, which used to stack a failed head or tail onto
	one timestamp. Everything ends strictly increasing at the 0.01 s resolution LRC can express.
	"""
	n = len(times)
	anchors: list[int] = []
	prev = None
	for i, t in enumerate(times):
		if t is None:
			continue
		if prev is not None and t <= prev:
			times[i] = None
			continue
		anchors.append(i)
		prev = t
	if not anchors:
		for i in range(n):
			times[i] = 0.0
		return

	per_line = [(times[b] - times[a]) / (b - a) for a, b in pairwise(anchors)]
	gap = min(statistics.median(per_line) if per_line else DEFAULT_LINE_GAP, MAX_SPREAD_STEP)

	n_lead = anchors[0]
	if n_lead:
		first = times[anchors[0]]
		step = min(gap, first / (n_lead + 1))
		for i in range(n_lead):
			times[i] = first - (n_lead - i) * step
	for a, b in pairwise(anchors):
		if b - a > 1:
			t0, t1 = times[a], times[b]
			for i in range(a + 1, b):
				frac = (i - a) / (b - a)
				times[i] = t0 + frac * (t1 - t0)
	n_trail = n - 1 - anchors[-1]
	if n_trail:
		last_anchor = times[anchors[-1]]
		if length is not None and length > last_anchor:
			room = max(length - last_anchor - TRAILING_MARGIN, 0.0)
			step = min(gap, room / (n_trail + 1))
		else:
			step = gap
		for k in range(1, n_trail + 1):
			times[anchors[-1] + k] = last_anchor + k * step

	last_cs = None
	for i, t in enumerate(times):
		cs = round(t * 100)
		if last_cs is not None and cs <= last_cs:
			cs = last_cs + 1
		times[i] = cs / 100
		last_cs = cs


def format_lrc_timestamp(seconds: float) -> str:
	minutes, centis = divmod(round(seconds * 100), 6000)  # round first: 59.996 must not print 60.00
	return f'[{minutes:02d}:{centis / 100:05.2f}]'


def build_lrc(id_tags: list[str], lyric_lines: list[str], times: list[float]) -> str:
	timed = (
		f'{format_lrc_timestamp(t)}{capitalize_line(normalize_text(line))}'
		for line, t in zip(lyric_lines, times)
	)
	return '\n'.join([*id_tags, *timed])


def build_instrumental_lrc(id_tags: list[str]) -> str:
	"""Canonical instrumental marker, via lrc_format.build_instrumental_marker
	(shared with discogs/update_lyrics.py). Strips any pre-existing
	la:/instrumental: lines from id_tags first, so this is idempotent rather
	than duplicating the sentinel when called on a file that's already
	canonically marked, and preserves any other header line (e.g. [re:])
	already in id_tags.
	"""
	return build_instrumental_marker(id_tags)


def write_lyrics_tag(flac: FLAC, new_lrc: str, dry_run: bool) -> None:
	print(new_lrc)
	if dry_run:
		return
	flac['LYRICS'] = new_lrc
	flac.save()


CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path.home() / '.cache' / 'lrc_fix'


def _leading_int(value: str, default: int | None) -> int | None:
	"""'7/12' -> 7, '07' -> 7; default if not a number."""
	try:
		return int(value.split('/')[0].strip())
	except ValueError:
		return default


def cache_path(flac: FLAC, cache_dir: Path) -> Path | None:
	"""<discogs_id>_<disc>_<track>.json, or None when the file can't be keyed
	(no usable DISCOGS_RELEASE_ID or TRACKNUMBER) - those files are never cached."""
	discogs_id = _flac_value(flac, 'DISCOGS_RELEASE_ID').strip()
	track = _leading_int(_flac_value(flac, 'TRACKNUMBER'), None)
	if not discogs_id.isdigit() or track is None:
		return None
	disc = _leading_int(_flac_value(flac, 'DISCNUMBER'), 1)
	return cache_dir / f'{discogs_id}_{disc}_{track}.json'


def cache_key(args: argparse.Namespace, flac: FLAC) -> dict:
	"""Everything the cached ASR output depends on besides the lyric text. The
	sample count/rate (not mtime, which every tag write changes) catches a
	replaced rip that reuses the same Discogs ID and track number."""
	return {
		'version': CACHE_VERSION,
		'whisper_model': args.whisper_model,
		'language': args.language,
		'compute_type': args.compute_type,
		'isolate_vocals': not args.no_isolate_vocals,
		'sample_rate': getattr(flac.info, 'sample_rate', None),
		'total_samples': getattr(flac.info, 'total_samples', None),
	}


def load_cache(path: Path, key: dict) -> dict | None:
	"""The cached payload if it exists and every key field matches, else None.
	A missing, unreadable or corrupt file is a miss, never an error."""
	try:
		data = json.loads(path.read_text(encoding='utf-8'))
	except (OSError, ValueError):
		return None
	if not isinstance(data, dict) or not isinstance(data.get('words'), list):
		return None
	if any(data.get(k) != v for k, v in key.items()):
		return None
	if data.get('onsets') is not None and not isinstance(data['onsets'], list):
		return None
	return data


def save_cache(
	path: Path,
	key: dict,
	words: list[dict],
	onsets: list[float] | None,
	language_used: str | None = None,
) -> None:
	"""Write via a temp file + os.replace, so an interrupted run never leaves a
	half-written cache file. A failure to write only costs the speedup."""
	tmp_path = path.with_name(path.name + '.tmp')
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		payload = {**key, 'words': words, 'onsets': onsets}
		if language_used:
			payload['language_used'] = language_used
		tmp_path.write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
		os.replace(tmp_path, path)
	except OSError as exc:
		print(f'   warning: could not write cache {path}: {exc}', file=sys.stderr)


def process_file(path: Path, args: argparse.Namespace, index: int, total: int) -> None:
	print(f'== [{index}/{total}] {path}')
	flac = FLAC(path)
	raw = read_lyrics_tag(flac)
	if not raw:
		print('   skip: no LYRICS tag')
		return

	id_tags, lyric_lines = strip_lyric_lines(raw)
	if not lyric_lines:
		print('   skip: LYRICS tag empty after parsing')
		return
	if is_instrumental(lyric_lines):
		id_tags = ensure_id_tags(id_tags, flac)
		new_lrc = build_instrumental_lrc(id_tags)
		if _strip_metadata_lines(new_lrc) != _strip_metadata_lines(raw):
			id_tags = stamp_creator_tag(id_tags)
			new_lrc = build_instrumental_lrc(id_tags)
		if new_lrc == raw:
			print('   already complete, no change')
			return
		write_lyrics_tag(flac, new_lrc, args.dry_run)
		print(f'   {"would complete" if args.dry_run else "completed"} instrumental marker')
		return
	id_tags = ensure_id_tags(id_tags, flac)

	language, skip_reason = track_language(flac, args)
	if skip_reason:
		print(f'   skip: {skip_reason} - tag left unchanged')
		return

	cache_file = None if args.no_cache else cache_path(flac, args.cache_dir)
	key = cache_key(args, flac)
	cached = None
	if cache_file and not args.refresh_cache:
		cached = load_cache(cache_file, key)
	if cached and language and cached.get('language_used') not in (None, language):
		print(
			f'   cache entry was transcribed as {cached["language_used"]}, the language is '
			f'{language}: transcribing again'
		)
		cached = None
	language_used = cached.get('language_used') if cached else None
	words = cached['words'] if cached else None
	onsets = cached.get('onsets') if cached else None
	if cached:
		print('   cache hit (skipping demucs/whisperx)')
	elif cache_file:
		print('   cache miss')

	with tempfile.TemporaryDirectory(prefix='lrc_fix_') as tmp:
		audio: dict[str, Path] = {}

		def get_audio() -> Path:
			# demucs runs at most once per file, and only if something below needs the audio
			if 'path' not in audio:
				audio['path'] = path
				if not args.no_isolate_vocals:
					print(f'   isolating vocals (demucs, {args.jobs} job(s))...')
					audio['path'] = separate_vocals(path, args.device, args.jobs, Path(tmp))
			return audio['path']

		if words is None:
			audio_path = get_audio()
			shown = f', language {language}' if language else ''
			print(f'   transcribing ({args.whisper_model}, {args.device}{shown})...')
			fallback = None if args.fallback_language.lower() == 'none' else args.fallback_language
			words, language_used = transcribe_words(
				audio_path, args.whisper_model, args.device, args.compute_type, language, fallback
			)
			if words and cache_file:
				save_cache(cache_file, key, words, None, language_used)

		if not words:
			print('   skip: whisperx produced no word timestamps')
			return

		if args.dump_words:
			for w in words:
				print(f'   {w["t"]:8.2f}  {w["w"]}')

		print(f'   aligning {len(lyric_lines)} lines...')
		raw_times = match_line_times(lyric_lines, words)

		if not args.no_vocal_check and all(t is None for t in raw_times):
			print('   no lines matched - checking for vocal activity (VAD)...')
			if not has_speech(get_audio()):
				print(
					'   warning: no lines matched and no vocals detected (VAD) - '
					'possibly mislabeled instrumental; tag left unchanged'
				)
				return

		if not args.no_quality_gate:
			reason = alignment_rejection(
				lyric_lines, raw_times, args.min_match, words, args.min_sung
			)
			if reason:
				print(f'   skip: {reason} - tag left unchanged')
				return

		if args.no_snap_onsets:
			onsets = []
		elif onsets is None:
			print('   detecting vocal onsets...')
			onsets = detect_onsets(get_audio())
			if cache_file:
				save_cache(cache_file, key, words, onsets, language_used)

	times = finalize_times(raw_times, onsets, float(flac.info.length) if flac.info else None)

	new_lrc = build_lrc(id_tags, lyric_lines, times)
	if not args.no_quality_gate:
		broken = [
			r for r in lrc_suspect_reasons(new_lrc) if r in ('one_timestamp', 'shared_timestamps')
		]
		if broken:
			print(f'   skip: result would have {" and ".join(broken)} - tag left unchanged')
			return
	if _strip_metadata_lines(new_lrc) != _strip_metadata_lines(raw):
		id_tags = stamp_creator_tag(id_tags)
		new_lrc = build_lrc(id_tags, lyric_lines, times)
	if new_lrc == raw:
		print('   already up to date, no change')
		return
	write_lyrics_tag(flac, new_lrc, args.dry_run)
	print(f'   {"would update" if args.dry_run else "updated"} LYRICS tag')


def process_missing_lyrics_file(
	path: Path, args: argparse.Namespace, index: int, total: int
) -> None:
	"""For a file with no LYRICS tag at all: use VAD to tell an actual
	instrumental (tag it as such - nothing is being overwritten) from a
	track that simply needs lyrics fetched (just log it, no tag write).
	"""
	print(f'== [{index}/{total}] {path}')
	flac = FLAC(path)

	with tempfile.TemporaryDirectory(prefix='lrc_fix_') as tmp:
		audio_path = path
		if not args.no_isolate_vocals:
			print(f'   isolating vocals (demucs, {args.jobs} job(s))...')
			audio_path = separate_vocals(path, args.device, args.jobs, Path(tmp))

		print('   checking for vocal activity (VAD)...')
		found_speech = has_speech(audio_path)

	if found_speech:
		print(f'   Missing lyrics, not instrumental: {path}')
		return

	# No prior LYRICS tag to compare against - this is unconditionally new
	# lyric content (from nothing to an instrumental marker), so stamp.
	id_tags = stamp_creator_tag(ensure_id_tags([], flac))
	new_lrc = build_instrumental_lrc(id_tags)
	write_lyrics_tag(flac, new_lrc, args.dry_run)
	print(f'   {"would mark" if args.dry_run else "marked"} as instrumental')


def process_metadata_only_file(
	path: Path, args: argparse.Namespace, index: int, total: int
) -> None:
	"""Refresh only the ar/ti/al/length id-tag header lines on a file that's
	already LRC-timestamped and therefore skipped for realignment. [re:] is
	left exactly as it was (ensure_id_tags no longer touches it - see
	stamp_creator_tag) since this pass never changes lyric content. The
	existing timestamped body (e.g. a manually added
	[00:00.00](Spoken Intro) line) is left completely untouched - no
	demucs/whisperx involved.
	"""
	print(f'== [{index}/{total}] {path} (metadata only)')
	flac = FLAC(path)
	raw = read_lyrics_tag(flac)
	if not raw:
		return

	id_tags, body = split_id_tags(raw)
	if not body:
		return

	id_tags = ensure_id_tags(id_tags, flac)
	new_lrc = '\n'.join([*id_tags, *body])
	if new_lrc == raw:
		print('   metadata already up to date, no change')
		return
	write_lyrics_tag(flac, new_lrc, args.dry_run)
	print(f'   {"would update" if args.dry_run else "updated"} metadata only')


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('path', type=Path, help='FLAC file or directory to process')
	parser.add_argument('--whisper-model', default='medium')
	parser.add_argument('--language', default=None)
	parser.add_argument('--device', default='cpu')
	parser.add_argument('--compute-type', default='int8')
	parser.add_argument(
		'--jobs',
		'-j',
		type=int,
		default=min(4, os.cpu_count() or 1),
		help='parallel demucs jobs (each holds a model copy in memory; '
		'default is min(4, cpu count) to bound memory use)',
	)
	parser.add_argument('--dry-run', action='store_true')
	parser.add_argument(
		'--all',
		action='store_true',
		help='when path is a directory, also reprocess files whose '
		'LYRICS tag is already LRC-timestamped',
	)
	parser.add_argument(
		'--no-isolate-vocals',
		action='store_true',
		help='skip demucs vocal separation, transcribe the full mix',
	)
	parser.add_argument(
		'--no-snap-onsets',
		action='store_true',
		help="don't snap line timestamps to detected vocal onsets",
	)
	parser.add_argument(
		'--no-vocal-check',
		action='store_true',
		help="don't run a VAD fallback check when alignment finds zero "
		'matches (which otherwise warns about a possibly mislabeled '
		'instrumental instead of writing a useless tag)',
	)
	parser.add_argument(
		'--min-match',
		type=float,
		default=0.6,
		metavar='FRACTION',
		help='minimum share of lyric lines that must match the transcript '
		'(default 0.6); a weaker alignment is skipped and the tag left '
		'unchanged instead of being stamped with copied timestamps',
	)
	parser.add_argument(
		'--min-sung',
		type=float,
		default=0.5,
		metavar='FRACTION',
		help="minimum share of the lyric's word pairs that must occur in the transcript "
		'(default 0.5, 0 disables); a text that is mostly not sung is skipped and the tag left '
		'unchanged even if single common words match enough lines',
	)
	parser.add_argument(
		'--fallback-language',
		default='en',
		metavar='LANG',
		help='when whisperx has no alignment model for the detected language, transcribe again as '
		'this language (default en, none = fail as before)',
	)
	parser.add_argument(
		'--ignore-language-tag',
		action='store_true',
		help='ignore the LYRICS_LANGUAGE tag (sung language per track, from MusicBrainz): '
		'auto-detect the language and do not skip instrumentals or unsupported languages',
	)
	parser.add_argument(
		'--no-quality-gate',
		action='store_true',
		help='write the alignment even when too few lines matched or the '
		'result piles lines onto one timestamp',
	)
	parser.add_argument(
		'--find-missing-lyrics',
		action='store_true',
		help='instead of the normal pipeline, scan for files with no '
		'LYRICS tag at all and use VAD to tell instrumentals (tagged '
		'as such) from tracks that just need lyrics fetched (logged)',
	)
	parser.add_argument(
		'--dump-words',
		action='store_true',
		help='print the raw ASR word/timestamp transcript for debugging',
	)
	parser.add_argument(
		'--cache-dir',
		type=Path,
		default=DEFAULT_CACHE_DIR,
		metavar='PATH',
		help='where the demucs/whisperx results are cached, one JSON file per '
		'track keyed by Discogs ID/disc/track (default ~/.cache/lrc_fix)',
	)
	parser.add_argument(
		'--no-cache', action='store_true', help='neither read nor write the demucs/whisperx cache'
	)
	parser.add_argument(
		'--refresh-cache',
		action='store_true',
		help='ignore existing cache entries and rewrite them',
	)
	args = parser.parse_args()
	if not 0.0 <= args.min_match <= 1.0:
		parser.error('--min-match must be between 0 and 1')
	if not 0.0 <= args.min_sung <= 1.0:
		parser.error('--min-sung must be between 0 and 1')
	if args.no_cache and args.refresh_cache:
		parser.error('--no-cache and --refresh-cache are mutually exclusive')

	files = find_flac_files(args.path)
	if not files:
		print(f'no .flac files found under {args.path}', file=sys.stderr)
		return 1

	if args.find_missing_lyrics:
		missing = []
		for f in files:
			try:
				raw = read_lyrics_tag(FLAC(f))
			except Exception as exc:  # noqa: BLE001
				print(f'error reading {f}: {exc}', file=sys.stderr)
				continue
			if not raw:
				missing.append(f)
		if not missing:
			print('nothing to process')
			return 0
		print(f'{len(missing)} file(s) with no LYRICS tag')
		for i, path in enumerate(missing, 1):
			try:
				process_missing_lyrics_file(path, args, i, len(missing))
			except Exception as exc:  # noqa: BLE001
				print(f'   error: {exc}', file=sys.stderr)
		return 0

	if args.path.is_dir():
		kept = []
		metadata_only = []
		skipped_no_lyrics = 0
		for f in files:
			try:
				raw = read_lyrics_tag(FLAC(f))
			except Exception as exc:  # noqa: BLE001
				print(f'error reading {f}: {exc}', file=sys.stderr)
				continue
			if not raw:
				skipped_no_lyrics += 1
				continue
			_, lyric_lines = strip_lyric_lines(raw)
			if not lyric_lines:
				skipped_no_lyrics += 1
				continue
			if is_instrumental(lyric_lines):
				# Always keep instrumental placeholders for completion into the
				# canonical marker, even if a stray/malformed timestamp on the
				# line would otherwise make is_lrc() below treat it as
				# already-processed and skip it forever.
				kept.append(f)
				continue
			if not args.all and is_lrc(raw):
				# Already LRC-timestamped, so no realignment - but its id-tag
				# header (ar/ti/al/re/length) can still be stale/incomplete
				# (e.g. a manually added [00:00.00](Spoken Intro) marker never
				# got the usual ensure_id_tags treatment). Fix that cheaply
				# without touching the existing timestamped body.
				metadata_only.append(f)
				continue
			kept.append(f)
		if metadata_only:
			print(
				f'{len(metadata_only)} file(s) already LRC-timestamped - '
				f'checking/refreshing metadata only (use --all to fully realign them instead)'
			)
			for i, path in enumerate(metadata_only, 1):
				try:
					process_metadata_only_file(path, args, i, len(metadata_only))
				except Exception as exc:  # noqa: BLE001
					print(f'   error: {exc}', file=sys.stderr)
		if skipped_no_lyrics:
			print(f'skipping {skipped_no_lyrics} file(s) with no usable lyrics')
		files = kept

	if not files:
		print('nothing to process')
		return 0

	print(f'{len(files)} file(s) to process')
	for i, path in enumerate(files, 1):
		try:
			process_file(path, args, i, len(files))
		except Exception as exc:  # noqa: BLE001
			print(f'   error: {exc}', file=sys.stderr)

	return 0


if __name__ == '__main__':
	raise SystemExit(main())
