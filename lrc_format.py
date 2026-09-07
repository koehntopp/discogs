"""lrc_format.py — Shared LRC id-tag/header formatting.

Used by update_lyrics.py and lrc_fix.py so their embedded LYRICS tag output
stays byte-identical — neither tool should ever perpetually "fix" a file the
other just wrote. lrc_count.py imports the constants it needs for
classification.

Pure string-in/string-out: no mutagen/FLAC dependency. Each caller owns its
own FLAC tag reads and passes plain strings in.
"""

import re

LRC_TIMESTAMP = re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')  # valid: [MM:SS.xx]
LRC_BAD_TS = re.compile(r'\[\d{3,}:\d{2}:\d{2}\.\d{2}\]')  # invalid: [HH:MM:SS.xx]
ID_TAG_LINE = re.compile(r'^\[([a-zA-Z]{2,20}):.*\]\s*$')
LRC_LINE = re.compile(r'^(\[\d{2}:\d{2}\.\d{2}\])(.*)$')
MANAGED_HEADER_KEYS = ('ar', 'ti', 'al', 'length')
INSTRUMENTAL_MARKER = '[instrumental:true]'
MANUAL_INSTRUMENTAL_MARKER = re.compile(
	r'\[\d{2}:\d{2}\.\d{2}\]\s*(?:\[instrumental\]|\(instrumental\))', re.IGNORECASE
)
BARE_INSTRUMENTAL_PLACEHOLDER = re.compile(r'^[\[(]?\s*instrumental\s*[\])]?$', re.IGNORECASE)
LA_OR_INSTRUMENTAL_TAG = re.compile(r'^\[(la|instrumental):', re.IGNORECASE)
INSTRUMENTAL_SUFFIX_LINES = ('[la:zxx]', '[instrumental:true]', '[00:00.00](Instrumental)')


def is_lrc(text: str) -> bool:
	return bool(LRC_TIMESTAMP.search(text))


def is_invalid_lrc(text: str) -> bool:
	return bool(LRC_BAD_TS.search(text))


def resolve_artist(albumartist: str, artist: str) -> str:
	"""The one place both tools decide which tag supplies 'the artist' —
	ALBUMARTIST, falling back to ARTIST only when ALBUMARTIST is empty.
	See ADR 0002 §6: a track's own ARTIST can carry rip-specific billing
	(e.g. 'Roy Orbison With Guests') that lrclib.net's artist index won't
	match, and that two independent copies of this exact fallback silently
	diverged is why this module exists.
	"""
	return albumartist or artist


def make_headers(artist: str, title: str, album: str, length_secs: float) -> str:
	mins, secs = divmod(int(length_secs), 60)
	return f'[ar:{artist}]\n[ti:{title}]\n[al:{album}]\n[length:{mins:02d}:{secs:02d}]\n'


def refresh_headers(
	lines: list[str], artist: str, title: str, album: str, length_secs: float
) -> list[str]:
	"""Refresh ar/ti/al/length header lines wherever they already sit in `lines`
	(any other line — lyric body, or a header key this module doesn't manage,
	e.g. [re:]/[by:]/[offset:] — passes through completely unchanged, at its
	original position; a fixed output order would make a tag merely sitting in
	a different position than this run would generate look like a content
	change and force a rewrite for nothing).

	A fresh value is only applied when it's non-empty — an empty value falls
	back to whatever line was already there rather than ever writing a blank
	header over a previously-good one. Any of ar/ti/al/length missing entirely
	is inserted at the top, in that order, but only when a fresh value for it
	actually exists.
	"""
	mins, secs = divmod(int(length_secs), 60) if length_secs else (0, 0)
	fresh = {
		'ar': artist,
		'ti': title,
		'al': album,
		'length': f'{mins:02d}:{secs:02d}' if length_secs else '',
	}
	seen = set()
	out = []
	for line in lines:
		m = ID_TAG_LINE.match(line)
		key = m.group(1).lower() if m else None
		if key in fresh:
			seen.add(key)
			out.append(f'[{key}:{fresh[key]}]' if fresh[key] else line)
		else:
			out.append(line)
	missing = [k for k in MANAGED_HEADER_KEYS if k not in seen and fresh[k]]
	if missing:
		out = [f'[{k}:{fresh[k]}]' for k in missing] + out
	return out


def apply_headers(lrc: str, artist: str, title: str, album: str, length_secs: float) -> str:
	lines = refresh_headers(lrc.splitlines(), artist, title, album, length_secs)
	return '\n'.join(line for line in lines if line).strip()


def build_instrumental_marker(id_tags: list[str]) -> str:
	"""Append the canonical instrumental block to id_tags, stripping any
	pre-existing la:/instrumental: lines first so this is idempotent rather
	than duplicating the sentinel on a file that's already canonically marked.
	Any other header line already in id_tags (e.g. [re:]) is preserved.
	"""
	filtered = [line for line in id_tags if not LA_OR_INSTRUMENTAL_TAG.match(line)]
	return '\n'.join([*filtered, *INSTRUMENTAL_SUFFIX_LINES])


def make_instrumental_lrc(artist: str, title: str, album: str, length_secs: float) -> str:
	"""Build the full canonical instrumental marker from scratch — ar/ti/al/length
	plus the instrumental block — for a track with no existing header lines to
	preserve. For refreshing an already-parsed id_tags list in place instead
	(preserving lines this module doesn't manage), use build_instrumental_marker.
	"""
	header_lines = make_headers(artist, title, album, length_secs).strip().splitlines()
	return build_instrumental_marker(header_lines)


def is_instrumental_marker(text: str) -> bool:
	return INSTRUMENTAL_MARKER in text


def has_manual_instrumental_marker(text: str) -> bool:
	"""Detect an informal instrumental marker a human (or another tool) left behind:
	'[00:00.00][Instrumental]' (hand-typed) or a bare '[00:00.00](Instrumental)' line
	missing the '[la:zxx]'/'[instrumental:true]' sentinel that makes it canonical.

	Distinct from the canonical '[instrumental:true]' block, which is always written
	in full — this catches anything that looks like someone's intent to mark a track
	instrumental without actually being the real sentinel.
	"""
	return bool(MANUAL_INSTRUMENTAL_MARKER.search(text))


def is_bare_instrumental_placeholder(lyric_lines: list[str]) -> bool:
	"""True if the tag is just a placeholder like 'Instrumental'/'[Instrumental]' —
	a single line, no timestamp at all. Distinct from has_manual_instrumental_marker,
	which requires an existing [MM:SS.xx] timestamp; this catches the earlier,
	pre-LRC-structure case (e.g. a plain LYRICS=Instrumental tag).
	"""
	return len(lyric_lines) == 1 and bool(BARE_INSTRUMENTAL_PLACEHOLDER.match(lyric_lines[0]))


def capitalize_line(text: str) -> str:
	"""Uppercase the first non-whitespace character of a line, preserving leading whitespace."""
	m = re.match(r'^(\s*)(\S)(.*)$', text, re.DOTALL)
	return m.group(1) + m.group(2).upper() + m.group(3) if m else text


def capitalize_lrc(lrc: str) -> str:
	"""Strip whitespace after each [MM:SS.xx] timestamp and capitalize the lyric text.

	Header lines ([ar:..], [ti:..], etc.) don't match LRC_LINE and pass through untouched.
	"""
	out = []
	for line in lrc.splitlines():
		m = LRC_LINE.match(line)
		out.append(m.group(1) + capitalize_line(m.group(2).lstrip()) if m else line)
	return '\n'.join(out)


def capitalize_txt(text: str) -> str:
	return '\n'.join(capitalize_line(line) for line in text.splitlines())
