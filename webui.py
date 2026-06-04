# /// script
# dependencies = [
#   "fastapi",
#   "uvicorn",
#   "pandas",
#   "rich",
#   "aiofiles",
#   "mutagen",
#   "python-multipart",
# ]
# ///

from __future__ import annotations

import re
import subprocess
import time
from html import escape
from pathlib import Path
from datetime import datetime

import pandas as pd
import uvicorn
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

SCRIPTS_DIR = Path(__file__).parent
CSV_PATH = SCRIPTS_DIR / 'albums.csv'

app = FastAPI()
app.mount('/favicon', StaticFiles(directory=str(SCRIPTS_DIR / 'favicon')), name='favicon')

_refresh: dict = {'proc': None, 'started': 0.0, 'status': '', 'done': False}

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
	df = pd.read_csv(CSV_PATH, dtype=str).fillna('')
	if search:
		mask = df.apply(lambda row: row.str.contains(search, case=False).any(), axis=1)
		df = df[mask]
	if sort in df.columns:
		df = df.sort_values(sort, ascending=(order == 'asc'))
	return df.to_dict(orient='records')


def _album_link(row: dict) -> str:
	album = escape(row.get('Album', ''))
	rid = row.get('Discogs', '').strip()
	if rid:
		return f'<a href="https://www.discogs.com/release/{escape(rid)}" target="_blank" rel="noopener">{album}</a>'
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
		'https://www.discogs.com/favicon.ico', 'Discogs',
	)
	mb_cell = _icon_cell(
		f'https://musicbrainz.org/release/{escape(mb_id)}' if mb_id else '',
		'https://musicbrainz.org/favicon.ico', 'MusicBrainz',
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
				('Discogs',     'https://www.discogs.com/favicon.ico',  'Discogs'),
				('MusicBrainz', 'https://musicbrainz.org/favicon.ico',  'MusicBrainz'),
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
    .tab-btn {
      padding: 5px 12px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px;
    }
    .tab-btn.active { background: #fff; font-weight: 600; }
    .panel { display: none; }
    .panel.active { display: block; }
    #albums-panel { overflow: auto; height: calc(100vh - 45px); }
    table { border-collapse: collapse; width: 100%; }
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
      padding: 5px 12px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px;
    }
    #refresh-btn.htmx-request { color: #999; cursor: default; }
    #settings-btn {
      margin-left: auto; padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px;
      background: #eee; cursor: pointer; font-size: 13px; color: #555;
    }
    #settings-btn:hover { background: #e0e0e0; }
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
    #pipeline-panel { padding: 16px; height: calc(100vh - 45px); overflow: auto; }
    .pipeline-form { display: flex; flex-direction: column; gap: 10px; max-width: 500px; }
    .pipeline-form label { font-weight: 600; }
    .pipeline-form input[type=text] {
      padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px;
    }
    .pipeline-form button {
      padding: 7px 16px; border: 1px solid #999; border-radius: 4px;
      background: #fff; cursor: pointer; font-size: 13px; width: fit-content;
    }
    .pipeline-form button:hover { background: #f0f0f0; }
    #log {
      margin-top: 16px; background: #1e1e1e; color: #d4d4d4;
      padding: 12px; border-radius: 6px; font-family: monospace; font-size: 12px;
      min-height: 120px; max-height: calc(100vh - 240px); overflow-y: auto;
    }
    .log-line { white-space: pre-wrap; line-height: 1.6; }
    .log-done { color: #6ec96e; font-weight: 600; }
  </style>
</head>
<body>
  <div class="toolbar">
    <h1>Discogs Library</h1>
    <button class="tab-btn active" id="btn-albums" onclick="switchTab('albums')">Albums</button>
    <button class="tab-btn" id="btn-pipeline" onclick="switchTab('pipeline')">Pipeline</button>
    <input type="search" name="search" id="search-box" placeholder="Search…"
      hx-get="/albums" hx-trigger="input changed delay:300ms, search"
      hx-target="#albums-wrap" hx-swap="outerHTML"
      hx-include="[name='search']" />
    <button id="refresh-btn"
      hx-get="/refresh/start"
      hx-target="#refresh-status"
      hx-swap="outerHTML"
      hx-disabled-elt="this">Refresh</button>
    <span id="refresh-status"></span>
    <span id="count"></span>
    <button id="settings-btn"
      hx-get="/settings" hx-target="#modal-wrap" hx-swap="innerHTML">
      <i class="fa-solid fa-gear"></i>
    </button>
  </div>
  <div id="modal-wrap"></div>

  <div class="panel active" id="albums-panel">
    <div id="albums-wrap"
      hx-get="/albums" hx-trigger="load"
      hx-target="#albums-wrap" hx-swap="outerHTML">
      <p style="padding:16px;color:#666">Loading…</p>
    </div>
  </div>

  <div class="panel" id="pipeline-panel">
    <div class="pipeline-form">
      <label for="dir-input">Directory to process</label>
      <input type="text" id="dir-input" name="directory" placeholder="/path/to/flacs" />
      <button hx-get="/run-pipeline" hx-include="#dir-input"
        hx-target="#log" hx-swap="innerHTML">Run Pipeline</button>
    </div>
    <div id="log"><span style="color:#666">Output will appear here.</span></div>
  </div>

  <script>
    function switchTab(name) {
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(name + '-panel').classList.add('active');
      document.getElementById('btn-' + name).classList.add('active');
      const search = document.getElementById('search-box');
      const count  = document.getElementById('count');
      search.style.display = name === 'albums' ? '' : 'none';
      count.style.display  = name === 'albums' ? '' : 'none';
    }
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


_SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

def _status_span(elapsed: float, status: str = '') -> str:
	spin = _SPINNER[int(elapsed) % len(_SPINNER)]
	detail = f' {status}' if status else ''
	return (
		f'<span id="refresh-status" style="color:#666;font-family:monospace;font-size:12px"'
		f' hx-get="/refresh/status" hx-trigger="every 1s" hx-swap="outerHTML">'
		f'{spin} {elapsed:.0f}s{detail}'
		f'</span>'
	)


@app.get('/refresh/start', response_class=HTMLResponse)
async def refresh_start():
	global _refresh
	if _refresh['proc'] and _refresh['proc'].poll() is None:
		_refresh['proc'].terminate()
	from config import flacroot
	proc = subprocess.Popen(
		['uv', 'run', str(SCRIPTS_DIR / 'album_list.py'), str(flacroot)],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		cwd=str(SCRIPTS_DIR),
	)
	_refresh = {'proc': proc, 'started': time.monotonic(), 'status': '', 'done': False}
	return HTMLResponse(_status_span(0))


@app.get('/refresh/status', response_class=HTMLResponse)
async def refresh_status():
	global _refresh
	proc = _refresh.get('proc')
	if proc is None:
		return HTMLResponse('<span id="refresh-status"></span>')

	elapsed = time.monotonic() - _refresh['started']

	if not _refresh['done']:
		import select
		while select.select([proc.stdout], [], [], 0)[0]:
			line = proc.stdout.readline()
			if not line:
				break
			line = line.strip()
			if 'Done:' in line:
				proc.wait()
				_refresh['done'] = True
				_refresh['status'] = line
				break
			if line:
				_refresh['status'] = line

	if _refresh['done']:
		rows = load_albums()
		table_html = render_table(rows, 'Album Artist', 'asc', '')
		oob_table = table_html.replace('<div id="albums-wrap">', '<div id="albums-wrap" hx-swap-oob="outerHTML">', 1)
		return HTMLResponse(f'<span id="refresh-status"></span>{oob_table}')

	return HTMLResponse(_status_span(elapsed, _refresh['status']))


@app.get('/reprocess', response_class=HTMLResponse)
async def reprocess(artist_dir: str = Query(...), artist_id: str = Query(...)):
	import os

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

	# Run fixtags on each album dir, then bliss on the artist dir
	if Path(artist_dir).is_dir():
		for entry in sorted(Path(artist_dir).iterdir()):
			if entry.is_dir() and any(f.suffix == '.flac' for f in entry.iterdir()):
				subprocess.run(
					['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), str(entry)],
					stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
					cwd=str(SCRIPTS_DIR),
				)
	subprocess.run(
		['uv', 'run', str(SCRIPTS_DIR / 'bliss.py'), artist_dir],
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
		cwd=str(SCRIPTS_DIR),
	)

	# Re-read all album subdirs under the artist directory
	def read_album_dir(album_dir: str) -> dict | None:
		first_flac = next((f for f in os.listdir(album_dir) if f.endswith('.flac')), None)
		if not first_flac:
			return None
		try:
			from mutagen.flac import FLAC
			audio = FLAC(str(Path(album_dir) / first_flac))
			raw = {k.upper(): v for k, v in audio.tags}
		except Exception:
			return None
		row = {DISPLAY[t]: (raw.get(t, [''])[0] if isinstance(raw.get(t), list) else raw.get(t, '') or '') for t in ALBUM_TAGS}
		row['Directory'] = album_dir
		return row

	rows = []
	if Path(artist_dir).is_dir():
		for entry in sorted(Path(artist_dir).iterdir()):
			if entry.is_dir():
				row = read_album_dir(str(entry))
				if row:
					rows.append(row)

	if not rows:
		return HTMLResponse(f'<tbody id="{artist_id}"></tbody>')

	artist = rows[0].get('Album Artist', '')
	return HTMLResponse(render_artist_tbody(artist, rows))


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
	'discogs_api_key': ('Discogs API Key',   'text'),
	'tagger_scheme':   ('Tagger URL Scheme', 'text'),
	'flacroot':        ('FLAC Library Root', 'text'),
	'mp3root':         ('MP3 Mirror Root',   'text'),
	'flacroot_local':  ('FLAC Root (local)', 'text'),
	'rsgain_args':     ('rsgain Arguments', 'text'),
}


def config_read() -> dict[str, str]:
	"""Parse config.py and return active (non-commented) key=value pairs."""
	text = CONFIG_PATH.read_text()
	result = {}
	for line in text.splitlines():
		line = line.strip()
		if line.startswith('#') or not line:
			continue
		m = re.match(r'^(\w+)\s*=\s*[\'"](.*)[\'"]\s*$', line)
		if m:
			result[m.group(1)] = m.group(2)
	return result


def config_write(updates: dict[str, str]) -> None:
	"""Write updated values back to config.py, preserving comments and structure."""
	lines = CONFIG_PATH.read_text().splitlines()
	out = []
	for line in lines:
		m = re.match(r'^(\w+)\s*=\s*[\'"](.*)[\'"]\s*$', line.strip())
		if m and m.group(1) in updates:
			key = m.group(1)
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
