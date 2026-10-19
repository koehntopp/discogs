#!/usr/bin/env -S uv run
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
#     "requests",
#     "rich",
#     "structlog",
#     "openpyxl",
# ]
# ///

"""lrc_audit.py - Why do some synced lyrics look broken: lrclib, or our tools?

Takes every track whose synced LRC looks like a failed alignment (the lrc_count.py --suspects
test, lrc_format.lrc_suspect_reasons) and compares three sources per track:

  1. the tag as it is now (text, timestamps, and the [re:] header that says lrc_fix wrote it),
  2. lrclib.net today (fetched fresh, paced as in ADR 0007 section 4),
  3. the audio, as the demucs + whisperx transcript in the lrc_fix ASR cache.

Each track gets a verdict (see classify()): the lyrics do not match the audio, the lyrics match but
the timestamps are bad at lrclib, the timestamps were broken by our own tools, and so on, plus whether
today's lrc_fix would fix it. The library is only read: lrc_fix is run with --dry-run, so no tag is
written; the only outputs are the lrc_fix cache, this tool's work directory and the reports.

Usage (everything is resumable; re-running continues where it stopped):
    ./lrc_audit.py run                  # prepare + transcribe + analyze, e.g. overnight
    ./lrc_audit.py prepare [--root DIR]
    ./lrc_audit.py transcribe [--limit N] [--offset N]
    ./lrc_audit.py analyze [--skip-lrclib] [--refetch]

Outputs: lrc_suspects_audit.csv/.xlsx (one row per track, git-ignored) and the summary
docs/lrc-suspects-audit.md. Work files live in ~/.cache/lrc_audit (--work-dir).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path

import requests
from mutagen.flac import FLAC
from openpyxl import Workbook

import lrc_fix
import update_lyrics
from lrc_format import (
	is_instrumental_marker,
	is_lrc,
	lrc_body,
	lrc_problem_line_count,
	lrc_suspect_reasons,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_WORK_DIR = Path.home() / '.cache' / 'lrc_audit'
DEFAULT_REPORT = ROOT / 'docs' / 'lrc-suspects-audit.md'
DEFAULT_OUT = ROOT / 'lrc_suspects_audit'

# Verdict thresholds (documented in the report).
MIN_WORDS = 5  # fewer transcript words than this: whisper heard (almost) nothing
MIN_WORDS_PER_MIN = 10  # fewer than this many words per minute: same
MATCH_OK = 0.6  # share of matched lines lrc_fix needs to align (its own --min-match)
BIGRAM_LOW = 0.2  # share of lyric word pairs found in the transcript: below this, not sung
BIGRAM_OK = 0.5  # at or above this the text is sung, whatever the order or structure
AUDIO_CONTINUES_SECS = 20  # transcript runs this long past the last lyric timestamp
STACKED = {'one_timestamp', 'shared_timestamps'}  # the reasons that mean "timestamps are broken"
BORDERLINE = 0.05  # report-only: a match share this close to a threshold is flagged

CATEGORY_TEXT = {
	'not_cacheable': 'cannot be cached (no numeric DISCOGS_RELEASE_ID or no TRACKNUMBER)',
	'file_missing': 'file not found',
	'not_transcribed': 'not transcribed yet (or the transcription failed)',
	'no_audio_evidence': 'whisper heard (almost) nothing: text cannot be judged',
	'text_mismatch': 'lyrics are not in the audio (under 20% of their word pairs are sung)',
	'text_partial': 'lyrics are in the audio only partly (20-50% of their word pairs)',
	'text_ok_not_alignable': 'lyrics are sung, but lrc_fix cannot align them (order or structure differs)',
	'lyrics_truncated': 'lyrics match, but the vocals go on long after the last lyric line',
	'ends_early_plausible': 'lyrics match; ends early only (likely an instrumental outro)',
	'source_junk_only': 'lyrics match; only junk characters (hearts) in the source text',
	'lrclib_bad_timestamps': 'lyrics match, timestamps stacked, lrclib has the same timestamps',
	'lrclib_bad_other_version': 'lyrics match, timestamps stacked, lrclib has stacked ones too (different)',
	'tag_worse_than_lrclib_lrc_fix': 'lyrics match, lrclib timestamps fine, tag written by lrc_fix',
	'tag_worse_than_lrclib_other': 'lyrics match, lrclib timestamps fine, tag from elsewhere',
	'timestamps_bad_source_unknown': 'lyrics match, timestamps stacked, lrclib not comparable',
}

# The report's answer to "lrclib or us?": mutually exclusive groups, in this order.
G_LRCLIB_TS = 'Likely bad input from lrclib: stacked timestamps or truncated lyrics'
G_LRCLIB_TEXT = (
	'Likely bad input from lrclib: lyrics are not (fully) in the audio, lrclib serves the same text'
)
G_OURS = 'Broken by our tools (lrclib has good timestamps)'
G_NOT_ALIGNABLE = 'Lyrics are sung, but lrc_fix cannot align them (order or structure differs)'
G_TEXT_OTHER = 'Lyrics are not (fully) in the audio, and the tag text differs from lrclib'
G_FINE = 'Probably fine (hints only)'
G_UNKNOWN = 'Cannot tell (no audio evidence, lrclib not comparable, not transcribed)'
GROUPS = [G_LRCLIB_TS, G_LRCLIB_TEXT, G_OURS, G_NOT_ALIGNABLE, G_TEXT_OTHER, G_FINE, G_UNKNOWN]


def group_of(r: dict) -> str:
	cat = r['category']
	if cat in ('lrclib_bad_timestamps', 'lrclib_bad_other_version', 'lyrics_truncated'):
		return G_LRCLIB_TS
	if cat in ('text_mismatch', 'text_partial'):
		return G_LRCLIB_TEXT if r.get('text_source') == 'lrclib_same_text' else G_TEXT_OTHER
	if cat == 'text_ok_not_alignable':
		return G_NOT_ALIGNABLE
	if cat in ('tag_worse_than_lrclib_lrc_fix', 'tag_worse_than_lrclib_other'):
		return G_OURS
	if cat in ('ends_early_plausible', 'source_junk_only'):
		return G_FINE
	return G_UNKNOWN


COLUMNS = [
	'category',
	'text_source',
	'artist',
	'album',
	'title',
	'path',
	'discogs_id',
	'disc',
	'track',
	'length',
	'tag_reasons',
	'tag_lines',
	'tag_problem_lines',
	'tag_last_ts',
	'tag_origin',
	'transcript_words',
	'words_per_min',
	'transcript_last_ts',
	'audio_continues',
	'lines_counted',
	'lines_matched',
	'line_match',
	'bigram_recall',
	'word_recall',
	'word_precision',
	'lrclib_status',
	'lrclib_instrumental',
	'lrclib_has_synced',
	'lrclib_reasons',
	'lrclib_same_timestamps',
	'lrclib_text_similarity',
	'lrclib_duration_delta',
	'fix_status',
	'fix_detail',
	'fix_remaining_reasons',
]


# ---------------------------------------------------------------------------------------------
# prepare: find the suspect tracks
# ---------------------------------------------------------------------------------------------


def tag_origin(lyrics: str) -> str:
	"""Who wrote the tag, judging from its [re:] header: lrc_fix, another tool, or nobody."""
	m = re.search(r'^\[re:(.*)\]\s*$', lyrics, re.MULTILINE)
	if not m:
		return 'no_re_tag'
	return 'lrc_fix' if 'lrc_fix' in m.group(1) else 'other_tool'


def _first(song: FLAC, key: str) -> str:
	values = song.get(key)
	return str(values[0]).strip() if values else ''


def _leading_int(value: str, default: int) -> int:
	try:
		return int(value.split('/')[0].strip())
	except ValueError:
		return default


def suspect_target(path: Path) -> dict | None:
	"""The audit record of one track if its synced LRC is suspect, else None (same test as
	lrc_count.py --suspects)."""
	try:
		song = FLAC(path)
	except Exception:  # noqa: BLE001  # an unreadable file is simply not a target
		return None
	lyrics = _first(song, 'LYRICS')
	if not lyrics or is_instrumental_marker(lyrics) or not is_lrc(lyrics):
		return None
	length = float(song.info.length) if song.info else 0.0
	reasons = lrc_suspect_reasons(lyrics, length)
	if not reasons:
		return None
	times, _ = lrc_body(lyrics)
	return {
		'path': str(path),
		'artist': _first(song, 'ALBUMARTIST') or _first(song, 'ARTIST'),
		'album': _first(song, 'ALBUM'),
		'title': _first(song, 'TITLE') or path.stem,
		'discogs_id': _first(song, 'DISCOGS_RELEASE_ID'),
		'disc': _leading_int(_first(song, 'DISCNUMBER'), 1),
		'track': _leading_int(_first(song, 'TRACKNUMBER'), 0),
		'length': length,
		'reasons': reasons,
		'lines': len(times),
		'problem_lines': lrc_problem_line_count(lyrics),
		'last_ts': times[-1] if times else 0.0,
		'origin': tag_origin(lyrics),
		'lyrics': lyrics,
	}


def scan_targets(root: Path) -> list[dict]:
	targets: list[dict] = []
	seen = 0
	for dirpath, dirs, files in os.walk(root):
		dirs.sort()
		flacs = sorted(f for f in files if f.lower().endswith('.flac'))
		if not flacs:
			continue
		for name in flacs:
			seen += 1
			target = suspect_target(Path(dirpath) / name)
			if target:
				targets.append(target)
		dirs.clear()  # an album directory is a leaf
		if seen % 500 < len(flacs):
			print(f'   scanned {seen} tracks, {len(targets)} suspects so far', flush=True)
	return targets


def targets_path(work_dir: Path) -> Path:
	return work_dir / 'targets.jsonl'


def load_targets(work_dir: Path) -> list[dict]:
	path = targets_path(work_dir)
	if not path.exists():
		sys.exit(f'no targets at {path}: run "lrc_audit.py prepare" first')
	with path.open(encoding='utf-8') as fh:
		return [json.loads(line) for line in fh if line.strip()]


def prepared_root(work_dir: Path) -> str:
	try:
		return json.loads((work_dir / 'meta.json').read_text(encoding='utf-8'))['root']
	except (OSError, ValueError, KeyError):
		return '(unknown)'


def cmd_prepare(args: argparse.Namespace) -> None:
	root = args.root
	if root is None:
		try:
			import config
		except ImportError:
			sys.exit('no --root given and config.flacroot is not available')
		root = Path(config.flacroot)
	print(f'== prepare: scanning {root} (read-only)')
	targets = scan_targets(root)
	args.work_dir.mkdir(parents=True, exist_ok=True)
	with targets_path(args.work_dir).open('w', encoding='utf-8') as fh:
		for t in targets:
			fh.write(json.dumps(t, ensure_ascii=False) + '\n')
	albums = len({str(Path(t['path']).parent) for t in targets})
	(args.work_dir / 'meta.json').write_text(
		json.dumps({'root': str(root), 'prepared': datetime.now().isoformat(timespec='seconds')}),
		encoding='utf-8',
	)
	print(f'   {len(targets)} suspect tracks in {albums} albums -> {targets_path(args.work_dir)}')


# ---------------------------------------------------------------------------------------------
# transcribe: build the lrc_fix cache by running lrc_fix --dry-run per track
# ---------------------------------------------------------------------------------------------


def lrc_fix_namespace(args: argparse.Namespace) -> argparse.Namespace:
	"""The attributes lrc_fix.cache_key reads."""
	return argparse.Namespace(
		whisper_model=args.whisper_model,
		language=args.language,
		compute_type=args.compute_type,
		no_isolate_vocals=False,
	)


def cache_state(target: dict, args: argparse.Namespace) -> tuple[str, dict | None]:
	"""('cached', payload) / ('missing', None) / ('not_cacheable', None) / ('file_missing', None)."""
	path = Path(target['path'])
	try:
		flac = FLAC(path)
	except Exception:  # noqa: BLE001  # missing or unreadable
		return 'file_missing', None
	cache_file = lrc_fix.cache_path(flac, args.cache_dir)
	if cache_file is None:
		return 'not_cacheable', None
	payload = lrc_fix.load_cache(cache_file, lrc_fix.cache_key(lrc_fix_namespace(args), flac))
	return ('cached', payload) if payload else ('missing', None)


def start_caffeinate() -> subprocess.Popen | None:
	"""Keep a Mac awake for as long as this process lives."""
	if sys.platform != 'darwin' or not shutil.which('caffeinate'):
		return None
	return subprocess.Popen(['caffeinate', '-i', '-w', str(os.getpid())])


def run_lrc_fix(path: str, args: argparse.Namespace) -> tuple[int, str, str]:
	"""lrc_fix.py --dry-run on one file, in its own process (so memory is released per track)."""
	cmd = [
		sys.executable,
		str(ROOT / 'lrc_fix.py'),
		'--dry-run',
		'--whisper-model',
		args.whisper_model,
		'--device',
		args.device,
		'--compute-type',
		args.compute_type,
		'--jobs',
		str(args.jobs),
		'--cache-dir',
		str(args.cache_dir),
	]
	if args.language:
		cmd += ['--language', args.language]
	cmd.append(path)
	try:
		proc = subprocess.run(
			cmd, capture_output=True, text=True, timeout=args.timeout, check=False
		)
	except subprocess.TimeoutExpired:
		return -1, '', f'timed out after {args.timeout} s'
	return proc.returncode, proc.stdout, proc.stderr


def status_lines(stdout: str) -> list[str]:
	"""lrc_fix's own progress lines (indented), not the LRC it prints."""
	return [line.strip() for line in stdout.splitlines() if line.startswith('   ')]


def cmd_transcribe(args: argparse.Namespace) -> None:
	targets = load_targets(args.work_dir)
	subset = targets[args.offset : (args.offset + args.limit) if args.limit else None]
	todo = []
	counts: Counter[str] = Counter()
	for t in subset:
		state, _ = cache_state(t, args)
		counts[state] += 1
		if state == 'missing':
			todo.append(t)
	print(
		f'== transcribe: {len(subset)} tracks, {counts["cached"]} already cached, '
		f'{counts["not_cacheable"]} not cacheable, {counts["file_missing"]} missing, '
		f'{len(todo)} to do'
	)
	if not todo:
		return
	awake = None if args.no_caffeinate else start_caffeinate()
	args.work_dir.mkdir(parents=True, exist_ok=True)
	log = (args.work_dir / 'transcribe.log').open('a', encoding='utf-8')
	failed_path = args.work_dir / 'failed.txt'
	started = time.monotonic()
	failed = 0
	try:
		for i, t in enumerate(todo, 1):
			t0 = time.monotonic()
			label = f'{t["artist"]} - {t["title"]}'
			print(f'[{i}/{len(todo)}] {label}', flush=True)
			rc, out, err = run_lrc_fix(t['path'], args)
			log.write(f'=== {datetime.now().isoformat(timespec="seconds")} rc={rc} {t["path"]}\n')
			log.write(out + '\n' + err[-4000:] + '\n')
			log.flush()
			for line in status_lines(out):
				print(f'     {line}')
			state, _ = cache_state(t, args)
			if rc != 0 or state != 'cached':
				failed += 1
				why = err.strip().splitlines()[-1] if err.strip() else f'rc={rc}, no cache written'
				print(f'     FAILED: {why}')
				with failed_path.open('a', encoding='utf-8') as fh:
					fh.write(f'{t["path"]}\t{why}\n')
			elapsed = time.monotonic() - started
			eta = elapsed / i * (len(todo) - i)
			print(f'     {time.monotonic() - t0:.0f} s; eta {eta / 3600:.1f} h', flush=True)
	except KeyboardInterrupt:
		print('interrupted; run again to continue (finished tracks are cached)')
		sys.exit(130)
	finally:
		log.close()
		if awake:
			awake.terminate()
	print(f'== transcribe done: {len(todo) - failed} ok, {failed} failed (see {failed_path})')


# ---------------------------------------------------------------------------------------------
# analyze: lrclib, metrics, verdicts
# ---------------------------------------------------------------------------------------------


def tokens(lines: list[str]) -> list[str]:
	return [tok for line in lines for tok in lrc_fix._tokenize(line)]


def similarity(a_lines: list[str], b_lines: list[str]) -> float | None:
	a, b = tokens(a_lines), tokens(b_lines)
	if not a and not b:
		return None
	return SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def asr_tokens(words: list[dict]) -> list[str]:
	"""One token per transcript word (the first, as lrc_fix.match_line_times does)."""
	out = []
	for w in words:
		toks = lrc_fix._tokenize(w['w'])
		if toks:
			out.append(toks[0])
	return out


def bigram_recall(lyric_lines: list[str], words: list[dict]) -> float | None:
	"""Share of the lyric's consecutive word pairs that occur anywhere in the transcript.

	Unlike the line match it ignores order and structure, so repeated sections, a shuffled
	line order or interleaved backing vocals ("ooh") do not hide the fact that the text is sung.
	"""
	lyric, asr = tokens(lyric_lines), asr_tokens(words)
	if len(lyric) < 2 or len(asr) < 2:
		return None
	heard = set(pairwise(asr))
	pairs = list(pairwise(lyric))
	return sum(p in heard for p in pairs) / len(pairs)


def word_stats(lyric_lines: list[str], words: list[dict]) -> tuple[float | None, float | None]:
	"""(recall, precision) of the lyric tokens against the transcript tokens."""
	asr, lyric = asr_tokens(words), tokens(lyric_lines)
	if not asr or not lyric:
		return None, None
	blocks = SequenceMatcher(a=asr, b=lyric, autojunk=False).get_matching_blocks()
	matched = sum(b.size for b in blocks)
	return matched / len(lyric), matched / len(asr)


def line_match(lyric_lines: list[str], raw_times: list[float | None]) -> tuple[int, int]:
	"""(lines counted, lines matched), counting only lines that contain a word (like the gate)."""
	counted = [t for line, t in zip(lyric_lines, raw_times) if lrc_fix._tokenize(line)]
	return len(counted), sum(t is not None for t in counted)


def simulate_fix(
	lyric_lines: list[str],
	raw_times: list[float | None],
	onsets: list[float] | None,
	length: float,
	min_match: float = MATCH_OK,
) -> tuple[str, str, list[str]]:
	"""What the current lrc_fix would do: ('fixed'|'rejected', why, remaining suspect reasons)."""
	why = lrc_fix.alignment_rejection(lyric_lines, raw_times, min_match)
	if why:
		return 'rejected', why, []
	times = lrc_fix.finalize_times(raw_times, onsets or [], length or None)
	new_lrc = lrc_fix.build_lrc([], lyric_lines, times)
	reasons = lrc_suspect_reasons(new_lrc, length)
	broken = [r for r in reasons if r in STACKED]
	if broken:
		return 'rejected', 'result would have ' + ' and '.join(broken), reasons
	return 'fixed', '', reasons


def classify(r: dict) -> tuple[str, str]:
	"""(category, text_source) for one analysed track. See the report for the rules."""
	text_source = ''
	if r.get('pre_category'):
		return r['pre_category'], text_source
	if r.get('lrclib_status') == 'found':
		sim = r.get('lrclib_text_similarity')
		text_source = (
			'lrclib_same_text' if sim is not None and sim >= 0.9 else 'differs_from_lrclib'
		)
	words, wpm = r['transcript_words'], r['words_per_min']
	match, bigrams = r['line_match'], r['bigram_recall']
	if words < MIN_WORDS or wpm < MIN_WORDS_PER_MIN or bigrams is None:
		return 'no_audio_evidence', text_source
	if bigrams < BIGRAM_LOW:
		return 'text_mismatch', text_source
	if bigrams < BIGRAM_OK:
		return 'text_partial', text_source
	if match is None or match < MATCH_OK:
		return 'text_ok_not_alignable', text_source
	tag_reasons = set(r['tag_reasons'])
	if not tag_reasons & STACKED:
		if 'ends_early' in tag_reasons:
			if r['audio_continues']:
				return 'lyrics_truncated', text_source
			return 'ends_early_plausible', text_source
		return 'source_junk_only', text_source
	if r['lrclib_status'] != 'found' or not r['lrclib_has_synced']:
		return 'timestamps_bad_source_unknown', text_source
	if set(r['lrclib_reasons']) & STACKED:
		same = r['lrclib_same_timestamps']
		return ('lrclib_bad_timestamps' if same else 'lrclib_bad_other_version'), text_source
	if r['tag_origin'] == 'lrc_fix':
		return 'tag_worse_than_lrclib_lrc_fix', text_source
	return 'tag_worse_than_lrclib_other', text_source


def lrclib_path(work_dir: Path, track_path: str) -> Path:
	digest = hashlib.sha1(track_path.encode('utf-8')).hexdigest()[:16]
	return work_dir / 'lrclib' / f'{digest}.json'


def fetch_lrclib(targets: list[dict], args: argparse.Namespace) -> dict[str, dict]:
	"""Fresh lrclib answer per track, cached on disk. Same lookup order as update_lyrics."""
	session = requests.Session()
	pacer = update_lyrics.Pacer()
	out: dict[str, dict] = {}
	fetched = 0
	for i, t in enumerate(targets, 1):
		cache = lrclib_path(args.work_dir, t['path'])
		if cache.exists() and not args.refetch:
			out[t['path']] = json.loads(cache.read_text(encoding='utf-8'))
			continue
		title = t['title']
		stripped = update_lyrics.strip_trailing_bracket(title)
		names = [title] if stripped == title else [title, stripped]
		duration = str(round(t['length']))
		variants = [
			v
			for name in names
			for v in (
				{
					'artist_name': t['artist'],
					'track_name': name,
					'album_name': t['album'],
					'duration': duration,
				},
				{'artist_name': t['artist'], 'track_name': name, 'duration': duration},
			)
		]
		entry = {'status': 'not_found', 'body': {}, 'fetched': datetime.now().isoformat()}
		for params in variants:
			body = update_lyrics._lrclib_get(session, pacer, params, title)
			if body is None:
				entry['status'] = 'error'
				break
			if body:
				entry = {'status': 'found', 'body': body, 'fetched': entry['fetched']}
				break
		if entry['status'] != 'error':  # an error is retried by the next analyze
			cache.parent.mkdir(parents=True, exist_ok=True)
			cache.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
		out[t['path']] = entry
		fetched += 1
		if fetched % 25 == 0:
			print(f'   lrclib: {i}/{len(targets)}', flush=True)
	return out


def same_times(a: list[float], b: list[float]) -> bool:
	return len(a) == len(b) and all(abs(x - y) < 0.011 for x, y in zip(a, b))


def compare_lrclib(t: dict, entry: dict | None) -> dict:
	"""The lrclib-derived columns for one track."""
	res = {
		'lrclib_status': entry['status'] if entry else 'skipped',
		'lrclib_instrumental': '',
		'lrclib_has_synced': False,
		'lrclib_reasons': [],
		'lrclib_same_timestamps': None,
		'lrclib_text_similarity': None,
		'lrclib_duration_delta': None,
	}
	if not entry or entry['status'] != 'found':
		return res
	body = entry['body']
	res['lrclib_instrumental'] = bool(body.get('instrumental'))
	if body.get('duration') is not None:
		res['lrclib_duration_delta'] = round(abs(float(body['duration']) - t['length']), 1)
	synced = re.sub(r'\[(\d{2}:\d{2}\.\d{2})\d\]', r'[\1]', body.get('syncedLyrics') or '')
	plain = body.get('plainLyrics') or ''
	tag_times, tag_texts = lrc_body(t['lyrics'])
	if synced:
		l_times, l_texts = lrc_body(synced)
		res['lrclib_has_synced'] = True
		res['lrclib_reasons'] = lrc_suspect_reasons(synced, t['length'])
		res['lrclib_same_timestamps'] = same_times(tag_times, l_times)
		res['lrclib_text_similarity'] = similarity(tag_texts, l_texts)
	elif plain:
		res['lrclib_text_similarity'] = similarity(tag_texts, plain.splitlines())
	return res


def analyze_target(t: dict, args: argparse.Namespace, entry: dict | None) -> dict:
	row = {
		'artist': t['artist'],
		'album': t['album'],
		'title': t['title'],
		'path': t['path'],
		'discogs_id': t['discogs_id'],
		'disc': t['disc'],
		'track': t['track'],
		'length': round(t['length'], 1),
		'tag_reasons': t['reasons'],
		'tag_lines': t['lines'],
		'tag_problem_lines': t['problem_lines'],
		'tag_last_ts': round(t['last_ts'], 1),
		'tag_origin': t['origin'],
		**compare_lrclib(t, entry),
	}
	state, payload = cache_state(t, args)
	if payload is None:
		row['pre_category'] = {'missing': 'not_transcribed'}.get(state, state)
		row['category'], row['text_source'] = classify(row)
		return row
	words = payload['words']
	_, lyric_lines = lrc_fix.strip_lyric_lines(t['lyrics'])
	raw_times = lrc_fix.match_line_times(lyric_lines, words)
	counted, matched = line_match(lyric_lines, raw_times)
	recall, precision = word_stats(lyric_lines, words)
	length = t['length']
	last_word = words[-1]['t'] if words else 0.0
	fix_status, fix_detail, remaining = simulate_fix(
		lyric_lines, raw_times, payload.get('onsets'), length
	)
	row.update(
		{
			'transcript_words': len(words),
			'words_per_min': round(len(words) / (length / 60), 1) if length else 0.0,
			'transcript_last_ts': round(last_word, 1),
			'audio_continues': last_word > t['last_ts'] + AUDIO_CONTINUES_SECS,
			'lines_counted': counted,
			'lines_matched': matched,
			'line_match': (matched / counted) if counted else None,
			'bigram_recall': bigram_recall(lyric_lines, words),
			'word_recall': recall,
			'word_precision': precision,
			'fix_status': fix_status,
			'fix_detail': fix_detail,
			'fix_remaining_reasons': remaining,
		}
	)
	row['category'], row['text_source'] = classify(row)
	return row


def cell(value: object) -> object:
	if isinstance(value, list):
		return '; '.join(str(v) for v in value)
	if isinstance(value, float):
		return round(value, 3)
	return '' if value is None else value


def write_tables(rows: list[dict], out_base: Path) -> None:
	records = [[cell(r.get(c)) for c in COLUMNS] for r in rows]
	with out_base.with_suffix('.csv').open('w', newline='', encoding='utf-8') as fh:
		writer = csv.writer(fh)
		writer.writerow(COLUMNS)
		writer.writerows(records)
	wb = Workbook()
	ws = wb.active
	ws.append(COLUMNS)
	for rec in records:
		ws.append(rec)
	wb.save(out_base.with_suffix('.xlsx'))


def pct(n: int, total: int) -> str:
	return f'{n / total:.0%}' if total else '-'


def md_cell(text: object) -> str:
	return str(text).replace('|', '\\|').replace('\n', ' ')


def build_report(rows: list[dict], meta: dict) -> str:
	total = len(rows)
	by_cat = Counter(r['category'] for r in rows)
	fixable = Counter(r['category'] for r in rows if r.get('fix_status') == 'fixed')
	n_fixed = sum(1 for r in rows if r.get('fix_status') == 'fixed')
	shown = [c for c in CATEGORY_TEXT if by_cat[c]]
	intro = (
		f'Generated by `lrc_audit.py` on {meta["date"]}. Library: `{meta["root"]}`. '
		f'{total} suspect tracks in {meta["albums"]} albums (the `lrc_count.py --suspects` test); '
		f'lrclib queried: {meta["lrclib"]}.'
	)
	question = (
		'The question: is a suspect `LYRICS` tag bad because lrclib supplied bad input, because our '
		'own tools broke it, or can it not be told? Each track is compared against three sources: '
		'the tag, lrclib today, and a demucs + whisperx transcript of the audio (the `lrc_fix` ASR '
		'cache). The verdicts are heuristics, not proof; the rules are at the end.'
	)
	lines = [
		'# lrc suspects audit',
		'',
		intro,
		'',
		question,
		'',
		'## Bottom line',
		'',
		'| Group | Tracks | Share |',
		'|---|---:|---:|',
	]
	by_group = Counter(group_of(r) for r in rows)
	for name in GROUPS:
		lines.append(f'| {name} | {by_group[name]} | {pct(by_group[name], total)} |')
	lines += [
		'',
		(
			'The groups add up to the total. "Lyrics do not match the audio" can also mean that '
			'whisper failed on that track (quiet, processed or non-English vocals), so those two '
			'groups are an upper bound for wrong lyrics.'
		),
		'',
		(
			f"Today's `lrc_fix` would write a non-suspect result for **{n_fixed}** of {total} tracks "
			'(it passes its own quality gate and the result has no stacked timestamps).'
		),
		'',
		'## Verdicts',
		'',
		'| Category | Meaning | Tracks | Share | Fixable by lrc_fix |',
		'|---|---|---:|---:|---:|',
	]
	for cat in shown:
		lines.append(
			f'| `{cat}` | {CATEGORY_TEXT[cat]} | {by_cat[cat]} | {pct(by_cat[cat], total)} '
			f'| {fixable[cat]} |'
		)
	lines += ['', '## By suspect reason (a track can have several)', '']
	lines.append('| Reason | Tracks | ' + ' | '.join(f'`{c}`' for c in shown) + ' |')
	lines.append('|---|---:|' + '---:|' * len(shown))
	for reason in sorted({x for r in rows for x in r['tag_reasons']}):
		sub = [r for r in rows if reason in r['tag_reasons']]
		cnt = Counter(r['category'] for r in sub)
		lines.append(
			f'| `{reason}` | {len(sub)} | ' + ' | '.join(str(cnt[c]) for c in shown) + ' |'
		)
	lines += [
		'',
		'## By who wrote the tag',
		'',
		'| Origin (`[re:]` header) | Tracks | Fixable |',
		'|---|---:|---:|',
	]
	for origin, n in Counter(r['tag_origin'] for r in rows).most_common():
		fx = sum(1 for r in rows if r['tag_origin'] == origin and r.get('fix_status') == 'fixed')
		lines.append(f'| `{origin}` | {n} | {fx} |')
	border = [
		r
		for r in rows
		if r.get('bigram_recall') is not None
		and any(abs(r['bigram_recall'] - t) <= BORDERLINE for t in (BIGRAM_LOW, BIGRAM_OK))
	]
	rules = [
		(
			f'`no_audio_evidence`: under {MIN_WORDS} transcript words, or under '
			f'{MIN_WORDS_PER_MIN} words per minute.'
		),
		(
			"Is the text sung at all? Bigram recall = share of the lyric's consecutive word pairs that "
			'occur anywhere in the transcript, independent of order, so repeats, a shuffled line order '
			f'and backing vocals do not matter: under {BIGRAM_LOW:.0%} `text_mismatch`, under '
			f'{BIGRAM_OK:.0%} `text_partial`. {len(border)} tracks lie within {BORDERLINE:.0%} of a '
			'threshold (see the distribution below).'
		),
		(
			f'Sung, but fewer than {MATCH_OK:.0%} of the word-bearing lines match the transcript in order '
			"(the quality gate's own number, `--min-match`): `text_ok_not_alignable`. The words are "
			'there, but `lrc_fix` aligns monotonically and cannot place them.'
		),
		(
			'Otherwise the text is sung and alignable. If the tag has no stacked timestamps '
			'(`one_timestamp`/`shared_timestamps`): `lyrics_truncated` when the transcript runs more '
			f'than {AUDIO_CONTINUES_SECS} s past the last lyric timestamp, else `ends_early_plausible`, '
			'else `source_junk_only`.'
		),
		(
			'With stacked timestamps, lrclib decides: no synced lyrics there is '
			'`timestamps_bad_source_unknown`; lrclib stacked too is `lrclib_bad_timestamps` (identical '
			'timestamps) or `lrclib_bad_other_version`; lrclib fine means our tools wrote it '
			'(`tag_worse_than_lrclib_lrc_fix` if the tag has a `lrc_fix` `[re:]` header, otherwise '
			'`..._other`, which also covers an older lrclib version).'
		),
		(
			'"Fixable" = today\'s `lrc_fix` passes its gate on the cached transcript and the result '
			'has no stacked timestamps (onsets as cached; tracks gated out earlier have none).'
		),
	]
	buckets = Counter(
		min(int(r['bigram_recall'] * 10), 9) for r in rows if r.get('bigram_recall') is not None
	)
	lines += [
		'',
		'## Distribution of bigram recall (how much of the lyric is sung)',
		'',
		'| Share of lyric word pairs found in the transcript | Tracks |',
		'|---|---:|',
	]
	for b in range(10):
		hi = f'{(b + 1) * 10}%' if b < 9 else '100%'
		lines.append(f'| {b * 10}% to {hi} | {buckets[b]} |')
	lines += ['', '## Rules and thresholds', ''] + [f'- {rule}' for rule in rules] + ['']
	lines += ['## Examples', '']
	for cat in shown:
		sample = [r for r in rows if r['category'] == cat][:5]
		lines += [
			f'**`{cat}`**',
			'',
			'| Artist - title | Line match | lrclib | Fix |',
			'|---|---:|---|---|',
		]
		for r in sample:
			lm = '-' if r.get('line_match') is None else f'{r["line_match"]:.0%}'
			lines.append(
				f'| {md_cell(r["artist"])} - {md_cell(r["title"])} | {lm} '
				f'| {r["lrclib_status"]} | {r.get("fix_status", "-")} |'
			)
		lines.append('')
	caveats = [
		(
			'whisper `medium` can miss quiet, heavily processed or non-English vocals; those land in '
			'`no_audio_evidence`/`text_mismatch` although the lyrics may be right.'
		),
		(
			'The tags are audited as they were when `prepare` ran; lrclib data is as of the fetch date '
			'(cached in the work directory, `--refetch` renews it).'
		),
		(
			'`[re:]` only says who wrote the tag last; a manual edit or an older lrclib version looks '
			'the same as `update_lyrics` output.'
		),
		'Per-track results: `lrc_suspects_audit.csv`/`.xlsx` in the repository root (git-ignored).',
	]
	lines += ['## Caveats', ''] + [f'- {c}' for c in caveats] + ['']
	return '\n'.join(lines)


def cmd_analyze(args: argparse.Namespace) -> None:
	targets = load_targets(args.work_dir)
	print(f'== analyze: {len(targets)} tracks')
	entries: dict[str, dict] = {}
	if not args.skip_lrclib:
		print('   fetching lrclib (cached per track; one request at a time)')
		entries = fetch_lrclib(targets, args)
	rows = [analyze_target(t, args, entries.get(t['path'])) for t in targets]
	write_tables(rows, args.out)
	albums = len({str(Path(t['path']).parent) for t in targets})
	meta = {
		'date': datetime.now().strftime('%Y-%m-%d'),
		'root': prepared_root(args.work_dir),
		'albums': albums,
		'lrclib': 'no (skipped)' if args.skip_lrclib else 'yes',
	}
	args.report.parent.mkdir(parents=True, exist_ok=True)
	args.report.write_text(build_report(rows, meta), encoding='utf-8')
	by_cat = Counter(r['category'] for r in rows)
	for cat, n in by_cat.most_common():
		print(f'   {n:4d}  {cat}')
	print(f'   report: {args.report}\n   tables: {args.out}.csv / .xlsx')


def cmd_run(args: argparse.Namespace) -> None:
	if args.reuse_targets and targets_path(args.work_dir).exists():
		print(f'== prepare: reusing {targets_path(args.work_dir)}')
	else:
		cmd_prepare(args)
	cmd_transcribe(args)
	cmd_analyze(args)


# ---------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
	common = argparse.ArgumentParser(add_help=False)
	common.add_argument('--work-dir', type=Path, default=DEFAULT_WORK_DIR)
	common.add_argument('--root', type=Path, default=None, help='library root (default flacroot)')
	common.add_argument('--whisper-model', default='medium')
	common.add_argument('--language', default=None)
	common.add_argument('--device', default='cpu')
	common.add_argument('--compute-type', default='int8')
	common.add_argument('--jobs', type=int, default=min(4, os.cpu_count() or 1))
	common.add_argument('--cache-dir', type=Path, default=lrc_fix.DEFAULT_CACHE_DIR)
	common.add_argument('--timeout', type=int, default=3600, help='seconds per track')
	common.add_argument('--limit', type=int, default=0, help='transcribe at most N tracks')
	common.add_argument('--offset', type=int, default=0, help='skip the first N targets')
	common.add_argument('--no-caffeinate', action='store_true')
	common.add_argument('--skip-lrclib', action='store_true')
	common.add_argument('--refetch', action='store_true', help='ignore cached lrclib answers')
	common.add_argument('--reuse-targets', action='store_true', help='run: keep existing targets')
	common.add_argument('--report', type=Path, default=DEFAULT_REPORT)
	common.add_argument(
		'--out', type=Path, default=DEFAULT_OUT, help='CSV/XLSX path without suffix'
	)
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
	sub = parser.add_subparsers(dest='command', required=True)
	for name, func in (
		('prepare', cmd_prepare),
		('transcribe', cmd_transcribe),
		('analyze', cmd_analyze),
		('run', cmd_run),
	):
		sub.add_parser(name, parents=[common]).set_defaults(func=func)
	return parser


def main() -> int:
	args = build_parser().parse_args()
	args.func(args)
	return 0


if __name__ == '__main__':
	sys.exit(main())
