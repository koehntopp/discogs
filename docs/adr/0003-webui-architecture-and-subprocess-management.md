# ADR 0003: Web UI Architecture, Process Lifecycle, and Asset Management

- **Status**: Accepted
- **Date**: 2026-08-01 (Updated)
- **Authors**: Discogs Project Maintainers

## Context

The Discogs Music Library Manager includes a web-based dashboard (`webui.py`) built on FastAPI, Jinja2, and HTMX. The Web UI provides a live album table (with sorting, filtering, Dynamic Range visual indicators, and tagger links) and serves as an interactive control panel for invoking batch processing tasks (`fixtags.py`, `bliss.py`, `update_lyrics.py`, `nzbfix.py`).

Because batch CLI operations run as child subprocesses, the Web UI needs a reliable mechanism to execute long-running tasks asynchronously, broadcast real-time log output to the frontend modal without blocking the main event loop, allow manual process termination (kill button), and cache external assets (such as site favicons and toolbar link button icons).

---

## Decision

We establish the following architectural conventions for `webui.py` and its interaction with child subprocesses:

### 1. Web Framework & Interactivity (FastAPI + HTMX)
* **Server**: FastAPI application running on port 8000 (configurable via `PORT` environment variable).
* **Frontend**: Dynamic UI updates driven by HTMX endpoints rendering server-side Jinja2 templates (`templates/index.html`, `templates/albums.html`).

### 2. Main Inventory Table Layout & Column Sequence
* **Binding Column Order**:
  `[reprocess]` | `Album Artist` | `Album` | `Format` | `Edition` | `Release Date` | `Original Date` | `DR` | `[Discogs icon]` | `[MusicBrainz icon]` | `Catalog` | `Cover Art`
* **Format Positioning**: The `Format` column MUST be positioned immediately to the left of the `Edition` column.
* **Header Alignment Guarantee**: The `COLUMNS` header array in `webui.py` MUST match the data cells in `render_row()` 1-to-1 to prevent header/cell misalignment.
* **Reprocess Button Styling**: The reprocess icon button on the left of each row MUST use `.reprocess-btn` styling (compact 20px circular button: `width: 20px; height: 20px; border-radius: 50%; font-size: 10px;`).

### 3. Automatic Site Favicon Caching (`_ensure_site_favicons`)
* Site favicons for **Discogs** (`/favicon/discogs.png`), **MusicBrainz** (`/favicon/musicbrainz.png`), and **Album Art Exchange** (`/favicon/albumartexchange.png`) are automatically fetched and cached locally into `SCRIPTS_DIR / 'favicon'` on startup.
* Served locally via `app.mount('/favicon', StaticFiles(directory=str(SCRIPTS_DIR / 'favicon')))` to ensure instant loading, zero 404 broken icons, and no external network leaks during UI rendering.

### 4. Custom Toolbar Link Buttons & Favicon Caching
* Up to 5 configurable external link buttons are supported via `config.py` (`link_1_name`, `link_1_url`, ...).
* Favicons for configured URLs are automatically fetched and cached locally as `link_favicon_N.ico` in `config_dir`. Cached favicons are served directly by `webui.py` to prevent redundant external network calls.

### 5. Child Process Lifecycle Management (`_current_proc`)
* **Single Active Subprocess**: Only one heavy batch CLI task (`fixtags`, `bliss`, `update_lyrics`, `nzbfix`) can execute at a time.
* **Process Tracking**: Global reference functions (`_set_proc()`, `_clear_proc()`, `_get_proc()`) manage the active `asyncio.subprocess.Process` instance.
* **Process Termination**: The UI log modal includes an emergency Kill button endpoint (`POST /log/kill`), which sends `SIGTERM` / `SIGKILL` to `_current_proc` and clears process state.

### 6. Structured Subprocess Log Streaming (JSON over `sys.stdout`)
* When scripts run as child processes under `webui.py`, standard output is non-interactive (`sys.stderr.isatty() == False`).
* Per ADR 0001, scripts emit structured JSON lines to `sys.stdout`. `webui.py` reads these JSON lines line-by-line using asynchronous stream reading.
* JSON events are parsed, formatted into HTML log entries (with level-based color badges, e.g. green for `SUCCESS`), and streamed live to the HTMX log modal via HTTP response streams.

---

## Consequences

### Positive
* **Real-time Diagnostics**: Users view clean, live-streamed log output in the Web UI without ANSI terminal corruption.
* **Strict Visual & Layout Integrity**: Enforces column alignment and 20px button sizing across all browsers.
* **Zero External Favicon Leaks**: Cached favicons improve toolbar and table rendering speed and preserve privacy.

### Negative / Trade-offs
* All CLI batch scripts must strictly emit valid JSON lines to `sys.stdout` when executed in non-TTY environments.
