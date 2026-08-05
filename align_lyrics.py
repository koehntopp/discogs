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
"""

import difflib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

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

# ─── Constants ──────────────────────────────────────────────────────────────────

LRC_TIMESTAMP_RE = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2})\]')
LRC_HEADER_RE = re.compile(r'^\[(ar|ti|al|by|length|offset):.*\]\s*$', re.IGNORECASE)
LYRICS_TAGS = ('LYRICS', 'UNSYNCEDLYRICS', 'COMMENT')  # checked in order

PUNCT_RE = re.compile(r"[^\w\s']", re.UNICODE)

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
	norm: str = field(init=False)

	def __post_init__(self) -> None:
		self.norm = _normalize(self.word)


@dataclass
class AlignedLine:
	"""A lyric line paired with the suggested start timestamp."""

	lyric: LyricLine
	suggested_ts: float | None
	confidence: float  # 0.0 – 1.0 similarity score


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
	for segment in result.get('segments', []):
		for w in segment.get('words', []):
			word_text = w.get('word', '').strip()
			if word_text:
				words.append(WhisperWord(word=word_text, start=w['start'], end=w['end']))

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


def align(lyric_lines: list[LyricLine], words: list[WhisperWord]) -> list[AlignedLine]:
	"""
	Greedily align each lyric line to the best matching window of Whisper words.

	Strategy:
	  - For each lyric line, compute the similarity score for every possible
	    starting position in the remaining (unconsumed) Whisper words.
	  - Pick the highest-scoring position; advance the cursor to just past that window.
	  - This single-pass greedy approach keeps lines in order, which is a safe
	    assumption for sequential songs.
	"""
	if not words:
		return [AlignedLine(lyric=ll, suggested_ts=None, confidence=0.0) for ll in lyric_lines]

	results: list[AlignedLine] = []
	cursor = 0  # minimum word index for the next alignment

	for lyric_line in lyric_lines:
		tokens = _normalize_words(lyric_line.text)
		if not tokens:
			results.append(AlignedLine(lyric=lyric_line, suggested_ts=None, confidence=0.0))
			continue

		n = len(tokens)
		best_score = -1.0
		best_pos = cursor

		# Search a generous look-ahead window (don't let the cursor pin us too tightly)
		search_end = min(len(words) - n + 1, cursor + max(n * 10, 40))
		search_start = cursor

		for i in range(search_start, search_end):
			score = _window_similarity(tokens, words, i)
			if score > best_score:
				best_score = score
				best_pos = i

		suggested_ts = words[best_pos].start if best_score > 0 else None
		# Advance cursor to just after the matched window so next line starts later
		cursor = best_pos + max(n, 1)

		results.append(
			AlignedLine(
				lyric=lyric_line, suggested_ts=suggested_ts, confidence=round(best_score, 3)
			)
		)

	return results


# ─── Output formatting ───────────────────────────────────────────────────────────


def format_lrc(
	aligned: list[AlignedLine], *, artist: str = '', title: str = '', album: str = ''
) -> str:
	"""Render aligned lines as an LRC file string with suggested timestamps."""
	header_parts = []
	if artist:
		header_parts.append(f'[ar:{artist}]')
	if title:
		header_parts.append(f'[ti:{title}]')
	if album:
		header_parts.append(f'[al:{album}]')

	body_lines = []
	for a in aligned:
		if a.suggested_ts is not None:
			body_lines.append(f'{_secs_to_lrc(a.suggested_ts)}{a.lyric.text}')
		else:
			body_lines.append(a.lyric.text)  # no timestamp available

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
		sugg_str = _secs_to_lrc(a.suggested_ts) if a.suggested_ts is not None else '(none)'

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

	has_timestamps = any(ll.original_ts is not None for ll in lyric_lines)
	console.print(
		f'  Tag [cyan]{tag_name}[/cyan]: '
		f'[bold]{len(lyric_lines)}[/bold] lines, '
		f'format: [magenta]{"LRC" if has_timestamps else "plain TXT"}[/magenta]'
	)

	# 2. Transcribe with Whisper
	with console.status(f'  Transcribing [dim]{path.name}[/dim] with Whisper…'):
		words = transcribe(path, model, transcribe_device=transcribe_device)

	if not words:
		console.print('  [red]Whisper returned no words — skipping.[/red]')
		return False

	console.print(f'  Whisper: [bold]{len(words)}[/bold] words transcribed.')

	# 3. Align
	aligned = align(lyric_lines, words)

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

	# Warn about low-confidence lines
	low_conf = [a for a in aligned if a.confidence < min_confidence]
	if low_conf:
		console.print(
			f'  [yellow]⚠ {len(low_conf)} lines have confidence < {min_confidence:.2f} '
			f'— review carefully before applying.[/yellow]'
		)

	# 7. Optionally write sidecar
	if write and not dry_run:
		out_path = path.with_suffix('.lrc.suggested')
		try:
			out_path.write_text(lrc_out, encoding='utf-8')
			console.print(f'  [green]✓ Written to[/green] {out_path.name}')
		except OSError as exc:
			console.print(f'  [red]✗ Could not write {out_path.name}: {exc}[/red]')

	return True


# ─── CLI ──────────────────────────────────────────────────────────────────────────


@click.command()
@click.argument(
	'folder', default='.', type=click.Path(exists=True, file_okay=False, path_type=Path)
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
	help='Write suggested LRC to a .lrc.suggested sidecar file next to each FLAC.',
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
def main(
	folder: Path,
	model: str,
	device: str,
	write: bool,
	dry_run: bool,
	min_confidence: float,
	recursive: bool,
) -> None:
	"""
	Align FLAC lyrics tags to Whisper speech-to-text timestamps.

	Reads LRC or plain TXT lyrics from FLAC tags, runs a local Whisper
	model to produce word-level timestamps, then aligns each lyric line
	to the best-matching span of transcribed words.

	Outputs a comparison table and a suggested LRC for each track.
	Use --write to save results as .lrc.suggested sidecar files.
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
			f'Folder: [dim]{folder}[/dim]',
			title='[bold]Startup[/bold]',
		)
	)

	# ── Load model ──────────────────────────────────────────────────────────
	with console.status(f'Loading Whisper model [bold]{model}[/bold] on [bold]{_device}[/bold]…'):
		wmodel = whisper.load_model(model, device=_device)
	console.print(f'[green]✓[/green] Model [bold]{model}[/bold] ready on {_device}.')

	# ── Discover FLAC files ────────────────────────────────────────────────
	pattern = '**/*.flac' if recursive else '*.flac'
	flac_files = sorted(folder.glob(pattern))

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
			):
				ok += 1
			progress.advance(task)

	console.print()
	console.rule()
	console.print(
		f'Done. [bold green]{ok}[/bold green] / [bold]{len(flac_files)}[/bold] file(s) aligned.'
	)
	if write and not dry_run:
		console.print('[dim]Results saved as .lrc.suggested alongside each FLAC.[/dim]')


if __name__ == '__main__':
	main()
