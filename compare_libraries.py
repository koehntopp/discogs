#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
# 	"mutagen",
# 	"structlog",
# ]
# ///

import argparse
import csv
import os
import re
from pathlib import Path

from mutagen.flac import FLAC

from log import logger

try:
	from config import flacroot as default_target
except ImportError:
	default_target = '.'


def normalize_text(text: str) -> str:
	"""Normalize string for fuzzy title/artist matching."""
	return re.sub(r'[\W_]+', '', text.lower())


def get_tag(tags: dict[str, list[str]], key: str) -> str:
	"""Extract clean string value for a tag key."""
	val = tags.get(key, [''])
	return val[0].strip() if val and val[0] else ''


def scan_album_directories(root: str) -> list[dict]:
	"""Walk directory tree and extract album identities and FLAC counts."""
	root_path = Path(root).resolve()
	albums = []
	for dirpath, _, files in os.walk(root_path):
		flacs = sorted(f for f in files if f.endswith('.flac'))
		if not flacs:
			continue

		first_flac = os.path.join(dirpath, flacs[0])
		tags: dict[str, list[str]] = {}
		try:
			audio = FLAC(first_flac)
			tags = (
				{k.upper(): [str(x) for x in v] for k, v in audio.tags.items()}
				if audio.tags
				else {}
			)
		except Exception as e:  # noqa: BLE001
			logger.warning(f'Could not read FLAC tags from {first_flac}: {e}')

		discogs_id = get_tag(tags, 'DISCOGS_RELEASE_ID')
		mb_id = get_tag(tags, 'MUSICBRAINZ_ALBUMID')
		orig_filename = get_tag(tags, 'ORIGINAL FILENAME') or get_tag(tags, 'ORIGINAL_FILENAME')
		artist = (
			get_tag(tags, 'ALBUM_ARTIST_OVERRIDE')
			or get_tag(tags, 'ALBUMARTIST')
			or get_tag(tags, 'ARTIST')
		)
		album = (
			get_tag(tags, 'ALBUM_TITLE_OVERRIDE')
			or get_tag(tags, 'ALBUM_MASTER_TITLE')
			or get_tag(tags, 'ORIGINAL_TITLE')
			or get_tag(tags, 'ALBUM')
		)

		rel_path = os.path.relpath(dirpath, root_path)

		albums.append(
			{
				'rel_path': rel_path,
				'abs_path': dirpath,
				'track_count': len(flacs),
				'discogs_id': discogs_id,
				'mb_id': mb_id,
				'orig_filename': orig_filename,
				'artist': artist,
				'album': album,
			}
		)
	return albums


def build_album_key(album: dict) -> str:
	"""Generate a unique identity key for an album (Discogs ID > MB ID > OrigFilename > Artist/Album > RelPath)."""
	if album['discogs_id']:
		return f'discogs:{album["discogs_id"]}'
	if album['mb_id']:
		return f'mb:{album["mb_id"]}'
	if album['orig_filename']:
		return f'origfn:{normalize_text(album["orig_filename"])}'
	if album['artist'] and album['album']:
		norm_artist = normalize_text(album['artist'])
		norm_album = normalize_text(album['album'].split(' [')[0])
		return f'meta:{norm_artist}::{norm_album}'
	return f'path:{album["rel_path"]}'


def compare_libraries(reference_dir: str, target_dir: str, output_csv: str) -> None:
	"""Compare backup/reference library with target library using tag-based release matching."""
	ref_path = Path(reference_dir).resolve()
	tgt_path = Path(target_dir).resolve()

	logger.info(f'Scanning reference library (old tags/paths supported): {ref_path}')
	ref_albums = scan_album_directories(str(ref_path))
	logger.info(
		f'Reference library: {len(ref_albums)} albums, {sum(a["track_count"] for a in ref_albums)} FLAC files'
	)

	logger.info(f'Scanning target library: {tgt_path}')
	tgt_albums = scan_album_directories(str(tgt_path))
	logger.info(
		f'Target library: {len(tgt_albums)} albums, {sum(a["track_count"] for a in tgt_albums)} FLAC files'
	)

	# Build maps by identity key and relative path
	ref_by_key = {build_album_key(a): a for a in ref_albums}
	tgt_by_key = {build_album_key(a): a for a in tgt_albums}

	ref_by_rel = {a['rel_path']: a for a in ref_albums}
	tgt_by_rel = {a['rel_path']: a for a in tgt_albums}

	all_keys = sorted(set(ref_by_key.keys()) | set(tgt_by_key.keys()))

	matched_count = 0
	renamed_count = 0
	missing_in_target = []
	extra_in_target = []
	track_mismatches = []

	rows = []
	for key in all_keys:
		ref = ref_by_key.get(key)
		tgt = tgt_by_key.get(key)

		# Fallback check by relative path if not matched by tag ID key
		if not tgt and ref and ref['rel_path'] in tgt_by_rel:
			tgt = tgt_by_rel[ref['rel_path']]
		if not ref and tgt and tgt['rel_path'] in ref_by_rel:
			ref = ref_by_rel[tgt['rel_path']]

		if ref and not tgt:
			status = 'Missing in Target'
			missing_in_target.append(ref)
			rows.append(
				{
					'identity_key': key,
					'status': status,
					'discogs_id': ref['discogs_id'],
					'artist': ref['artist'],
					'album': ref['album'],
					'ref_tracks': ref['track_count'],
					'tgt_tracks': 0,
					'reference_path': ref['rel_path'],
					'target_path': '',
				}
			)
		elif tgt and not ref:
			status = 'Only in Target'
			extra_in_target.append(tgt)
			rows.append(
				{
					'identity_key': key,
					'status': status,
					'discogs_id': tgt['discogs_id'],
					'artist': tgt['artist'],
					'album': tgt['album'],
					'ref_tracks': 0,
					'tgt_tracks': tgt['track_count'],
					'reference_path': '',
					'target_path': tgt['rel_path'],
				}
			)
		elif ref and tgt:
			ref_tracks = ref['track_count']
			tgt_tracks = tgt['track_count']
			is_renamed = ref['rel_path'] != tgt['rel_path']

			if is_renamed:
				renamed_count += 1
				status = 'Renamed/Moved'
			elif ref_tracks != tgt_tracks:
				track_mismatches.append((ref, tgt))
				status = 'Track Count Mismatch'
			else:
				matched_count += 1
				status = 'Exact Match'

			if status != 'Exact Match':
				rows.append(
					{
						'identity_key': key,
						'status': status,
						'discogs_id': ref['discogs_id'] or tgt['discogs_id'],
						'artist': tgt['artist'] or ref['artist'],
						'album': tgt['album'] or ref['album'],
						'ref_tracks': ref_tracks,
						'tgt_tracks': tgt_tracks,
						'reference_path': ref['rel_path'],
						'target_path': tgt['rel_path'],
					}
				)

	output_path = Path(output_csv)
	fieldnames = [
		'identity_key',
		'status',
		'discogs_id',
		'artist',
		'album',
		'ref_tracks',
		'tgt_tracks',
		'reference_path',
		'target_path',
	]
	with output_path.open('w', newline='', encoding='utf-8') as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(rows)

	logger.warning('=== Library Tag-Aware Comparison Results ===')
	logger.warning(f'Exact Matches: {matched_count}')
	logger.warning(f'Renamed / Moved Directories (matching release ID/tags): {renamed_count}')
	logger.warning(f'Missing in Target ({target_dir}): {len(missing_in_target)}')
	logger.warning(f'Only in Target ({target_dir}): {len(extra_in_target)}')
	logger.warning(f'Track Count Mismatches: {len(track_mismatches)}')
	logger.warning(f'Detailed report saved to: {output_path.resolve()}')


def main():
	parser = argparse.ArgumentParser(
		description='Tag-aware comparison between reference library (old tags/paths) and target library.'
	)
	parser.add_argument('reference_dir', help='Path to reference / backup FLAC library root')
	parser.add_argument(
		'--target',
		default=default_target,
		help=f'Path to target library root (default: {default_target})',
	)
	parser.add_argument(
		'-o',
		'--output',
		default='library_comparison.csv',
		help='Output CSV report path (default: library_comparison.csv)',
	)
	args = parser.parse_args()

	compare_libraries(args.reference_dir, args.target, args.output)


if __name__ == '__main__':
	main()
