#!/usr/bin/env -S uv run
# /// script
# dependencies = ["mcp", "pandas"]
# ///
"""Standalone MCP server exposing the albums.csv music library."""

import csv
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Locate albums.csv: prefer CONFIG_DIR, fall back to script directory
_config_dir = os.environ.get('CONFIG_DIR', os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = Path(_config_dir) / 'albums.csv'

mcp = FastMCP('discogs-albums')


def _load() -> list[dict]:
	if not CSV_PATH.exists():
		return []
	with open(CSV_PATH, newline='', encoding='utf-8') as f:
		return list(csv.DictReader(f))


def _match(row: dict, query: str) -> bool:
	q = query.lower()
	return any(q in str(v).lower() for v in row.values())


@mcp.tool()
def search_albums(query: str) -> list[dict]:
	"""Search albums by any field (artist, title, catalog, version, etc.)."""
	rows = _load()
	return [r for r in rows if _match(r, query)]


@mcp.tool()
def list_artists() -> list[str]:
	"""Return a sorted list of all album artists in the library."""
	rows = _load()
	return sorted({r['Album Artist'] for r in rows if r.get('Album Artist')})


@mcp.tool()
def get_albums_by_artist(artist: str) -> list[dict]:
	"""Return all albums for an artist (case-insensitive, partial match)."""
	rows = _load()
	a = artist.lower()
	return [r for r in rows if a in r.get('Album Artist', '').lower()]


@mcp.tool()
def get_album_stats() -> dict:
	"""Return summary statistics: total albums, DR distribution, year range."""
	rows = _load()
	if not rows:
		return {}
	drs = [int(r['DR']) for r in rows if r.get('DR', '').strip().isdigit()]
	years = [int(r['Original Date']) for r in rows if r.get('Original Date', '').strip().isdigit()]
	return {
		'total_albums': len(rows),
		'dr_min': min(drs) if drs else None,
		'dr_max': max(drs) if drs else None,
		'dr_avg': round(sum(drs) / len(drs), 1) if drs else None,
		'year_min': min(years) if years else None,
		'year_max': max(years) if years else None,
	}


@mcp.tool()
def get_albums_by_dr(min_dr: int = 0, max_dr: int = 20) -> list[dict]:
	"""Return albums with DR score in the given range (inclusive)."""
	rows = _load()
	return [
		r for r in rows if r.get('DR', '').strip().isdigit() and min_dr <= int(r['DR']) <= max_dr
	]


@mcp.tool()
def get_albums_by_year(year: int) -> list[dict]:
	"""Return albums with the given original release year."""
	rows = _load()
	return [r for r in rows if r.get('Original Date', '').strip() == str(year)]


LYRICS_DIR = Path(_config_dir) / 'lyrics'


@mcp.tool()
def get_lyrics(discogs_id: str, track: int) -> str:
	"""Return lyrics for a specific track. discogs_id is the Discogs release ID, track is the track number."""
	stem = f'{discogs_id}_{str(track).zfill(2)}'
	for ext in ('lrc', 'txt'):
		f = LYRICS_DIR / f'{stem}.{ext}'
		if f.exists():
			return f.read_text(encoding='utf-8')
	return ''


@mcp.tool()
def search_lyrics(query: str) -> list[dict]:
	"""Search lyrics files for a text string. Returns list of {discogs_id, track, snippet}."""
	if not LYRICS_DIR.exists():
		return []
	q = query.lower()
	results = []
	for f in sorted(LYRICS_DIR.iterdir()):
		text = f.read_text(encoding='utf-8')
		if q in text.lower():
			parts = f.stem.split('_')
			discogs_id, track = parts[0], parts[1] if len(parts) > 1 else '?'
			# find the matching line for context
			line = next((l.strip() for l in text.splitlines() if q in l.lower()), '')
			results.append({'discogs_id': discogs_id, 'track': track, 'match': line})
	return results


if __name__ == '__main__':
	mcp.run(transport='stdio')
