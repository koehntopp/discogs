# /// script
# dependencies = [
#   "fastapi",
#   "uvicorn",
#   "pandas",
#   "rich",
#   "aiofiles",
#   "mutagen",
#   "pillow",
#   "python-multipart",
#   "structlog",
#   "requests",
# ]
# ///

from __future__ import annotations

import os as _os, sys as _sys
if _os.environ.get('PREINSTALL_ONLY'):
	_sys.exit(0)

import re
import subprocess

def _relay_child_line(prefix: str, line: str) -> None:
	"""Parse a JSON log line from a child process and re-log just the event."""
	import json
	line = line.strip()
	if not line:
		return
	try:
		rec = json.loads(line)
		event = rec.get('event', line)
		level = rec.get('level', 'info').lower()
		if level == 'success':
			success(f'{prefix}: {event}')
		else:
			getattr(logger, level, logger.info)(f'{prefix}: {event}')
	except (json.JSONDecodeError, ValueError):
		logger.info(f'{prefix}: {line}')
import sys
import os
import time
from html import escape
from pathlib import Path
from datetime import datetime

# Allow config.py to live in CONFIG_DIR (e.g. /config in Docker)
_config_dir = os.environ.get('CONFIG_DIR')
if _config_dir and _config_dir not in sys.path:
	sys.path.insert(0, _config_dir)

from log import logger, success

import pandas as pd
import uvicorn
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

SCRIPTS_DIR = Path(__file__).parent

def _config_dir() -> Path:
	# ENV var takes priority (set in Docker); fall back to config.py, then CWD
	env = os.environ.get('CONFIG_DIR')
	if env:
		p = Path(env)
	else:
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
_refresh_done: dict = {'pending': False}
_album_cache: pd.DataFrame | None = None
_current_proc: subprocess.Popen | None = None


def _set_proc(proc: subprocess.Popen) -> subprocess.Popen:
	"""Register proc as the current killable process and return it."""
	global _current_proc
	_current_proc = proc
	return proc


def _clear_proc() -> None:
	global _current_proc
	_current_proc = None


def _cache_load() -> pd.DataFrame:
	"""Return the in-memory album cache, loading from CSV if needed."""
	global _album_cache
	if _album_cache is None:
		csv = _config_dir() / 'albums.csv'
		if csv.exists():
			try:
				_album_cache = pd.read_csv(csv, dtype=str).fillna('')
			except Exception as e:
				logger.error(f'cache load: {e}')
				_album_cache = pd.DataFrame()
		else:
			_album_cache = pd.DataFrame()
	return _album_cache


def _cache_invalidate() -> None:
	global _album_cache
	_album_cache = None


def _cache_update(new_rows: list[dict], drop_dirs: set[str]) -> None:
	"""Replace rows matching drop_dirs with new_rows, then write through to CSV."""
	global _album_cache
	df = _cache_load()
	if 'Directory' in df.columns:
		df = df[~df['Directory'].isin(drop_dirs)]
	df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
	_album_cache = df
	try:
		df.to_csv(_config_dir() / 'albums.csv', index=False)
	except Exception as e:
		logger.error(f'cache write: {e}')

COLUMNS = ['Album Artist', 'Album', 'DR', 'Original Date', 'Release Date', 'Catalog', 'Cover Art', 'Version']


def dr_class(dr: str) -> str:
	try:
		v = int(dr)
		if v >= 12: return 'dr-hi'
		if v >= 8:  return 'dr-mid'
		return 'dr-lo'
	except ValueError:
		return ''


def load_albums(search: str = '', sort: str = 'Album Artist', order: str = 'asc') -> list[dict]:
	df = _cache_load()
	if df.empty:
		return []
	if search:
		mask = df.apply(lambda row: row.str.contains(search, case=False).any(), axis=1)
		df = df[mask]
	if sort in df.columns:
		asc = order == 'asc'
		by = [sort]
		ascending = [asc]
		if sort == 'Album Artist':
			by += ['Original Date', 'Release Date']
			ascending += [True, True]
		df = df.sort_values(by=by, ascending=ascending)
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


def _album_link(row: dict, title: str = '') -> str:
	album = escape(title or row.get('Album', ''))
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


def _cover_art_cell(row: dict) -> str:
	dims = row.get('Cover Art', '')
	artist = row.get('Album Artist', '')
	title = row.get('Original Title', '') or row.get('Album', '')
	if not dims:
		return ''
	if artist or title:
		from urllib.parse import urlencode
		url = 'https://www.albumartexchange.com/covers?' + urlencode({'fltr': 'ALL', 'sort': 'TITLE', 'q': f'{artist} {title}'.strip()})
		icon = (
			f'<a href="{url}" target="_blank" rel="noopener" title="Search Album Art Exchange" style="margin-left:4px;">'
			f'<img src="/favicon/albumartexchange.png" width="12" height="12" style="vertical-align:middle;opacity:0.7;">'
			f'</a>'
		)
		return f'{escape(dims)}{icon}'
	return escape(dims)


def render_row(row: dict, artist_id: str, row_index: int = 0) -> str:
	dr = escape(row.get('DR', ''))
	album_title = row.get('Original Filename', '').strip() or row.get('Original Title', '').strip() or row.get('Album', '')
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
	from urllib.parse import urlencode
	dr_artist = escape(row.get('Album Artist', ''))
	dr_album  = escape(album_title)
	dr_url    = 'https://dr.loudness-war.info/album/list/1/dr/desc?' + urlencode({'artist': row.get('Album Artist', ''), 'album': album_title})
	dr_btn    = (
		f'<a href="{dr_url}" target="_blank" rel="noopener" title="Look up DR on loudness-war.info" '
		f'style="color:#888;font-size:11px;text-decoration:none;margin-left:4px;">'
		f'<i class="fa-solid fa-wave-square"></i></a>'
	) if dr else ''
	return (
		f'<tr class="{"even" if row_index % 2 else "odd"}">'
		f'<td class="reprocess">{btn}</td>'
		f'<td class="artist">{escape(row.get("Album Artist",""))}</td>'
		f'<td class="album">{_album_link(row, album_title)}</td>'
		f'<td class="dr {dr_class(row.get("DR",""))}">{dr}{dr_btn}</td>'
		f'<td>{escape(row.get("Original Date",""))}</td>'
		f'<td>{escape(row.get("Release Date",""))}</td>'
		f'{discogs_cell}{mb_cell}'
		f'<td>{escape(row.get("Catalog",""))}</td>'
		f'<td class="cover-art">{_cover_art_cell(row)}</td>'
		f'<td class="version">{escape(row.get("Version",""))}</td>'
		f'</tr>'
	)


def render_artist_tbody(artist: str, rows: list[dict], start_index: int = 0) -> str:
	aid = _artist_id(artist)
	trs = ''.join(render_row(r, aid, start_index + i) for i, r in enumerate(rows))
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
	row_counter = 0
	for artist, group in groupby(rows, key=lambda r: r.get('Album Artist', '')):
		group_rows = list(group)
		tbodies += render_artist_tbody(artist, group_rows, row_counter)
		row_counter += len(group_rows)

	total = len(rows)
	if total == 0:
		return (
			'<div id="albums-wrap"'
			' hx-get="/refresh/start" hx-trigger="load" hx-target="#modal-wrap" hx-swap="innerHTML">'
			'</div>'
		)
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
      position: sticky; top: 0; z-index: 30;
    }
    .toolbar h1 { margin: 0; font-size: 15px; font-weight: 600; }
    .toolbar input[type=search] {
      flex: 1; max-width: 320px; padding: 4px 8px;
      border: 1px solid #ccc; border-radius: 4px; font-size: 13px;
    }
    table { border-collapse: collapse; width: 100%; font-size: 15px; }
    thead th {
      position: sticky; top: 0; background: #f0f0f0; z-index: 20;
      border-bottom: 2px solid #ccc; padding: 5px 8px;
      text-align: left; white-space: nowrap; cursor: pointer; user-select: none;
    }
    thead th:hover { background: #e0e0e0; }
    thead th.icon-sort { text-align: center; }
    thead th.sorted-asc::after  { content: " ↑"; }
    thead th.sorted-desc::after { content: " ↓"; }
    tbody tr.odd  { background: #ffffff; }
    tbody tr.even { background: #eef0f5; }
    tbody tr:hover { background: #dde8ff; }
    td { padding: 4px 8px; border-bottom: 1px solid #eee; white-space: nowrap; }
    td.artist { width: 600px; min-width: 300px; max-width: 600px; white-space: normal; }
    td.album { white-space: normal; width: 600px; min-width: 300px; }
    td.version { white-space: normal; min-width: 100px; }
    td.dr { font-weight: 600; }
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
    .toolbar-sep { width: 1px; height: 20px; background: #ccc; margin: 0 4px; flex-shrink: 0; }
    #link-buttons { display: flex; gap: 4px; align-items: center; }
    .link-url-btn {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 5px 7px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; text-decoration: none;
    }
    .link-url-btn:hover { background: #e0e0e0; }
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
    td.cover-art { color: #888; font-size: 11px; white-space: nowrap; }
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
    <div class="toolbar-sep"></div>
    <div id="link-buttons"
      hx-get="/link-buttons" hx-trigger="load" hx-swap="innerHTML"></div>
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
    // Re-trigger log polling immediately when tab regains focus,
    // compensating for browser throttling of background timers.
    document.addEventListener('visibilitychange', function() {
      if (document.visibilityState === 'visible') {
        const el = document.getElementById('log-content');
        if (el) htmx.trigger(el, 'every 3s');
      }
    });
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



def _start_album_scan(label: str = 'refresh') -> None:
	"""Launch album_list.py in a background thread; sets _refresh_done on completion."""
	import threading, shutil
	try:
		from config import flacroot
	except Exception as e:
		logger.error(f'{label}: cannot import config: {e}')
		return
	uv = shutil.which('uv')
	if not Path(flacroot).exists():
		logger.error(f'{label}: flacroot does not exist: {flacroot}')
		return
	script = SCRIPTS_DIR / 'album_list.py'
	logger.info(f'{label}: running library scan')
	proc = _set_proc(subprocess.Popen(
		['uv', 'run', str(script), str(flacroot)],
		stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
		cwd=str(SCRIPTS_DIR), env={**os.environ, 'DISCOGS_CHILD': '1'},
	))
	def _reader():
		for line in proc.stdout:
			_relay_child_line(label, line)
		proc.wait()
		if proc.returncode == 0:
			logger.info(f'{label}: library scan complete')
			_cache_invalidate()
			_refresh_done['pending'] = True
		else:
			logger.error(f'{label}: scan failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()


@app.get('/refresh/start', response_class=HTMLResponse)
async def refresh_start():
	_start_album_scan('refresh')
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
		'ORIGINAL FILENAME', 'ORIGINALDATE', 'RELEASEDATE', 'CATALOGNUMBER',
		'DISCOGS_RELEASE_ID', 'MUSICBRAINZ_ALBUMID', 'SUBTITLE',
	]
	DISPLAY = {
		'ALBUMARTIST': 'Album Artist', 'ALBUM': 'Album',
		'ALBUM DYNAMIC RANGE': 'DR', 'ORIGINAL_TITLE': 'Original Title',
		'ORIGINAL FILENAME': 'Original Filename',
		'ORIGINALDATE': 'Original Date', 'RELEASEDATE': 'Release Date',
		'CATALOGNUMBER': 'Catalog', 'DISCOGS_RELEASE_ID': 'Discogs',
		'MUSICBRAINZ_ALBUMID': 'MusicBrainz', 'SUBTITLE': 'Version',
	}

	def read_album_dir(album_dir: str) -> dict | None:
		first_flac = next((f for f in os.listdir(album_dir) if f.endswith('.flac')), None)
		if not first_flac:
			return None
		flac_path = str(Path(album_dir) / first_flac)
		try:
			audio = FLAC(flac_path)
			raw = {k.upper(): v for k, v in audio.tags.items()}
		except Exception as e:
			logger.warning(f'read_album_dir tag read failed for {album_dir}: {e}')
			return None
		row = {DISPLAY[t]: (raw.get(t, [''])[0] if isinstance(raw.get(t), list) else raw.get(t, '') or '') for t in ALBUM_TAGS}
		try:
			import io
			from PIL import Image
			if audio.pictures:
				img = Image.open(io.BytesIO(audio.pictures[0].data))
				row['Cover Art'] = f'{img.width}x{img.height}'
			else:
				logger.info(f'read_album_dir: no pictures in {flac_path}')
				row['Cover Art'] = ''
		except Exception as e:
			logger.warning(f'cover art read failed for {album_dir}: {e}')
			row['Cover Art'] = ''
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
		child_env = {**os.environ, 'DISCOGS_CHILD': '1'}
		# Run fixtags on each album subdir
		if Path(artist_dir).is_dir():
			for entry in sorted(Path(artist_dir).iterdir()):
				if entry.is_dir() and any(f.suffix == '.flac' for f in entry.iterdir()):
					proc = _set_proc(subprocess.Popen(
						['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), str(entry)],
						stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
						text=True, cwd=str(SCRIPTS_DIR), env=child_env,
					))
					for line in proc.stdout:
						_relay_child_line('fixtags', line)
					proc.wait()
		# Run bliss on artist dir
		proc = _set_proc(subprocess.Popen(
			['uv', 'run', str(SCRIPTS_DIR / 'bliss.py'), artist_dir],
			stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
			text=True, cwd=str(SCRIPTS_DIR), env=child_env,
		))
		for line in proc.stdout:
			_relay_child_line('bliss', line)
		proc.wait()

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

	if rows:
		new_dirs = {r['Directory'] for r in rows}
		old_dirs = {str(e) for e in Path(artist_dir).iterdir() if e.is_dir()} if Path(artist_dir).is_dir() else set()
		_cache_update(rows, new_dirs | old_dirs)

	if not rows:
		return HTMLResponse(f'<tbody id="{artist_id}"></tbody>')

	artist = rows[0].get('Album Artist', '')
	# Use the original artist_id so the HTMX swap target always matches, even
	# if bliss renamed the artist directory and the artist name changed.
	trs = ''.join(render_row(r, artist_id) for r in rows)
	return HTMLResponse(f'<tbody id="{artist_id}">{trs}</tbody>')


@app.get('/lyrics', response_class=HTMLResponse)
async def lyrics_run():
	import threading
	from config import flacroot
	logger.info('lyrics: starting update')
	proc = _set_proc(subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'update_lyrics.py'), str(flacroot)],
		stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
		cwd=str(SCRIPTS_DIR), env={**os.environ, 'DISCOGS_CHILD': '1'},
	))
	def _reader():
		for line in proc.stdout:
			_relay_child_line('lyrics', line)
		proc.wait()
		if proc.returncode == 0:
			logger.info('lyrics: done')
		else:
			logger.error(f'lyrics: failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()
	return await log_modal()


@app.get('/bliss', response_class=HTMLResponse)
async def bliss_run():
	import threading
	logger.info('bliss: starting default organisation pass')
	proc = _set_proc(subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'bliss.py')],
		stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
		cwd=str(SCRIPTS_DIR), env={**os.environ, 'DISCOGS_CHILD': '1'},
	))
	def _reader():
		for line in proc.stdout:
			_relay_child_line('bliss', line)
		proc.wait()
		if proc.returncode == 0:
			logger.info('bliss: done — triggering library rescan')
			_start_album_scan('bliss')
		else:
			logger.error(f'bliss: failed (exit {proc.returncode})')
	threading.Thread(target=_reader, daemon=True).start()
	return await log_modal()


@app.get('/sync', response_class=HTMLResponse)
async def sync_start():
	global _sync
	cfg = config_read()
	source    = cfg.get('rclone_source', '')
	remote    = cfg.get('flacroot_remote', '')
	flags     = cfg.get('rclone_flags', 'sync')
	transfers = cfg.get('rclone_transfers', '16')
	checkers  = cfg.get('rclone_checkers', '32')
	buffer    = cfg.get('rclone_buffer_size', '128M')
	stats     = cfg.get('rclone_stats', '5s')

	if not source or not remote:
		logger.error('rclone sync: rclone_source or flacroot_remote not set in config')
	else:
		if _sync.get('proc') and _sync['proc'].poll() is None:
			_sync['proc'].terminate()
		import threading
		strip = {'-P', '--progress', '-v', '--verbose'}
		clean_flags = [f for f in flags.split() if f not in strip]
		rclone_log = _config_dir() / 'rclone.log'
		rclone_log.write_text('')  # truncate on each run
		rclone_conf = _config_dir() / 'rclone.conf'
		conf_flag = ['--config', str(rclone_conf)] if rclone_conf.exists() else []

		cleanup_cmd = ['rclone'] + conf_flag + [
			'cleanup',
			'--log-file', str(rclone_log),
			'--log-level', 'INFO',
			remote,
		]

		sync_cmd = ['rclone'] + conf_flag + clean_flags + [
			'--checksum',
			'--exclude', '@eaDir/**',
			'--log-file', str(rclone_log),
			'--log-level', 'INFO',
			'--stats-log-level', 'ERROR',
			'--stats-one-line', '--stats', stats,
			'--transfers', transfers,
			'--checkers', checkers,
			'--buffer-size', buffer,
			source, remote,
		]

		def _run_sequence():
			# 1. Run Cleanup
			logger.info(f"rclone cleanup started: {' '.join(cleanup_cmd)}")
			proc = _set_proc(subprocess.Popen(cleanup_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
			_sync['proc'] = proc

			# Read log file during cleanup
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

			if proc.returncode != 0:
				if proc.returncode < 0:
					logger.warning("rclone cleanup terminated by user")
					return
				logger.warning(f"rclone cleanup finished with non-zero exit code {proc.returncode}")
			else:
				logger.info("rclone cleanup finished successfully")

			# 2. Run Sync
			logger.info(f"rclone sync started: {' '.join(sync_cmd)}")
			proc = _set_proc(subprocess.Popen(sync_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
			_sync['proc'] = proc

			with open(rclone_log, 'r') as f:
				# Seek to the end of the file so we only read the new logs from sync
				f.seek(0, 2)
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
				logger.info('rclone sync done (exit 0)')
			else:
				if proc.returncode < 0:
					logger.warning("rclone sync terminated by user")
				else:
					logger.error(f'rclone sync failed (exit {proc.returncode})')

		threading.Thread(target=_run_sequence, daemon=True).start()

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


def _config_path() -> Path:
	return _config_dir() / 'config.py'

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
	'rsgain_skip':      ('rsgain Skip Existing (True/False)', 'text'),
	'log_file':         ('Log File',                          'text'),
	'log_rotation':     ('Log Rotation',                      'text'),
	'log_retention':    ('Log Retention',                     'text'),
	'syslog_host':      ('Syslog Host (Synology)',            'text'),
	'syslog_port':      ('Syslog Port',                       'text'),
	'rclone_source':     ('rclone Source',                    'text'),
	'flacroot_remote':   ('rclone Destination',               'text'),
	'rclone_flags':      ('rclone Flags',                     'text'),
	'rclone_transfers':  ('rclone Transfers',                 'text'),
	'rclone_checkers':   ('rclone Checkers',                  'text'),
	'rclone_buffer_size':('rclone Buffer Size',               'text'),
	'rclone_stats':      ('rclone Stats Interval',            'text'),
	'cover_max_size':    ('Cover Art Max Size (px)',           'text'),
	'link_url_1':        ('Link Button #1 URL',                'text'),
	'link_url_2':        ('Link Button #2 URL',                'text'),
	'link_url_3':        ('Link Button #3 URL',                'text'),
	'link_url_4':        ('Link Button #4 URL',                'text'),
	'link_url_5':        ('Link Button #5 URL',                'text'),
}


def config_read() -> dict[str, str]:
	"""Parse config.py and return active (non-commented) key=value pairs as strings."""
	text = _config_path().read_text()
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
		# unquoted value (bool, int, float, or empty) — strip any accidental quotes
		m = re.match(r'^(\w+)\s*=\s*(\S*)', line)
		if m:
			result[m.group(1)] = m.group(2).strip("'\"")
	return result


# Keys whose values are stored unquoted in config.py
_UNQUOTED = {'rsgain_loudness', 'rsgain_max_peak', 'rsgain_true_peak', 'rsgain_skip', 'rclone_transfers', 'rclone_checkers', 'cover_max_size', 'syslog_port'}


def config_write(updates: dict[str, str]) -> None:
	"""Write updated values back to config.py, preserving comments and structure.
	Keys already present are updated in-place; new keys are appended at the end."""
	lines = _config_path().read_text().splitlines()
	written = set()
	out = []
	for line in lines:
		m = re.match(r'^(\w+)\s*=\s*[\'"](.*)[\'"]\s*$', line.strip())
		if not m:
			m = re.match(r'^(\w+)\s*=\s*(\S*)', line.strip())
		if m and m.group(1) in updates:
			key = m.group(1)
			val = updates[key]
			written.add(key)
			if key in _UNQUOTED:
				out.append(f'{key} = {val}')
				continue
			quote = "'" if line.strip()[len(key):].lstrip(' =')[0] == "'" else '"'
			out.append(f"{key} = {quote}{val}{quote}")
		else:
			out.append(line)
	# Append any keys that were not found in the existing file
	for key, val in updates.items():
		if key not in written:
			if key in _UNQUOTED:
				out.append(f'{key} = {val}')
			else:
				out.append(f"{key} = '{val}'")
	_config_path().write_text('\n'.join(out) + '\n')


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
<div id="modal" style="max-height:90vh;display:flex;flex-direction:column;">
  <div id="modal-header">
    <span>{SETTINGS_TITLE}</span>
    <button onclick="closeModal()" title="Close">&times;</button>
  </div>
  <form hx-post="/settings/save" hx-target="#modal-wrap" hx-swap="innerHTML" style="display:flex;flex-direction:column;flex:1;overflow:hidden;">
    {banner}
    <div id="modal-fields" style="overflow-y:auto;flex:1;">{fields}</div>
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
	import json
	cfg = config_read()
	log_path = _config_dir() / cfg.get('log_file', 'discogs.log')
	if not log_path.exists():
		return '<span style="color:#666">(log file not found)</span>'
	lines = log_path.read_text(errors='replace').splitlines()[-LOG_TAIL:]
	out = []
	for line in lines:
		try:
			rec = json.loads(line)
			level = rec.get('level', '').upper()
			ts = rec.get('timestamp', '')
			event = rec.get('event', line)
			# Extra keys beyond the standard three
			extras = {k: v for k, v in rec.items() if k not in ('level', 'timestamp', 'event')}
			text = f'{ts} | {level:<8} | {event}'
			if extras:
				text += '  ' + '  '.join(f'{k}={v}' for k, v in extras.items())
		except (json.JSONDecodeError, ValueError):
			level = next((l for l in _LOG_COLOURS if f'| {l}' in line), None)
			text = line
		colour = _LOG_COLOURS.get(level)
		escaped = escape(text)
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
      <button hx-post="/kill" hx-swap="none" title="Kill running process"
        style="border:none;background:none;font-size:16px;cursor:pointer;color:#c44;padding:0 2px;line-height:1;">
        <i class="fa-regular fa-circle-xmark"></i>
      </button>
      <button onclick="closeModal()" title="Close">&times;</button>
    </div>
  </div>
  <pre id="log-content"
    hx-get="/log/content"
    hx-trigger="every 3s [document.getElementById('log-autorefresh')?.checked]"
    hx-swap="innerHTML"
    hx-on::after-request="if(document.getElementById('log-autoscroll')?.checked){ var el=document.getElementById('log-content'); el.scrollTop=el.scrollHeight; }"
    style="flex:1;overflow:auto;margin:0;padding:12px;background:#1e1e1e;color:#d4d4d4;
           font-family:monospace;font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-all;user-select:text;"
  >''' + _read_log_html() + '''</pre>
</div>
<script>
  (function(){ var el=document.getElementById('log-content'); el.scrollTop=el.scrollHeight; })();
</script>''')


@app.post('/kill', response_class=HTMLResponse)
async def kill_proc():
	global _current_proc
	proc = _current_proc
	if proc and proc.poll() is None:
		proc.terminate()
		logger.warning('Process killed by user')
		_current_proc = None
	else:
		logger.info('No active process to kill')
	return HTMLResponse('')


@app.get('/log/content', response_class=HTMLResponse)
async def log_content():
	html = _read_log_html()
	if _refresh_done.get('pending'):
		_refresh_done['pending'] = False
		# Out-of-band swap: replace #albums-wrap with a self-loading placeholder
		html += (
			'<div id="albums-wrap" hx-swap-oob="true"'
			' hx-get="/albums" hx-trigger="load" hx-target="#albums-wrap" hx-swap="outerHTML">'
			'<p style="padding:16px;color:#666">Reloading…</p>'
			'</div>'
		)
	return HTMLResponse(html)


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
	import threading
	form = await request.form()
	updates = {k: v for k, v in form.items() if k in CONFIG_LABELS}
	config_write(updates)
	# Re-fetch favicons for any link URLs in background
	def _refetch():
		for i in range(1, 6):
			url = updates.get(f'link_url_{i}', '').strip()
			if url:
				_cache_link_favicon(i, url)
	threading.Thread(target=_refetch, daemon=True).start()
	modal = render_settings_modal(config_read(), saved=True)
	oob = f'<div id="link-buttons" hx-swap-oob="true">{_render_link_buttons()}</div>'
	return HTMLResponse(modal + oob)


def _cache_link_favicon(n: int, url: str) -> None:
	"""Fetch favicon for link button n from url and save to config dir."""
	from urllib.parse import urlparse
	import requests as _req
	parsed = urlparse(url)
	for path in ('/favicon.ico', '/favicon.png', '/favicon-32x32.png', '/favicon-16x16.png'):
		favicon_url = f'{parsed.scheme}://{parsed.netloc}{path}'
		try:
			r = _req.get(favicon_url, timeout=5)
			logger.info(f'Favicon {n}: {favicon_url} → {r.status_code} ({len(r.content)} bytes)')
			data = r.content
			is_image = (
				data[:4] == b'\x89PNG' or
				data[:2] == b'\xff\xd8' or
				data[:4] in (b'GIF8', b'RIFF') or
				data[:4] == b'\x00\x00\x01\x00' or  # ICO
				b'<svg' in data[:64]
			)
			if r.status_code == 200 and is_image:
				dest = _config_dir() / f'link_favicon_{n}.ico'
				dest.write_bytes(data)
				return
		except Exception as e:
			logger.warning(f'Could not fetch favicon for link {n} at {favicon_url}: {e}')
	logger.warning(f'No favicon found for link {n} ({url})')


def _render_link_buttons() -> str:
	from urllib.parse import urlparse
	cfg = config_read()
	buttons = []
	for i in range(1, 6):
		url = cfg.get(f'link_url_{i}', '').strip()
		if not url:
			continue
		cached = _config_dir() / f'link_favicon_{i}.ico'
		if not cached.exists():
			_cache_link_favicon(i, url)
		favicon_src = f'/link-favicon/{i}' if cached.exists() else ''
		img = f'<img src="{favicon_src}" width="16" height="16" alt="" />' if favicon_src else '🔗'
		buttons.append(
			f'<a href="{escape(url)}" target="_blank" rel="noopener" class="link-url-btn" title="{escape(url)}">'
			f'{img}'
			f'</a>'
		)
	return ''.join(buttons)


@app.get('/link-favicon/{n}')
async def link_favicon(n: int):
	path = _config_dir() / f'link_favicon_{n}.ico'
	if not path.exists():
		return Response(status_code=404)
	data = path.read_bytes()
	if data[:4] == b'\x89PNG':
		media_type = 'image/png'
	elif data[:4] == b'<svg' or b'<svg' in data[:64]:
		media_type = 'image/svg+xml'
	elif data[:6] in (b'GIF87a', b'GIF89a'):
		media_type = 'image/gif'
	elif data[:2] == b'\xff\xd8':
		media_type = 'image/jpeg'
	else:
		media_type = 'image/x-icon'
	return Response(content=data, media_type=media_type)


@app.get('/link-buttons', response_class=HTMLResponse)
async def link_buttons():
	return HTMLResponse(_render_link_buttons())


if __name__ == '__main__':
	import socket
	logger.info(f"Python {sys.version.split()[0]}, cwd={Path.cwd()}")
	logger.info(f"SCRIPTS_DIR={SCRIPTS_DIR}")
	logger.info(f"CONFIG_DIR env={os.environ.get('CONFIG_DIR', '(not set)')}")

	cfg_dir = _config_dir()
	logger.info(f"Resolved config dir: {cfg_dir}")
	logger.info(f"config dir exists: {cfg_dir.exists()}, writable: {os.access(cfg_dir, os.W_OK)}")

	try:
		import config
		logger.info(f"config.py loaded from: {config.__file__}")
		logger.info(f"config.flacroot={getattr(config, 'flacroot', '(missing)')}")
		logger.info(f"config.config_dir={getattr(config, 'config_dir', '(missing)')}")
	except Exception as e:
		logger.error(f"Failed to import config.py: {e}")

	cfg = config_read()
	link_urls = {k: v for k, v in cfg.items() if k.startswith('link_url_') and v}
	logger.info(f"Link buttons configured: {link_urls or 'none'}")

	csv = cfg_dir / 'albums.csv'
	logger.info(f"albums.csv path: {csv} — exists: {csv.exists()}")

	host = '127.0.0.1' if not os.environ.get('CONFIG_DIR') else '0.0.0.0'
	port = int(os.environ.get('PORT', 8765))
	logger.info(f"Starting uvicorn on {host}:{port}")
	uvicorn.run('webui:app', host=host, port=port, reload=False)
