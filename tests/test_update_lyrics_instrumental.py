"""update_lyrics: a lone LYRICS_LANGUAGE=zxx marks plain-text/empty tags instrumental without lrclib.

Run: uv run --with pytest --with mutagen --with rich --with structlog --with requests pytest tests
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import update_lyrics


def test_only_a_lone_zxx_counts():
	assert update_lyrics.is_instrumental_language(['zxx'])
	assert update_lyrics.is_instrumental_language([' ZXX '])
	assert not update_lyrics.is_instrumental_language(['zxx', 'eng'])
	assert not update_lyrics.is_instrumental_language(['mul'])
	assert not update_lyrics.is_instrumental_language([])


def fetch(lyrics: str, languages: list[str]) -> tuple:
	tags = {
		'ALBUMARTIST': ['Artist'],
		'TITLE': ['Song'],
		'ALBUM': ['Album'],
		'LYRICS': [lyrics] if lyrics else [],
		'LYRICS_LANGUAGE': languages,
	}

	class Song(update_lyrics.FLAC):
		def __init__(self, _path: str) -> None:  # no file: only tags and info are read
			self.tags = tags

		@property
		def info(self) -> mock.Mock:
			return mock.Mock(length=100.0)

	session = mock.Mock()
	with (
		mock.patch.object(update_lyrics.os.path, 'isfile', return_value=True),
		mock.patch.object(update_lyrics, 'FLAC', Song),
		mock.patch.object(update_lyrics, '_lrclib_get', return_value={}) as get,
	):
		result = update_lyrics._fetch_one('x.flac', session, mock.Mock())
	return result, get


def test_empty_and_plain_text_get_the_marker_without_a_request():
	for lyrics in ('', 'just some words'):
		result, get = fetch(lyrics, ['zxx'])
		assert result[4:6] == ('instrumental', 'new')
		assert '[instrumental:true]' in result[3]
		get.assert_not_called()


def test_synced_lrc_is_left_alone():
	lrc = '[00:01.00]Hello\n[00:05.00]World'
	result, get = fetch(lrc, ['zxx'])
	assert result[4] == 'lrc'
	assert '[instrumental:true]' not in result[3]
	get.assert_not_called()


def test_other_languages_still_ask_lrclib():
	for languages in (['eng'], ['zxx', 'eng'], []):
		_result, get = fetch('', languages)
		get.assert_called()
