# Discogs Music Library Manager

A collection of Python scripts to manage a local FLAC music library using Discogs
metadata, paired with a FastAPI/HTMX web UI. Full CLI/API/tag reference: `SPEC.md`.

## Core Philosophy

- **User Tag Authority**: All metadata enrichment is anchored by user-set tags (e.g.
  `DISCOGS_RELEASE_ID`). No script is allowed to overwrite user-set tags arbitrarily or
  destructively.

## Agent Guidelines & Approval Workflow

- **Mandatory Implementation Plans**: You MUST create an `implementation_plan.md` artifact for any change, regardless of how minor or trivial it seems. Do not skip the planning phase for simple tweaks or quick bug fixes.
- **No Unapproved Edits**: You are strictly prohibited from modifying any source code files, configurations, or running write/exec commands until the user has explicitly approved the implementation plan.
- **Discuss First**: Always discuss your proposed design choices with the user and wait for approval before shifting from the planning/research phase to the execution phase.
- **Mandatory Automatic Documentation Synchronization**: After every code change, specification and documentation files (`SPEC.md`, `README.md`, and ADRs in `docs/adr/`) MUST be automatically updated to reflect the new codebase state, ensuring documentation is never outdated.
- **Mandatory Meaningful Git Commits**: After completing every code change and verifying tests/linting, all modified files MUST be committed with a concise, descriptive, and meaningful Git commit message summarizing the work completed.
- **No Production Data Testing**: NEVER run verification tests or test code on active/production library data (e.g. `/Volumes/FLAC`). When required, copy a small subset of the target files to a temporary directory (e.g., `/tmp`) on a completely different root path before testing.

## Package Management & Execution

- **Package Manager**: Managed via `uv` (requires Python >= 3.14).
- **Execution**: Execute standalone scripts exclusively via `uv run <script>.py [args]`.
- **Inline Dependencies**: Scripts declare dependencies using PEP 723 metadata headers (`# /// script ... # ///`).
- **Shebang**: All standalone Python scripts begin with the `uv` shebang line:
  ```python
  #!/usr/bin/env -S uv run
  ```
  This lets scripts be executed directly from the terminal (e.g. `./fixtags.py [args]` or `./bliss.py [args]`), equivalent to `uv run <script>.py [args]`. Inline PEP 723 dependencies are installed automatically either way.

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
- `lrclib_submitter.py`: Submits FLAC file lyrics to LRCLIB API (`lrclib.net`) with PoW challenge solver.
- `calculate_dr.py`: Dynamic Range calculation per track and album (`drmeter`).
- `calculate_fp.py`: AcoustID acoustic fingerprint generation (`fpcalc` / `pyacoustid`).
- `convert_opus.py`: Transcodes FLAC to Opus format.
- `log.py`: Central structured logging (`structlog`).
- `SPEC.md`: Full CLI, API, tag contract, and web UI specification.

## Architectural Decision Records

Detailed architectural standards and design contracts, loaded automatically as project context:

@docs/adr/0001-general-python-rules.md
@docs/adr/0002-flac-tag-handling.md
@docs/adr/0003-webui-architecture-and-subprocess-management.md
@docs/adr/0004-performance-caching-and-lyrics-export-architecture.md
@docs/adr/0005-mp3-transcoding-and-library-comparison.md
@docs/adr/0006-whisper-lrc-alignment-and-fallback.md
@docs/adr/0007-lrclib-lyrics-submission-proof-of-work.md
