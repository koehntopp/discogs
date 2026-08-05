#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "mutagen>=1.47",
#   "openai-whisper",
#   "rich>=13",
#   "click>=8",
#   "torch",
#   "numpy",
#   "structlog",
# ]
# ///
"""
align_lyrics.py — LRC timestamp correction using local Whisper STT

Reads FLAC files from a folder, extracts TXT or LRC lyrics from tags,
runs a local Whisper model to get word-level timestamps, and aligns
the lyrics lines against the transcription to suggest improved LRC timestamps.

Usage:
    uv run align_lyrics.py [FOLDER] [--model base] [--write] [--dry-run]
    uv run align_lyrics.py [FOLDER] --anchor-slack 5 --no-split
"""

import difflib
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# Suppress Whisper's "FP16 is not supported on CPU; using FP32 instead" noise.
# We already handle this intentionally for the MPS workaround.
warnings.filterwarnings('ignore', message='FP16 is not supported on CPU')

import click
import numpy as np
import torch
import whisper
from mutagen.flac import FLAC
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

from log import logger

# ─── Constants ──────────────────────────────────────────────────────────────────

LRC_TIMESTAMP_RE = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2})\]')
LRC_HEADER_RE = re.compile(r'^\[(ar|ti|al|by|length|offset):.*\]\s*$', re.IGNORECASE)
LYRICS_TAGS = ('LYRICS', 'UNSYNCEDLYRICS', 'COMMENT')  # checked in order
MULTILINE_SPLIT_RE = re.compile(r'\s*/\s*|\s*\|\s*')  # " / " or " | " delimiters

PUNCT_RE = re.compile(r"[^\w\s']", re.UNICODE)

DEFAULT_ANCHOR_SLACK = 5.0  # seconds either side of original_ts to search

console = Console(stderr=True)


# ─── Data structures ─────────────────────────────────────────────────────────────


@dataclass
class LyricLine:
	"""A single line from the lyrics, with an optional original timestamp."""

	text: str  # clean text, no timestamp
	original_ts: float | None = None  # seconds, None if plain TXT


@dataclass
class WhisperWord:
	"""One word from the Whisper transcription, with its start/end time."""

	word: str
	start: float
	end: float
	segment_id: int = 0  # index of the Whisper segment this word belongs to
	norm: str = field(init=False)

	def __post_init__(self) -> None:
		self.norm = _normalize(self.word)


@dataclass
class AlignedLine:
	"""A lyric line paired with the suggested start timestamp."""

	lyric: LyricLine
	suggested_ts: float | None
	confidence: float  # 0.0 – 1.0 similarity score
	whisper_text: str | None = None  # raw words Whisper produced in the matched window


# ─── Text helpers ────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
	"""Lowercase, strip punctuation, collapse whitespace, return single token string."""
	return PUNCT_RE.sub(' ', text.lower()).strip()


def _normalize_words(text: str) -> list[str]:
	"""Return normalized word tokens from a string."""
	cleaned = PUNCT_RE.sub(' ', text.lower())
	return [w for w in cleaned.split() if w]


def _ts_to_secs(mm: str, ss: str, cs: str) -> float:
	return int(mm) * 60 + int(ss) + int(cs) / 100


def _secs_to_lrc(secs: float) -> str:
	"""Convert seconds to [MM:SS.xx] LRC timestamp string."""
	minutes = int(secs) // 60
	sec_part = secs - minutes * 60
	return f'[{minutes:02d}:{sec_part:05.2f}]'


# ─── LRC / TXT parsing ───────────────────────────────────────────────────────────


def parse_lyrics(raw: str) -> list[LyricLine]:
	"""
	Parse raw lyrics string into a list of LyricLine objects.
	Handles both plain TXT (no timestamps) and LRC (with [MM:SS.xx] timestamps).
	LRC header metadata lines are silently dropped.
	"""
	lines: list[LyricLine] = []
	for raw_line in raw.splitlines():
		raw_line = raw_line.strip()
		if not raw_line:
			continue
		if LRC_HEADER_RE.match(raw_line):
			continue

		# Try to strip a leading LRC timestamp
		m = LRC_TIMESTAMP_RE.match(raw_line)
		if m:
			ts = _ts_to_secs(m.group(1), m.group(2), m.group(3))
			text = raw_line[m.end() :].strip()
		else:
			ts = None
			text = raw_line

		if text:
			lines.append(LyricLine(text=text, original_ts=ts))

	return lines


def split_multiline(lines: list[LyricLine]) -> list[LyricLine]:
	"""
	Expand multi-line LRC entries into individual LyricLine objects so each
	sub-phrase can receive its own Whisper-derived timestamp.

	Two heuristics are applied:
	  1. Explicit delimiters: a line containing " / " or " | " is split on that
	     delimiter. The first sub-phrase inherits the original timestamp; the
	     rest get None (to be filled by alignment).
	  2. Continuation lines: an un-timestamped line that immediately follows a
	     timestamped one is already a separate LyricLine in the parsed output,
	     so no extra work is needed here — they will be aligned individually.
	"""
	result: list[LyricLine] = []
	for line in lines:
		parts = MULTILINE_SPLIT_RE.split(line.text)
		if len(parts) == 1:
			# No delimiter found — pass through unchanged
			result.append(line)
		else:
			for idx, part in enumerate(parts):
				part = part.strip()
				if part:
					result.append(
						LyricLine(text=part, original_ts=line.original_ts if idx == 0 else None)
					)
	return result


def extract_lyrics_from_flac(path: Path) -> tuple[str | None, str | None]:
	"""
	Return (raw_lyrics, tag_name) for the first populated lyrics tag found,
	or (None, None) if none exists.
	"""
	try:
		audio = FLAC(str(path))
	except (OSError, ValueError, EOFError) as exc:
		console.print(f'[red]Cannot read {path.name}: {exc}[/red]')
		return None, None

	tags = dict(audio.tags or {})
	# Normalise to uppercase keys
	tags_upper = {k.upper(): v for k, v in tags.items()}

	for tag in LYRICS_TAGS:
		val = tags_upper.get(tag)
		if val:
			raw = val[0] if isinstance(val, list) else str(val)
			if raw.strip():
				return raw.strip(), tag

	return None, None


# ─── Whisper transcription ────────────────────────────────────────────────────────


def transcribe(
	path: Path, model: whisper.Whisper, transcribe_device: str = 'cpu'
) -> list[WhisperWord]:
	"""
	Transcribe the audio file with Whisper using word-level timestamps.
	Returns a flat list of WhisperWord objects ordered by start time.

	Note: word_timestamps=True uses a DTW (dynamic time warping) alignment step
	that calls .double() internally, which requires float64.  MPS does not support
	float64, so we move the model to `transcribe_device` (always CPU on MPS) just
	for this call and restore it afterwards.
	"""
	orig_device = next(model.parameters()).device
	need_move = str(orig_device) != transcribe_device
	if need_move:
		model = model.to(transcribe_device)
	try:
		result = model.transcribe(str(path), word_timestamps=True, verbose=False, task='transcribe')
	finally:
		if need_move:
			model = model.to(orig_device)

	words: list[WhisperWord] = []
	for seg_idx, segment in enumerate(result.get('segments', [])):
		for w in segment.get('words', []):
			word_text = w.get('word', '').strip()
			if word_text:
				words.append(
					WhisperWord(word=word_text, start=w['start'], end=w['end'], segment_id=seg_idx)
				)

	return words


# ─── Alignment ───────────────────────────────────────────────────────────────────


def _window_similarity(
	lyric_tokens: list[str], whisper_words: list[WhisperWord], start: int
) -> float:
	"""
	Compute normalised similarity between lyric_tokens and a same-length window
	starting at position `start` in whisper_words.
	"""
	n = len(lyric_tokens)
	window = [w.norm for w in whisper_words[start : start + n]]
	if not window:
		return 0.0
	sm = difflib.SequenceMatcher(None, lyric_tokens, window, autojunk=False)
	return sm.ratio()


def _split_by_segments(
	lyric_line: LyricLine,
	window_words: list[WhisperWord],
	*,
	min_segment_words: int = 3,
	fallback_confidence: float = 0.3,
) -> list[tuple[float, str]] | None:
	"""
	Attempt to split a lyric line into sub-lines using Whisper segment boundaries.

	Returns a list of (timestamp, lyric_fragment) tuples when a meaningful split
	is found, or None if the line should remain unsplit.

	Algorithm:
	  1. Group window_words by segment_id into N ordered groups.
	  2. Merge any group with fewer than min_segment_words into its neighbour.
	  3. Tokenise the lyric text and greedily assign lyric tokens to each segment
	     group using SequenceMatcher to find the best token boundary.
	  4. If any fragment has similarity below fallback_confidence, return None.
	  5. Reconstruct each fragment from the *original* lyric text (preserving
	     capitalisation and punctuation) by rejoining the assigned words.
	"""
	# ── 1. Group words by segment ────────────────────────────────────────────
	from itertools import groupby

	groups: list[list[WhisperWord]] = [
		list(g) for _, g in groupby(window_words, key=lambda w: w.segment_id)
	]

	if len(groups) <= 1:
		return None  # single segment — nothing to split

	# ── 2. Merge tiny groups ─────────────────────────────────────────────────
	merged: list[list[WhisperWord]] = []
	for group in groups:
		if merged and len(group) < min_segment_words:
			# Too small — absorb into the previous group
			merged[-1].extend(group)
		else:
			merged.append(list(group))

	if len(merged) <= 1:
		return None  # merging collapsed everything

	# ── 3. Assign lyric tokens to segments ──────────────────────────────────
	lyric_words_orig = lyric_line.text.split()  # preserve original capitalisation
	lyric_tokens = _normalize_words(lyric_line.text)
	n_tokens = len(lyric_tokens)

	fragments: list[tuple[float, str]] = []
	token_cursor = 0

	for seg_idx, seg_words in enumerate(merged):
		seg_tokens = [w.norm for w in seg_words]
		seg_ts = seg_words[0].start
		is_last = seg_idx == len(merged) - 1

		if is_last:
			# Last segment takes all remaining lyric tokens
			assigned_orig = lyric_words_orig[token_cursor:]
			assigned_norm = lyric_tokens[token_cursor:]
		else:
			# Find the boundary that best matches this segment's tokens
			seg_len = len(seg_tokens)
			best_score = 0.0
			best_end = token_cursor + seg_len  # default: consume exactly seg_len tokens

			# Search a small window around the expected boundary
			for end in range(
				max(token_cursor + 1, token_cursor + seg_len - 3),
				min(n_tokens, token_cursor + seg_len + 4),
			):
				candidate = lyric_tokens[token_cursor:end]
				sm = difflib.SequenceMatcher(None, seg_tokens, candidate, autojunk=False)
				score = sm.ratio()
				if score > best_score:
					best_score = score
					best_end = end

			if best_score < fallback_confidence:
				return None  # can't split cleanly — fall back to unsplit line

			assigned_orig = lyric_words_orig[token_cursor:best_end]
			assigned_norm = lyric_tokens[token_cursor:best_end]
			token_cursor = best_end

		if not assigned_orig:
			continue

		# Sanity: last-fragment similarity check
		if is_last and assigned_norm:
			sm = difflib.SequenceMatcher(
				None, [w.norm for w in seg_words], assigned_norm, autojunk=False
			)
			if sm.ratio() < fallback_confidence:
				return None

		fragments.append((seg_ts, ' '.join(assigned_orig)))

	if len(fragments) <= 1:
		return None

	return fragments


def align(
	lyric_lines: list[LyricLine],
	words: list[WhisperWord],
	*,
	anchor_slack: float = DEFAULT_ANCHOR_SLACK,
	segment_split: bool = True,
	min_confidence: float = 0.5,
) -> list[AlignedLine]:
	"""
	Align each lyric line to the best matching window of Whisper words.

	Two search strategies are used depending on whether original timestamps exist:

	  Time-anchor (LRC input): when a lyric line carries an original_ts, search
	  only the Whisper words whose start time falls within
	  [original_ts - anchor_slack, original_ts + anchor_slack].  This prevents
	  the cursor from jumping to a later repetition of a chorus phrase.
	  Falls back to the greedy window if no words fall in the anchor range.

	  Greedy (plain TXT input): search a forward look-ahead of max(n*3, 20)
	  words from the cursor position.  The cursor advances past the best match
	  to preserve line order.

	When segment_split=True, any matched window that spans multiple Whisper
	segments (natural pause boundaries) is split into individually-timestamped
	sub-lines via _split_by_segments().
	"""
	if not words:
		return [
			AlignedLine(lyric=ll, suggested_ts=ll.original_ts, confidence=0.0) for ll in lyric_lines
		]

	results: list[AlignedLine] = []
	cursor = 0  # minimum word index for next greedy search

	for lyric_line in lyric_lines:
		tokens = _normalize_words(lyric_line.text)
		if not tokens:
			results.append(
				AlignedLine(lyric=lyric_line, suggested_ts=lyric_line.original_ts, confidence=0.0)
			)
			continue

		n = len(tokens)
		best_score = 0.0
		best_pos = cursor

		if lyric_line.original_ts is not None:
			# ── Time-anchor search ──────────────────────────────────────────────
			# Find word indices whose start time is within the anchor window and at/after cursor.
			lo = lyric_line.original_ts - anchor_slack
			hi = lyric_line.original_ts + anchor_slack
			anchor_indices = [i for i, w in enumerate(words) if lo <= w.start <= hi and i >= cursor]
			if not anchor_indices:
				# Anchor window empty — fall back to greedy from cursor
				search_start = cursor
				search_end = min(len(words) - n + 1, cursor + max(n * 3, 20))
			else:
				search_start = max(cursor, anchor_indices[0])
				search_end = min(len(words) - n + 1, max(search_start + 1, anchor_indices[-1] + 1))
		else:
			# ── Greedy forward search ───────────────────────────────────────────
			search_start = cursor
			search_end = min(len(words) - n + 1, cursor + max(n * 3, 20))

		for i in range(search_start, search_end):
			score = _window_similarity(tokens, words, i)
			if score > best_score:
				best_score = score
				best_pos = i

		# Three-level fallback for suggested timestamp:
		#  1. High-confidence text match (>= min_confidence) → use Whisper word start time
		#  2. Low-confidence match or no match but original_ts exists → fall back to original tag ts
		#  3. Low-confidence match, plain TXT input → leave as None (format_lrc will interpolate)
		if best_score >= min_confidence:
			suggested_ts = words[best_pos].start
			window_words = words[best_pos : best_pos + n]
			whisper_text: str | None = ' '.join(w.word for w in window_words)

			# ── Segment-based splitting ───────────────────────────────────────
			if segment_split:
				frags = _split_by_segments(
					lyric_line, window_words, fallback_confidence=min_confidence
				)
				if frags:
					for frag_ts, frag_text in frags:
						results.append(
							AlignedLine(
								lyric=LyricLine(text=frag_text, original_ts=None),
								suggested_ts=frag_ts,
								confidence=round(best_score, 3),
								whisper_text=whisper_text,
							)
						)
					cursor = max(cursor, best_pos + max(n, 1))
					continue  # skip the normal single-line append below

		elif lyric_line.original_ts is not None:
			suggested_ts = lyric_line.original_ts
			# Tag fallback case: collect whatever Whisper said anywhere near the anchor window
			lo = lyric_line.original_ts - anchor_slack
			hi = lyric_line.original_ts + anchor_slack
			nearby = [w.word for w in words if lo <= w.start <= hi]
			whisper_text = ' '.join(nearby) if nearby else None
		else:
			suggested_ts = None
			whisper_text = None

		# Advance greedy cursor past this match so subsequent lines search forward
		cursor = max(cursor, best_pos + max(n, 1))

		results.append(
			AlignedLine(
				lyric=lyric_line,
				suggested_ts=suggested_ts,
				confidence=round(max(0.0, best_score), 3),  # clamp sentinel -1 → 0
				whisper_text=whisper_text,
			)
		)

	return results


# ─── Output formatting ───────────────────────────────────────────────────────────


def format_lrc(
	aligned: list[AlignedLine], *, artist: str = '', title: str = '', album: str = ''
) -> str:
	"""Render aligned lines as an LRC file string with guaranteed timestamps for every line."""
	header_parts = []
	if artist:
		header_parts.append(f'[ar:{artist}]')
	if title:
		header_parts.append(f'[ti:{title}]')
	if album:
		header_parts.append(f'[al:{album}]')

	body_lines = []
	last_ts = 0.0
	for a in aligned:
		if a.suggested_ts is not None:
			ts = a.suggested_ts
			last_ts = ts
		elif a.lyric.original_ts is not None:
			ts = a.lyric.original_ts
			last_ts = ts
		else:
			ts = last_ts
		body_lines.append(f'{_secs_to_lrc(ts)}{a.lyric.text}')

	parts = header_parts + body_lines
	return '\n'.join(parts)


def _render_comparison_table(aligned: list[AlignedLine]) -> Table:
	"""Build a Rich table comparing original vs suggested timestamps."""
	table = Table(show_header=True, header_style='bold cyan', expand=True, box=None)
	table.add_column('Original', style='dim', no_wrap=True, min_width=10)
	table.add_column('Suggested', no_wrap=True, min_width=10)
	table.add_column('Δ sec', no_wrap=True, min_width=7)
	table.add_column('Conf', no_wrap=True, min_width=5)
	table.add_column('Lyric text')

	for a in aligned:
		orig_str = (
			_secs_to_lrc(a.lyric.original_ts) if a.lyric.original_ts is not None else '(none)'
		)

		# Detect fallback case: timestamp was not Whisper-derived, copied from original
		is_fallback = (
			a.suggested_ts is not None
			and a.lyric.original_ts is not None
			and a.suggested_ts == a.lyric.original_ts
			and a.confidence < 0.5
		)
		if is_fallback:
			sugg_str = f'[dim]{_secs_to_lrc(a.suggested_ts)} (tag fallback)[/dim]'
		elif a.suggested_ts is not None:
			sugg_str = _secs_to_lrc(a.suggested_ts)
		else:
			sugg_str = '(none)'

		if a.lyric.original_ts is not None and a.suggested_ts is not None:
			delta = a.suggested_ts - a.lyric.original_ts
			delta_str = f'{delta:+.2f}'
			delta_color = 'green' if abs(delta) < 0.5 else ('yellow' if abs(delta) < 2.0 else 'red')
		else:
			delta_str = '—'
			delta_color = 'dim'

		conf_color = (
			'green' if a.confidence >= 0.7 else ('yellow' if a.confidence >= 0.4 else 'red')
		)

		table.add_row(
			orig_str,
			sugg_str,
			f'[{delta_color}]{delta_str}[/{delta_color}]',
			f'[{conf_color}]{a.confidence:.2f}[/{conf_color}]',
			a.lyric.text[:80],
		)

	return table


# ─── Per-file processing ──────────────────────────────────────────────────────────


def process_file(
	path: Path,
	model: whisper.Whisper,
	*,
	write: bool,
	dry_run: bool,
	min_confidence: float,
	transcribe_device: str = 'cpu',
	anchor_slack: float = DEFAULT_ANCHOR_SLACK,
	split: bool = True,
	segment_split: bool = True,
) -> bool:
	"""
	Full pipeline for one FLAC file.

	Returns True if the file was processed successfully with at least one aligned line.
	"""
	console.rule(f'[bold]{path.name}[/bold]')

	# 1. Extract lyrics
	raw_lyrics, tag_name = extract_lyrics_from_flac(path)
	if not raw_lyrics:
		console.print('  [dim]No lyrics tag found — skipping.[/dim]')
		return False

	lyric_lines = parse_lyrics(raw_lyrics)
	if not lyric_lines:
		console.print('  [dim]Lyrics tag is empty after parsing — skipping.[/dim]')
		return False

	if split:
		lyric_lines = split_multiline(lyric_lines)

	has_timestamps = any(ll.original_ts is not None for ll in lyric_lines)
	console.print(
		f'  Tag [cyan]{tag_name}[/cyan]: '
		f'[bold]{len(lyric_lines)}[/bold] lines, '
		f'format: [magenta]{"LRC" if has_timestamps else "plain TXT"}[/magenta]'
		+ (f', anchor_slack=[cyan]±{anchor_slack}s[/cyan]' if has_timestamps else '')
	)

	# 2. Transcribe with Whisper
	with console.status(f'  Transcribing [dim]{path.name}[/dim] with Whisper…'):
		words = transcribe(path, model, transcribe_device=transcribe_device)

	if not words:
		console.print('  [red]Whisper returned no words — skipping.[/red]')
		return False

	console.print(f'  Whisper: [bold]{len(words)}[/bold] words transcribed.')

	# 3. Align
	aligned = align(
		lyric_lines,
		words,
		anchor_slack=anchor_slack,
		segment_split=segment_split,
		min_confidence=min_confidence,
	)

	# 4. Read tags for metadata
	try:
		audio = FLAC(str(path))
		tags = {
			k.upper(): (v[0] if isinstance(v, list) else str(v))
			for k, v in (audio.tags or {}).items()
		}
	except (OSError, ValueError, EOFError):
		tags = {}

	artist = tags.get('ARTIST', tags.get('ALBUMARTIST', ''))
	title = tags.get('TITLE', '')
	album = tags.get('ALBUM', '')

	# 5. Show comparison table
	console.print()
	console.print(_render_comparison_table(aligned))

	# 6. Compute suggested LRC and show preview
	lrc_out = format_lrc(aligned, artist=artist, title=title, album=album)
	avg_conf = float(np.mean([a.confidence for a in aligned]))

	console.print()
	console.print(
		Panel(
			Syntax(lrc_out, 'text', theme='monokai', line_numbers=False),
			title='[bold green]Suggested LRC[/bold green]',
			subtitle=f'avg confidence: {avg_conf:.2f}',
			expand=False,
		)
	)

	# Warn about low-confidence lines with per-line diagnostic
	low_conf = [a for a in aligned if a.confidence < min_confidence]
	if low_conf:
		console.print(
			f'  [yellow]⚠ {len(low_conf)} line(s) below confidence threshold '
			f'({min_confidence:.2f}):[/yellow]'
		)
		diag = Table(show_header=True, header_style='bold yellow', box=None, padding=(0, 1))
		diag.add_column('Conf', no_wrap=True, min_width=5)
		diag.add_column('Lyric text', min_width=30)
		diag.add_column('Whisper heard', style='dim')
		for a in low_conf:
			conf_str = f'[red]{a.confidence:.2f}[/red]'
			lyric_str = a.lyric.text[:50]
			if a.whisper_text:
				heard_str = a.whisper_text[:60]
			else:
				heard_str = '[dim italic](nothing in window)[/dim italic]'
			diag.add_row(conf_str, lyric_str, heard_str)
		console.print(diag)

	# Log lines with changed timestamps
	changed_lines = []
	for a in aligned:
		if a.suggested_ts is not None:
			if a.lyric.original_ts is not None:
				delta = a.suggested_ts - a.lyric.original_ts
				if abs(delta) >= 0.05:
					changed_lines.append((a, delta))
			else:
				changed_lines.append((a, None))

	if changed_lines:
		console.print()
		console.print(f'  [cyan]ℹ {len(changed_lines)} timestamp(s) changed:[/cyan]')
		chg_table = Table(show_header=True, header_style='bold cyan', box=None, padding=(0, 1))
		chg_table.add_column('Original', style='dim', no_wrap=True, min_width=10)
		chg_table.add_column('Suggested', no_wrap=True, min_width=10)
		chg_table.add_column('Δ sec', no_wrap=True, min_width=7)
		chg_table.add_column('Lyric text', min_width=30)
		for a, delta in changed_lines:
			orig_s = (
				_secs_to_lrc(a.lyric.original_ts) if a.lyric.original_ts is not None else '(none)'
			)
			sugg_s = _secs_to_lrc(a.suggested_ts) if a.suggested_ts is not None else '(none)'
			delta_s = f'{delta:+.2f}s' if delta is not None else 'NEW'
			chg_table.add_row(orig_s, sugg_s, delta_s, a.lyric.text[:50])
			logger.info(
				'timestamp_changed',
				file=path.name,
				orig=orig_s,
				suggested=sugg_s,
				delta=delta_s,
				text=a.lyric.text,
			)
		console.print(chg_table)

	# 7. Optionally write back to the FLAC LYRICS tag
	if write and not dry_run:
		try:
			audio_w = FLAC(str(path))
			audio_w['LYRICS'] = lrc_out
			audio_w.save()
			console.print(f'  [green]✓ LYRICS tag updated in[/green] {path.name}')
		except (OSError, ValueError, EOFError) as exc:
			console.print(f'  [red]✗ Could not write LYRICS tag in {path.name}: {exc}[/red]')

	return True


# ─── CLI ──────────────────────────────────────────────────────────────────────────


@click.command()
@click.argument(
	'target',
	default='.',
	type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@click.option(
	'--model',
	'-m',
	default='base',
	show_default=True,
	type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo'], case_sensitive=False),
	help='Whisper model size. Larger = more accurate but slower.',
)
@click.option(
	'--device',
	'-d',
	default='auto',
	show_default=True,
	help='Torch device: auto | cpu | cuda | mps',
)
@click.option(
	'--write',
	'-w',
	is_flag=True,
	default=False,
	help='Write suggested LRC back into the LYRICS tag of each FLAC file (overwrites existing lyrics).',
)
@click.option(
	'--dry-run',
	is_flag=True,
	default=False,
	help='Show suggestions without writing any files (overrides --write).',
)
@click.option(
	'--min-confidence',
	default=0.5,
	show_default=True,
	type=float,
	help='Warn about lines with alignment confidence below this threshold.',
)
@click.option('--recursive', '-r', is_flag=True, default=False, help='Recurse into sub-folders.')
@click.option(
	'--anchor-slack',
	default=DEFAULT_ANCHOR_SLACK,
	show_default=True,
	type=float,
	help=(
		'For LRC input: search Whisper words within ±SECONDS of each original timestamp. '
		'Increase if original timestamps are far off; decrease for tighter anchoring.'
	),
)
@click.option(
	'--no-split',
	is_flag=True,
	default=False,
	help='Disable delimiter-based splitting (keep " / " and " | " intact).',
)
@click.option(
	'--no-segment-split',
	is_flag=True,
	default=False,
	help=(
		'Disable Whisper-segment-based splitting. '
		'Large lyric blocks that span multiple Whisper segments will not be split.'
	),
)
def main(
	target: Path,
	model: str,
	device: str,
	write: bool,
	dry_run: bool,
	min_confidence: float,
	recursive: bool,
	anchor_slack: float,
	no_split: bool,
	no_segment_split: bool,
) -> None:
	"""
	Align FLAC lyrics tags to Whisper speech-to-text timestamps.

	Reads LRC or plain TXT lyrics from FLAC tags, runs a local Whisper
	model to produce word-level timestamps, then aligns each lyric line
	to the best-matching span of transcribed words.

	Outputs a comparison table and a suggested LRC for each track.
	Use --write to overwrite the LYRICS tag in each FLAC with the suggested LRC.
	Use --dry-run to preview suggestions without modifying any files.
	"""
	# ── Device selection ────────────────────────────────────────────────────
	if device == 'auto':
		if torch.cuda.is_available():
			_device = 'cuda'
		elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
			_device = 'mps'
		else:
			_device = 'cpu'
	else:
		_device = device

	# Whisper's word-timestamp DTW alignment calls .double() (float64).
	# MPS does not support float64, so transcription must run on CPU.
	_transcribe_device = 'cpu' if _device == 'mps' else _device
	if _device == 'mps':
		console.print(
			'[yellow]⚠ MPS does not support float64 (required by Whisper DTW). '
			'Model will load on MPS but transcription will run on CPU.[/yellow]'
		)

	console.print(
		Panel(
			f'[bold cyan]align_lyrics[/bold cyan]  —  Whisper LRC timestamp alignment\n'
			f'Model: [magenta]{model}[/magenta]   '
			f'Device: [magenta]{_device}[/magenta]   '
			f'Target: [dim]{target}[/dim]',
			title='[bold]Startup[/bold]',
		)
	)

	# ── Load model ──────────────────────────────────────────────────────────
	with console.status(f'Loading Whisper model [bold]{model}[/bold] on [bold]{_device}[/bold]…'):
		wmodel = whisper.load_model(model, device=_device)
	console.print(f'[green]✓[/green] Model [bold]{model}[/bold] ready on {_device}.')

	# ── Discover FLAC files ────────────────────────────────────────────────
	if target.is_file():
		if target.suffix.lower() == '.flac':
			flac_files = [target]
		else:
			console.print(f'[red]Target file {target.name} is not a .flac file.[/red]')
			sys.exit(1)
	else:
		pattern = '**/*.flac' if recursive else '*.flac'
		flac_files = sorted(target.glob(pattern))

	if not flac_files:
		console.print('[yellow]No FLAC files found.[/yellow]')
		sys.exit(0)

	console.print(f'Found [bold]{len(flac_files)}[/bold] FLAC file(s).\n')

	# ── Process each file ──────────────────────────────────────────────────
	ok = 0
	with Progress(
		SpinnerColumn(),
		TextColumn('[progress.description]{task.description}'),
		BarColumn(),
		MofNCompleteColumn(),
		console=Console(stderr=True),
	) as progress:
		task = progress.add_task('Aligning lyrics…', total=len(flac_files))
		for flac_path in flac_files:
			progress.update(task, description=f'[cyan]{flac_path.name[:40]}[/cyan]')
			if process_file(
				flac_path,
				wmodel,
				write=write,
				dry_run=dry_run,
				min_confidence=min_confidence,
				transcribe_device=_transcribe_device,
				anchor_slack=anchor_slack,
				split=not no_split,
				segment_split=not no_segment_split,
			):
				ok += 1
			progress.advance(task)

	console.print()
	console.rule()
	console.print(
		f'Done. [bold green]{ok}[/bold green] / [bold]{len(flac_files)}[/bold] file(s) aligned.'
	)
	if write and not dry_run:
		console.print('[dim]LYRICS tags updated in each processed FLAC.[/dim]')


if __name__ == '__main__':
	main()
