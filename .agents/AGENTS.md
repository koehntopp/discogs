# Antigravity Agent Guidelines — Discogs Music Library Manager

## After Every Commit
- After completing changes and making a commit, update relevant specification and documentation files (`SPEC.md`, `README.md`, and ADRs in `docs/adr/`) to reflect the current project state.
- Keep all documentation accurate and synchronized with the codebase.

## Project Overview & Core Philosophy
- A collection of Python scripts to manage a local FLAC music library using Discogs metadata, paired with a FastAPI/HTMX web UI.
- **User Tag Authority**: All metadata enrichment is anchored by user-set tags (e.g. `DISCOGS_RELEASE_ID`). No script is allowed to overwrite user-set tags arbitrarily or destructively.

## Package Management & Execution
- **Package Manager**: Managed via `uv` (requires Python >= 3.14).
- **Execution**: Execute standalone scripts exclusively via `uv run <script>.py [args]`.
- **Inline Dependencies**: Scripts declare dependencies using PEP 723 metadata headers (`# /// script ... # ///`).

## Code Style & Formatting (Ruff)
- Single quotes (`'...'`) for string literals.
- Tabs for indentation (`indent-width = 4`).
- Maximum line length: 100 characters.
- Run formatter and linter:
  ```bash
  uvx ruff format .
  uvx ruff check .
  ```

## Logging Mechanics (`log.py`)
- Import logger via `from log import logger` (or `from log import logger, success`).
- **Interactive TTY**: Formats colorized logs to `sys.stderr`.
- **Subprocess / Non-TTY (Web UI child process)**: Formats structured JSON lines to `sys.stdout` so `webui.py` can parse and display logs in real-time.
- **Progress Bars (`rich`)**: Use `Console(stderr=True)` for `rich.progress.Progress`. Set `disable=not sys.stderr.isatty()`. In TTY mode, redirect `_console_handler.stream = sys.stderr` inside `with progress:` so log messages print cleanly above the active progress bar.

## Key System Components
- `webui.py`: FastAPI + HTMX web UI on port 8000.
- `nzbfix.py`: Pipeline orchestration script (`dot_clean` -> `calculate_dr` -> `rsgain` -> `calculate_fp` -> `fixtags` -> `update_lyrics`).
- `fixtags.py`: Discogs API metadata enrichment & tag normalization.
- `bliss.py`: File/folder organization and MP3 mirror sync (`ffmpeg`).
- `album_list.py`: Scans FLAC library, outputs `albums.csv` and `albums_dr.png`.
- `update_lyrics.py`: Parallel lyrics fetcher from lrclib.net with backoff retry logic.
- `calculate_dr.py`: Dynamic Range calculation per track and album (`drmeter`).
- `calculate_fp.py`: AcoustID acoustic fingerprint generation (`fpcalc` / `pyacoustid`).
- `convert_opus.py`: Transcodes FLAC to Opus format.
- `log.py`: Central structured logging (`structlog`).
- `docs/adr/`: Architectural Decision Records (ADRs).
- `SPEC.md`: Full CLI, API, tag contract, and web UI specification.
