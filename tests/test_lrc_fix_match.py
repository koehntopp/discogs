"""Tests for lrc_fix.match_per_line / match_line_times on synthetic transcripts.

Run: uv run --with pytest --with mutagen --with rich --with structlog --with requests pytest tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lrc_fix


def transcript(text: str, start: float = 0.0, step: float = 0.5) -> list[dict]:
	return [{'w': w, 't': start + i * step} for i, w in enumerate(text.split())]


CHORUS = ['Get into the groove', 'Boy you have got to prove']


def test_repeated_chorus_takes_successive_occurrences():
	lyric = [
		'First verse line one',
		'First verse line two',
		*CHORUS,
		'Second verse is here',
		*CHORUS,
	]
	words = transcript(
		'first verse line one first verse line two get into the groove boy you have got to prove '
		'second verse is here get into the groove boy you have got to prove'
	)
	times = lrc_fix.match_per_line(lyric, words)
	assert all(t is not None for t in times)
	assert times == sorted(times)
	assert times[2] < times[5]  # the second chorus is placed after the first


def test_transcript_sections_without_text_are_skipped():
	lyric = ['Hello darkness my old friend', 'I have come to talk with you again']
	words = transcript(
		'hello darkness my old friend ooh ooh ooh ooh ooh ooh i have come to talk with you again'
	)
	times = lrc_fix.match_per_line(lyric, words)
	assert times[0] == 0.0
	assert times[1] > times[0]


def test_misheard_word_still_matches():
	lyric = ['Tonight I wanna dance with someone else']
	words = transcript('tonight i wanna dancing with someone else')
	assert lrc_fix.match_per_line(lyric, words)[0] == 0.0


def test_unsung_line_stays_unmatched_and_order_is_kept():
	lyric = ['alpha beta gamma', 'completely absent words here', 'delta epsilon zeta']
	words = transcript('alpha beta gamma delta epsilon zeta')
	times = lrc_fix.match_per_line(lyric, words)
	assert times[1] is None
	assert times[0] < times[2]


def test_combined_matcher_never_places_fewer_lines_than_the_old_one():
	lyric = ['one two three', 'four five six', 'seven eight nine']
	words = transcript('one two three four five six seven eight nine')
	old = lrc_fix.match_blocks(lyric, words)
	new = lrc_fix.match_line_times(lyric, words)
	assert sum(t is not None for t in new) >= sum(t is not None for t in old)
