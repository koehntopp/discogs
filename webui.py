# /// script
# dependencies = [
#   "fastapi",
#   "uvicorn",
#   "pandas",
#   "rich",
#   "aiofiles",
#   "mutagen",
#   "python-multipart",
#   "loguru",
# ]
# ///

from __future__ import annotations

import re
import subprocess
import time
from html import escape
from pathlib import Path
from datetime import datetime
from log import logger

import pandas as pd
import uvicorn
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

SCRIPTS_DIR = Path(__file__).parent

def _config_dir() -> Path:
	try:
		from config import config_dir
		p = Path(config_dir)
	except Exception:
		p = Path('.')
	p.mkdir(parents=True, exist_ok=True)
	return p


app = FastAPI()
app.mount('/favicon', StaticFiles(directory=str(SCRIPTS_DIR / 'favicon')), name='favicon')

_sync: dict = {'proc': None}

COLUMNS = ['Album Artist', 'Album', 'DR', 'Original Date', 'Release Date', 'Catalog', 'Version']


def dr_class(dr: str) -> str:
	try:
		v = int(dr)
		if v >= 12: return 'dr-hi'
		if v >= 8:  return 'dr-mid'
		return 'dr-lo'
	except ValueError:
		return ''


def load_albums(search: str = '', sort: str = 'Album Artist', order: str = 'asc') -> list[dict]:
	df = pd.read_csv(_config_dir() / 'albums.csv', dtype=str).fillna('')
	if search:
		mask = df.apply(lambda row: row.str.contains(search, case=False).any(), axis=1)
		df = df[mask]
	if sort in df.columns:
		df = df.sort_values(sort, ascending=(order == 'asc'))
	return df.to_dict(orient='records')


def _tagger_url(row: dict) -> str:
	cfg = config_read()
	scheme = cfg.get('tagger_scheme', '')
	flacroot = cfg.get('flacroot', '')
	flacroot_local = cfg.get('flacroot_local', flacroot)
	directory = row.get('Directory', '')
	if not scheme or not directory or not flacroot:
		return ''
	# make path relative to flacroot, then rebase onto flacroot_local
	rel = Path(directory).relative_to(flacroot) if directory.startswith(flacroot) else Path(directory)
	local_path = str(Path(flacroot_local) / rel)
	return f'{scheme}{local_path}'


def _album_link(row: dict) -> str:
	album = escape(row.get('Album', ''))
	url = _tagger_url(row)
	if url:
		return f'<a href="{escape(url)}" title="Open in tagger">{album}</a>'
	return album


def _icon_cell(url: str, icon_url: str, title: str) -> str:
	if not url:
		return '<td class="icon-link"></td>'
	return (
		f'<td class="icon-link">'
		f'<a href="{url}" target="_blank" rel="noopener" title="{title}">'
		f'<img src="{icon_url}" width="16" height="16" alt="{title}" />'
		f'</a></td>'
	)


def _artist_id(artist: str) -> str:
	return f'artist-{abs(hash(artist))}'


def render_row(row: dict, artist_id: str) -> str:
	dr = escape(row.get('DR', ''))
	artist_dir = escape(str(Path(row.get('Directory', '')).parent))
	btn = (
		f'<button class="reprocess-btn" title="Re-run fixtags + bliss for all {escape(row.get("Album Artist",""))} albums" '
		f'hx-get="/reprocess" hx-vals=\'{{"artist_dir":"{artist_dir}","artist_id":"{artist_id}"}}\' '
		f'hx-target="#{artist_id}" hx-swap="outerHTML">'
		f'<i class="fa-solid fa-arrows-rotate"></i>'
		f'</button>'
	)
	discogs_id = row.get('Discogs', '').strip()
	mb_id = row.get('MusicBrainz', '').strip()
	discogs_cell = _icon_cell(
		f'https://www.discogs.com/release/{escape(discogs_id)}' if discogs_id else '',
		'/favicon/discogs.png', 'Discogs',
	)
	mb_cell = _icon_cell(
		f'https://musicbrainz.org/release/{escape(mb_id)}' if mb_id else '',
		'/favicon/musicbrainz.png', 'MusicBrainz',
	)
	return (
		f'<tr>'
		f'<td class="reprocess">{btn}</td>'
		f'<td>{escape(row.get("Album Artist",""))}</td>'
		f'<td class="album">{_album_link(row)}</td>'
		f'<td class="dr {dr_class(row.get("DR",""))}">{dr}</td>'
		f'<td>{escape(row.get("Original Date",""))}</td>'
		f'<td>{escape(row.get("Release Date",""))}</td>'
		f'{discogs_cell}{mb_cell}'
		f'<td>{escape(row.get("Catalog",""))}</td>'
		f'<td>{escape(row.get("Version",""))}</td>'
		f'</tr>'
	)


def render_artist_tbody(artist: str, rows: list[dict]) -> str:
	aid = _artist_id(artist)
	trs = ''.join(render_row(r, aid) for r in rows)
	return f'<tbody id="{aid}">{trs}</tbody>'


def render_table(rows: list[dict], sort: str, order: str, search: str) -> str:
	next_order = 'desc' if order == 'asc' else 'asc'
	ths = ['<th></th>']  # reprocess column — no sort
	for col in COLUMNS:
		if col == 'Catalog':
			for icon_col, favicon, label in [
				('Discogs',     '/favicon/discogs.png',     'Discogs'),
				('MusicBrainz', '/favicon/musicbrainz.png', 'MusicBrainz'),
			]:
				cur = 'sorted-' + order if sort == icon_col else ''
				col_order = next_order if sort == icon_col else 'asc'
				ths.append(
					f'<th class="icon-sort {cur}" '
					f'hx-get="/albums" hx-target="#albums-wrap" hx-swap="outerHTML" '
					f'hx-vals=\'{{"sort":"{icon_col}","order":"{col_order}","search":"{escape(search)}"}}\' '
					f'title="{label}">'
					f'<img src="{favicon}" width="14" height="14" alt="{label}" />'
					f'</th>'
				)
		cur = 'sorted-' + order if sort == col else ''
		col_order = next_order if sort == col else 'asc'
		ths.append(
			f'<th class="{cur}" '
			f'hx-get="/albums" hx-target="#albums-wrap" hx-swap="outerHTML" '
			f'hx-vals=\'{{"sort":"{escape(col)}","order":"{col_order}","search":"{escape(search)}"}}\' '
			f'>{escape(col)}</th>'
		)
	thead = '<thead><tr>' + ''.join(ths) + '</tr></thead>'

	# Group rows by artist, preserving current sort order
	from itertools import groupby
	tbodies = ''
	for artist, group in groupby(rows, key=lambda r: r.get('Album Artist', '')):
		tbodies += render_artist_tbody(artist, list(group))

	total = len(rows)
	return (
		f'<div id="albums-wrap">'
		f'<span id="count-data" data-total="{total}" style="display:none"></span>'
		f'<table>{thead}{tbodies}</table>'
		f'</div>'
	)


INDEX_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Discogs Library</title>
  <link rel="icon" type="image/x-icon" href="/favicon/favicon.ico" />
  <link rel="icon" type="image/png" sizes="192x192" href="/favicon/android-chrome-192x192.png" />
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon/favicon-32x32.png" />
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon/favicon-16x16.png" />
  <link rel="apple-touch-icon" sizes="180x180" href="/favicon/apple-touch-icon.png" />
  <link rel="manifest" href="/favicon/site.webmanifest" />
  <script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" />
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; font-size: 13px; margin: 0; background: #f5f5f5; color: #222; }
    .toolbar {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 12px; background: #fff; border-bottom: 1px solid #ddd;
      position: sticky; top: 0; z-index: 10;
    }
    .toolbar h1 { margin: 0; font-size: 15px; font-weight: 600; }
    .toolbar input[type=search] {
      flex: 1; max-width: 320px; padding: 4px 8px;
      border: 1px solid #ccc; border-radius: 4px; font-size: 13px;
    }
    table { border-collapse: collapse; width: 100%; font-size: 15px; }
    thead th {
      position: sticky; top: 0; background: #f0f0f0;
      border-bottom: 2px solid #ccc; padding: 5px 8px;
      text-align: left; white-space: nowrap; cursor: pointer; user-select: none;
    }
    thead th:hover { background: #e0e0e0; }
    thead th.icon-sort { text-align: center; }
    thead th.sorted-asc::after  { content: " ↑"; }
    thead th.sorted-desc::after { content: " ↓"; }
    tbody tr:nth-child(even) { background: #fafafa; }
    tbody tr:hover { background: #eef4ff; }
    td { padding: 4px 8px; border-bottom: 1px solid #eee; white-space: nowrap; }
    td.album { white-space: normal; max-width: 400px; }
    td.dr { font-weight: 600; text-align: center; }
    .dr-hi  { color: #1a7f1a; }
    .dr-mid { color: #996600; }
    .dr-lo  { color: #cc2200; }
    #refresh-btn {
      padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #refresh-btn:hover { background: #e0e0e0; }
    #refresh-btn.htmx-request i { animation: spin 0.8s linear infinite; display: inline-block; }
    #refresh-btn.htmx-request { color: #999; cursor: default; }
    #lyrics-btn, #bliss-btn, #sync-btn {
      padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #lyrics-btn:hover, #bliss-btn:hover, #sync-btn:hover { background: #e0e0e0; }
    #log-btn {
      margin-left: auto;
    }
    #settings-btn {
      padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #settings-btn:hover { background: #e0e0e0; }
    #about-btn {
      padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #about-btn:hover { background: #e0e0e0; }
    #log-btn {
      padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #log-btn:hover { background: #e0e0e0; }
    #modal-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 100;
    }
    #modal {
      position: fixed; z-index: 101; top: 50%; left: 50%; transform: translate(-50%, -50%);
      background: #fff; border-radius: 8px; box-shadow: 0 8px 32px rgba(0,0,0,0.2);
      width: 480px; max-width: 95vw; overflow: hidden;
    }
    #modal-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 12px 16px; border-bottom: 1px solid #ddd; font-weight: 600;
    }
    #modal-header button {
      border: none; background: none; font-size: 18px; cursor: pointer; color: #666; line-height: 1;
    }
    #modal-header button:hover { color: #222; }
    #modal-fields { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .field { display: flex; flex-direction: column; gap: 3px; }
    .field label { font-size: 11px; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: 0.04em; }
    .field input { padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; font-family: monospace; }
    .field input:focus { outline: none; border-color: #88a; }
    #modal-footer { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #ddd; justify-content: flex-end; }
    #modal-footer button { padding: 6px 16px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size: 13px; background: #eee; }
    #modal-footer button[type=submit] { background: #334; color: #fff; border-color: #334; }
    #modal-footer button[type=submit]:hover { background: #556; }
    .saved-ok { margin: 0 16px 0; padding: 8px; background: #e8f5e9; border-radius: 4px; color: #2a7a2a; font-size: 12px; }
    td.album a { color: inherit; text-decoration: none; }
    td.album a:hover { text-decoration: underline; }
    td.reprocess { width: 24px; padding: 2px 4px; text-align: center; }
    td.icon-link { width: 20px; padding: 2px 4px; text-align: center; }
    td.icon-link img { display: block; margin: auto; opacity: 0.8; }
    td.icon-link a:hover img { opacity: 1; }
    .reprocess-btn {
      display: inline-flex; align-items: center; justify-content: center;
      width: 20px; height: 20px; border-radius: 50%;
      border: 1px solid #ccc; background: #f5f5f5;
      cursor: pointer; font-size: 10px; color: #666; padding: 0;
      line-height: 1;
    }
    .reprocess-btn:hover { background: #e0e8ff; border-color: #99b; color: #339; }
    .reprocess-btn.htmx-request { animation: spin 0.8s linear infinite; border-color: #99b; color: #339; }
    @keyframes spin { to { transform: rotate(360deg); } }
    #count { font-size: 12px; color: #666; margin-left: auto; }
    .about { padding: 24px; max-width: 640px; }
    .about h2 { margin: 0 0 8px; font-size: 16px; }
    .about h3 { margin: 24px 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #666; }
    .about p { margin: 0 0 8px; line-height: 1.6; color: #444; }
    .about-table { border-collapse: collapse; width: 100%; }
    .about-table td { padding: 4px 12px 4px 0; vertical-align: top; font-size: 13px; border-bottom: 1px solid #eee; }
    .about-table td:first-child { white-space: nowrap; font-weight: 500; width: 160px; }
    .about a { color: #446; }
    .about a:hover { color: #000; }
  </style>
</head>
<body>
  <div class="toolbar">
    <h1><img src="/favicon/favicon-32x32.png" width="20" height="20" alt="" style="vertical-align:middle;margin-right:6px;margin-bottom:2px;">Discogs Library</h1>
    <input type="search" name="search" id="search-box" placeholder="Search…"
      hx-get="/albums" hx-trigger="input changed delay:300ms, search"
      hx-target="#albums-wrap" hx-swap="outerHTML"
      hx-include="[name='search']" />
    <button id="refresh-btn"
      hx-get="/refresh/start"
      hx-target="#modal-wrap"
      hx-swap="innerHTML">
      <i class="fa-solid fa-arrows-rotate"></i>
    </button>
    <button id="lyrics-btn"
      hx-get="/lyrics" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-music"></i>
    </button>
    <button id="bliss-btn"
      hx-get="/bliss" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-folder-tree"></i>
    </button>
    <button id="sync-btn"
      hx-get="/sync" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-cloud-arrow-up"></i>
    </button>
    <span id="count"></span>
    <button id="log-btn"
      hx-get="/log" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-regular fa-file-lines"></i>
    </button>
    <button id="settings-btn"
      hx-get="/settings" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-gear"></i>
    </button>
    <button id="about-btn"
      hx-get="/about" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-circle-info"></i>
    </button>
  </div>
  <div id="modal-wrap"></div>

  <div id="albums-panel" style="overflow:auto;height:calc(100vh - 45px)">
    <div id="albums-wrap"
      hx-get="/albums" hx-trigger="load"
      hx-target="#albums-wrap" hx-swap="outerHTML">
      <p style="padding:16px;color:#666">Loading…</p>
    </div>
  </div>


  <script>
    document.body.addEventListener('htmx:afterSwap', function() {
      const el = document.getElementById('count-data');
      if (el) document.getElementById('count').textContent = el.dataset.total + ' albums';
    });
    function closeModal() {
      document.getElementById('modal-wrap').innerHTML = '';
    }
  </script>
</body>
</html>'''


@app.get('/', response_class=HTMLResponse)
async def index():
	return HTMLResponse(INDEX_HTML)


@app.get('/albums', response_class=HTMLResponse)
async def albums(
	search: str = Query(default=''),
	sort: str = Query(default='Album Artist'),
	order: str = Query(default='asc'),
):
	rows = load_albums(search=search, sort=sort, order=order)
	return HTMLResponse(render_table(rows, sort, order, search))



@app.get('/refresh/start', response_class=HTMLResponse)
async def refresh_start():
	import threading
	from config import flacroot
	logger.info('refresh: scanning library')
	proc = subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'album_list.py'), str(flacroot)],
		stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
		cwd=str(SCRIPTS_DIR),
	)
	def _reader():
		for line in proc.stdout:
			line = line.rstrip()
			if line:
				logger.info(f'refresh: {line}')
		proc.wait()
		if proc.returncode == 0:
			logger.success('refresh: library scan complete')
		else:
			logger.error(f'refresh: scan failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()
	return await log_modal()


@app.get('/reprocess', response_class=HTMLResponse)
async def reprocess(artist_dir: str = Query(...), artist_id: str = Query(...)):
	import os
	from mutagen.flac import FLAC

	def clean(text: str) -> str:
		"""Replicate bliss.clean() to derive canonical directory names."""
		import unicodedata
		replacements = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss'}
		for k, v in replacements.items():
			text = text.replace(k, v)
		# Remove chars that are unsafe on common filesystems
		text = re.sub(r'[^\w\s\-.]', '', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode())
		return re.sub(r'[\s]+', '_', text).strip('_')

	ALBUM_TAGS = [
		'ALBUMARTIST', 'ALBUM', 'ALBUM DYNAMIC RANGE', 'ORIGINAL_TITLE',
		'ORIGINALDATE', 'RELEASEDATE', 'CATALOGNUMBER',
		'DISCOGS_RELEASE_ID', 'MUSICBRAINZ_ALBUMID', 'SUBTITLE',
	]
	DISPLAY = {
		'ALBUMARTIST': 'Album Artist', 'ALBUM': 'Album',
		'ALBUM DYNAMIC RANGE': 'DR', 'ORIGINAL_TITLE': 'Original Title',
		'ORIGINALDATE': 'Original Date', 'RELEASEDATE': 'Release Date',
		'CATALOGNUMBER': 'Catalog', 'DISCOGS_RELEASE_ID': 'Discogs',
		'MUSICBRAINZ_ALBUMID': 'MusicBrainz', 'SUBTITLE': 'Version',
	}

	def read_album_dir(album_dir: str) -> dict | None:
		first_flac = next((f for f in os.listdir(album_dir) if f.endswith('.flac')), None)
		if not first_flac:
			return None
		try:
			audio = FLAC(str(Path(album_dir) / first_flac))
			raw = {k.upper(): v for k, v in audio.tags}
		except Exception:
			return None
		row = {DISPLAY[t]: (raw.get(t, [''])[0] if isinstance(raw.get(t), list) else raw.get(t, '') or '') for t in ALBUM_TAGS}
		row['Directory'] = album_dir
		return row

	# Read ALBUMARTIST before running anything — bliss may rename the artist dir
	album_artist = None
	if Path(artist_dir).is_dir():
		for entry in sorted(Path(artist_dir).iterdir()):
			if entry.is_dir():
				first_flac = next((f for f in os.listdir(str(entry)) if f.endswith('.flac')), None)
				if first_flac:
					try:
						audio = FLAC(str(entry / first_flac))
						album_artist = audio.tags.get('ALBUMARTIST', [None])[0]
					except Exception:
						pass
				if album_artist:
					break

	import asyncio

	def run_scripts():
		# Run fixtags on each album subdir
		if Path(artist_dir).is_dir():
			for entry in sorted(Path(artist_dir).iterdir()):
				if entry.is_dir() and any(f.suffix == '.flac' for f in entry.iterdir()):
					subprocess.run(
						['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), str(entry)],
						stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
						cwd=str(SCRIPTS_DIR),
					)
		# Run bliss on artist dir
		subprocess.run(
			['uv', 'run', str(SCRIPTS_DIR / 'bliss.py'), artist_dir],
			stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
			cwd=str(SCRIPTS_DIR),
		)

	await asyncio.to_thread(run_scripts)

	# Derive the canonical new artist dir via bliss's clean() on the ALBUMARTIST tag
	from config import flacroot
	if album_artist:
		new_artist_dir = str(Path(flacroot) / clean(album_artist))
	else:
		new_artist_dir = artist_dir  # fallback

	rows = []
	if Path(new_artist_dir).is_dir():
		for entry in sorted(Path(new_artist_dir).iterdir()):
			if entry.is_dir():
				row = read_album_dir(str(entry))
				if row:
					rows.append(row)

	if not rows:
		return HTMLResponse(f'<tbody id="{artist_id}"></tbody>')

	artist = rows[0].get('Album Artist', '')
	return HTMLResponse(render_artist_tbody(artist, rows))


@app.get('/lyrics', response_class=HTMLResponse)
async def lyrics_run():
	import threading
	from config import flacroot
	logger.info('lyrics: starting update')
	proc = subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'update_lyrics.py'), str(flacroot)],
		stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
		cwd=str(SCRIPTS_DIR),
	)
	def _reader():
		for line in proc.stdout:
			line = line.rstrip()
			if line:
				logger.info(f'lyrics: {line}')
		proc.wait()
		if proc.returncode == 0:
			logger.success('lyrics: done')
		else:
			logger.error(f'lyrics: failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()
	return await log_modal()


@app.get('/bliss', response_class=HTMLResponse)
async def bliss_run():
	import threading
	logger.info('bliss: starting default organisation pass')
	proc = subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'bliss.py')],
		stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
		cwd=str(SCRIPTS_DIR),
	)
	def _reader():
		for line in proc.stdout:
			line = line.rstrip()
			if line:
				logger.info(f'bliss: {line}')
		proc.wait()
		if proc.returncode == 0:
			logger.success('bliss: done')
		else:
			logger.error(f'bliss: failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()
	return await log_modal()


@app.get('/sync', response_class=HTMLResponse)
async def sync_start():
	global _sync
	cfg = config_read()
	flacroot  = cfg.get('flacroot', '')
	remote    = cfg.get('flacroot_remote', '')
	flags     = cfg.get('rclone_flags', 'sync')
	transfers = cfg.get('rclone_transfers', '8')
	stats     = cfg.get('rclone_stats', '5s')

	if not flacroot or not remote:
		logger.error('rclone sync: flacroot or flacroot_remote not set in config')
	else:
		if _sync.get('proc') and _sync['proc'].poll() is None:
			_sync['proc'].terminate()
		import threading
		strip = {'-P', '--progress', '-v', '--verbose'}
		clean_flags = [f for f in flags.split() if f not in strip]
		rclone_log = _config_dir() / 'rclone.log'
		rclone_log.write_text('')  # truncate on each run
		cmd = ['rclone'] + clean_flags + [
			'--log-file', str(rclone_log),
			'--log-level', 'NOTICE',
			'--stats-log-level', 'NOTICE',
			'--stats-one-line', '--stats', stats,
			'--transfers', transfers,
			flacroot, remote,
		]
		proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		_sync = {'proc': proc}
		logger.info(f"rclone sync started: {' '.join(cmd)}")
		def _reader():
			with open(rclone_log, 'r') as f:
				while proc.poll() is None:
					line = f.readline()
					if line:
						logger.info(f"rclone: {line.rstrip()}")
					else:
						time.sleep(0.5)
				for line in f:
					if line.strip():
						logger.info(f"rclone: {line.rstrip()}")
			if proc.returncode == 0:
				logger.success('rclone sync done (exit 0)')
			else:
				logger.error(f'rclone sync failed (exit {proc.returncode})')
		threading.Thread(target=_reader, daemon=True).start()

	# Return the standard log modal
	return await log_modal()


@app.get('/run-pipeline', response_class=StreamingResponse)
async def run_pipeline(directory: str = Query(...)):
	def stream():
		yield f'<div class="log-line">[{datetime.now().strftime("%H:%M:%S")}] Starting pipeline on {escape(directory)}</div>\n'
		proc = subprocess.Popen(
			['uv', 'run', str(SCRIPTS_DIR / 'nzbfix.py'), directory],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
		)
		for line in proc.stdout:
			line = line.rstrip()
			if line:
				yield f'<div class="log-line">{escape(line)}</div>\n'
		proc.wait()
		status = 'Done' if proc.returncode == 0 else f'Failed (exit {proc.returncode})'
		yield f'<div class="log-line log-done">[{datetime.now().strftime("%H:%M:%S")}] {status}</div>\n'

	return StreamingResponse(stream(), media_type='text/html')


CONFIG_PATH = SCRIPTS_DIR / 'config.py'

# Labels and ordering for the settings form
SETTINGS_TITLE = 'Settings'

CONFIG_LABELS = {
	'config_dir':       ('Config / Data Directory',        'text'),
	'discogs_api_key':  ('Discogs API Key',               'text'),
	'tagger_scheme':    ('Tagger URL Scheme',              'text'),
	'flacroot':         ('FLAC Library Root',              'text'),
	'mp3root':          ('MP3 Mirror Root',                'text'),
	'flacroot_local':   ('FLAC Root (local)',              'text'),
	'nzbdir':           ('NZB Complete Dir',               'text'),
	'rsgain_loudness':  ('rsgain Loudness (LUFS)',         'text'),
	'rsgain_clip_mode': ('rsgain Clip Mode (n/p/a)',       'text'),
	'rsgain_max_peak':  ('rsgain Max Peak (dBTP)',         'text'),
	'rsgain_true_peak': ('rsgain True Peak (True/False)',  'text'),
	'rsgain_opus_mode': ('rsgain Opus Mode (d/r/s/t/a)',   'text'),
	'rsgain_skip':      ('rsgain Skip Existing (True/False)', 'text'),
	'log_file':         ('Log File',                          'text'),
	'log_rotation':     ('Log Rotation',                      'text'),
	'log_retention':    ('Log Retention',                     'text'),
	'flacroot_remote':   ('FLAC Remote (rclone destination)', 'text'),
	'rclone_flags':      ('rclone Flags',                     'text'),
	'rclone_transfers':  ('rclone Transfers',                  'text'),
	'rclone_stats':      ('rclone Stats Interval',             'text'),
}


def config_read() -> dict[str, str]:
	"""Parse config.py and return active (non-commented) key=value pairs as strings."""
	text = CONFIG_PATH.read_text()
	result = {}
	for line in text.splitlines():
		line = line.strip()
		if line.startswith('#') or not line:
			continue
		# strip inline comment (outside of quotes)
		line = re.sub(r'\s+#.*$', '', line)
		# quoted string
		m = re.match(r'^(\w+)\s*=\s*[\'"](.*)[\'"]\s*$', line)
		if m:
			result[m.group(1)] = m.group(2)
			continue
		# unquoted value (bool, int, float) — strip any accidental quotes
		m = re.match(r'^(\w+)\s*=\s*(\S+)', line)
		if m:
			result[m.group(1)] = m.group(2).strip("'\"")
	return result


# Keys whose values are stored unquoted in config.py
_UNQUOTED = {'rsgain_loudness', 'rsgain_max_peak', 'rsgain_true_peak', 'rsgain_skip', 'rclone_transfers'}


def config_write(updates: dict[str, str]) -> None:
	"""Write updated values back to config.py, preserving comments and structure."""
	lines = CONFIG_PATH.read_text().splitlines()
	out = []
	for line in lines:
		# match quoted
		m = re.match(r'^(\w+)\s*=\s*[\'"](.*)[\'"]\s*$', line.strip())
		if not m:
			# match unquoted
			m = re.match(r'^(\w+)\s*=\s*(\S+)', line.strip())
		if m and m.group(1) in updates:
			key = m.group(1)
			val = updates[key]
			if key in _UNQUOTED:
				out.append(f'{key} = {val}')
				continue
			# preserve original quote style
			quote = "'" if line.strip()[len(key):].lstrip(' =')[0] == "'" else '"'
			out.append(f"{key} = {quote}{updates[key]}{quote}")
		else:
			out.append(line)
	CONFIG_PATH.write_text('\n'.join(out) + '\n')


def render_settings_modal(values: dict[str, str], saved: bool = False) -> str:
	fields = ''
	for key, (label, _) in CONFIG_LABELS.items():
		val = escape(values.get(key, ''))
		fields += (
			f'<div class="field">'
			f'<label for="cfg-{key}">{label}</label>'
			f'<input type="text" id="cfg-{key}" name="{key}" value="{val}" />'
			f'</div>'
		)
	banner = '<p class="saved-ok">Saved.</p>' if saved else ''
	return f'''
<div id="modal-backdrop" onclick="closeModal()"></div>
<div id="modal">
  <div id="modal-header">
    <span>{SETTINGS_TITLE}</span>
    <button onclick="closeModal()" title="Close">&times;</button>
  </div>
  <form hx-post="/settings/save" hx-target="#modal-wrap" hx-swap="innerHTML">
    {banner}
    <div id="modal-fields">{fields}</div>
    <div id="modal-footer">
      <button type="submit">Save</button>
      <button type="button" onclick="closeModal()">Cancel</button>
    </div>
  </form>
</div>'''


LOG_TAIL = 500  # lines to show


_LOG_COLOURS = {
	'SUCCESS':  '#6ec96e',
	'ERROR':    '#f47f7f',
	'WARNING':  '#e0a840',
	'CRITICAL': '#ff5555',
}


def _read_log_html() -> str:
	cfg = config_read()
	log_path = _config_dir() / cfg.get('log_file', 'discogs.log')
	if not log_path.exists():
		return '<span style="color:#666">(log file not found)</span>'
	lines = log_path.read_text(errors='replace').splitlines()[-LOG_TAIL:]
	out = []
	for line in lines:
		colour = next((c for level, c in _LOG_COLOURS.items() if f'| {level}' in line), None)
		escaped = escape(line)
		out.append(f'<span style="color:{colour}">{escaped}</span>' if colour else escaped)
	return '\n'.join(out)


@app.get('/log', response_class=HTMLResponse)
async def log_modal():
	return HTMLResponse('''
<div id="modal-backdrop" onclick="closeModal()"></div>
<div id="modal" style="width:80vw;height:80vh;display:flex;flex-direction:column;">
  <div id="modal-header">
    <span>Log</span>
    <div style="display:flex;gap:8px;align-items:center;">
      <label style="font-size:12px;font-weight:normal;display:flex;align-items:center;gap:4px;">
        <input type="checkbox" id="log-autoscroll" checked> Auto-scroll
      </label>
      <label style="font-size:12px;font-weight:normal;display:flex;align-items:center;gap:4px;">
        <input type="checkbox" id="log-autorefresh" checked> Live
      </label>
      <button onclick="closeModal()" title="Close">&times;</button>
    </div>
  </div>
  <pre id="log-content"
    hx-get="/log/content"
    hx-trigger="every 3s [document.getElementById('log-autorefresh')?.checked]"
    hx-swap="innerHTML"
    hx-on::after-request="if(document.getElementById('log-autoscroll')?.checked){ var el=document.getElementById('log-content'); el.scrollTop=el.scrollHeight; }"
    style="flex:1;overflow:auto;margin:0;padding:12px;background:#1e1e1e;color:#d4d4d4;
           font-family:monospace;font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-all;"
  >''' + _read_log_html() + '''</pre>
</div>
<script>
  (function(){ var el=document.getElementById('log-content'); el.scrollTop=el.scrollHeight; })();
</script>''')


@app.get('/log/content', response_class=HTMLResponse)
async def log_content():
	return HTMLResponse(_read_log_html())


@app.get('/about', response_class=HTMLResponse)
async def about():
	return HTMLResponse('''
<div id="modal-backdrop" onclick="closeModal()"></div>
<div id="modal" style="width:560px;max-height:80vh;display:flex;flex-direction:column;">
  <div id="modal-header">
    <span>About</span>
    <button onclick="closeModal()" title="Close">&times;</button>
  </div>
  <div style="overflow-y:auto;padding:16px;" class="about">
    <p>
      A collection of Python tools for managing a local FLAC music library using
      <a href="https://www.discogs.com" target="_blank" rel="noopener">Discogs</a> metadata,
      with a web interface built on FastAPI and HTMX.
    </p>
    <h3>Python libraries</h3>
    <table class="about-table">
      <tr><td><a href="https://github.com/fastapi/fastapi" target="_blank" rel="noopener">FastAPI</a></td><td>Web framework powering this UI</td></tr>
      <tr><td><a href="https://github.com/encode/uvicorn" target="_blank" rel="noopener">Uvicorn</a></td><td>ASGI server</td></tr>
      <tr><td><a href="https://github.com/bigskysoftware/htmx" target="_blank" rel="noopener">HTMX</a></td><td>HTML-driven interactivity without JavaScript</td></tr>
      <tr><td><a href="https://github.com/joalla/discogs_client" target="_blank" rel="noopener">discogs_client</a></td><td>Discogs API client</td></tr>
      <tr><td><a href="https://github.com/supermihi/pytaglib" target="_blank" rel="noopener">pytaglib</a></td><td>FLAC tag reading and writing via TagLib</td></tr>
      <tr><td><a href="https://github.com/quodlibet/mutagen" target="_blank" rel="noopener">mutagen</a></td><td>Pure-Python audio metadata library</td></tr>
      <tr><td><a href="https://github.com/pandas-dev/pandas" target="_blank" rel="noopener">pandas</a></td><td>Album inventory as DataFrames</td></tr>
      <tr><td><a href="https://github.com/matplotlib/matplotlib" target="_blank" rel="noopener">matplotlib</a></td><td>Dynamic Range distribution chart</td></tr>
      <tr><td><a href="https://github.com/Textualize/rich" target="_blank" rel="noopener">Rich</a></td><td>Coloured terminal output and logging</td></tr>
      <tr><td><a href="https://github.com/beetbox/pyacoustid" target="_blank" rel="noopener">pyacoustid</a></td><td>AcoustID acoustic fingerprinting</td></tr>
      <tr><td><a href="https://pypi.org/project/drmeter/" target="_blank" rel="noopener">drmeter</a></td><td>Dynamic Range score calculation</td></tr>
      <tr><td><a href="https://github.com/amueller/word_cloud" target="_blank" rel="noopener">wordcloud</a></td><td>Lyrics word cloud generation</td></tr>
      <tr><td><a href="https://github.com/un33k/python-slugify" target="_blank" rel="noopener">python-slugify</a></td><td>Filename sanitisation</td></tr>
      <tr><td><a href="https://github.com/avian2/unidecode" target="_blank" rel="noopener">Unidecode</a></td><td>Unicode to ASCII transliteration</td></tr>
      <tr><td><a href="https://github.com/python-pillow/Pillow" target="_blank" rel="noopener">Pillow</a></td><td>Image handling for artwork</td></tr>
      <tr><td><a href="https://github.com/bastibe/python-soundfile" target="_blank" rel="noopener">SoundFile</a></td><td>Audio file I/O</td></tr>
    </table>
    <h3>External tools</h3>
    <table class="about-table">
      <tr><td><a href="https://github.com/complexlogic/rsgain" target="_blank" rel="noopener">rsgain</a></td><td>ReplayGain tag calculation</td></tr>
      <tr><td><a href="https://github.com/FFmpeg/FFmpeg" target="_blank" rel="noopener">FFmpeg</a></td><td>MP3 and Opus transcoding</td></tr>
      <tr><td><a href="https://acoustid.org/chromaprint" target="_blank" rel="noopener">fpcalc / Chromaprint</a></td><td>Acoustic fingerprint generation</td></tr>
      <tr><td><a href="https://lrclib.net" target="_blank" rel="noopener">lrclib.net</a></td><td>Synced lyrics source</td></tr>
      <tr><td><a href="https://2manyrobots.com/yate/" target="_blank" rel="noopener">Yate</a></td><td>FLAC tagger (macOS)</td></tr>
    </table>
  </div>
</div>''')


@app.get('/settings', response_class=HTMLResponse)
async def settings_get():
	return HTMLResponse(render_settings_modal(config_read()))


@app.post('/settings/save', response_class=HTMLResponse)
async def settings_save(request: Request):
	form = await request.form()
	updates = {k: v for k, v in form.items() if k in CONFIG_LABELS}
	config_write(updates)
	return HTMLResponse(render_settings_modal(config_read(), saved=True))


if __name__ == '__main__':
	uvicorn.run('webui:app', host='127.0.0.1', port=8000, reload=True)
