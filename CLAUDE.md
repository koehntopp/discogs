# Discogs Music Library Manager

A collection of Python scripts to manage a local FLAC music library using Discogs
metadata, paired with a FastAPI/HTMX web UI. Full CLI/API/tag reference: `SPEC.md`.

## Core Philosophy

- **User Tag Authority**: All metadata enrichment is anchored by user-set tags (e.g.
  `DISCOGS_RELEASE_ID`). User-set tags lead wherever they are present, and no script is
  allowed to overwrite them arbitrarily or destructively. User-set tags include
  `DISCOGS_RELEASE_ID`, `CATALOGNUMBER`, `MUSICBRAINZ_ALBUMID`, `ALBUM_FORMAT`,
  `ALBUM_EDITION`, `ALBUM_TITLE_OVERRIDE`, `ALBUM_ARTIST_OVERRIDE`, `SET SUBTITLE`,
  `SUBTITLE` and the ripper tags (`ARTIST`, `TITLE`, `ALBUMARTIST`, ...).
- **Discogs Is the System of Record**: Every other tag `fixtags.py` writes is derived from
  the Discogs release (and its master) and is overwritten on every run whenever it
  disagrees with the Discogs data, so changing `DISCOGS_RELEASE_ID` always updates them.
  A tag the tool wrote must never be read back as input for itself; the value must come
  from Discogs. If Discogs has data for a field, it is taken in. `ALBUM_RELEASE_YEAR` is
  taken only from the Discogs release's own year, never from any tag. The one exception is
  `LYRICS_LANGUAGE` (per-track sung language): Discogs has none, so it comes from MusicBrainz,
  anchored by the user-set `MUSICBRAINZ_ALBUMID` (ADR 0002 section 5b).

## Agent Guidelines & Approval Workflow

- **Mandatory Implementation Plans**: You MUST create an `implementation_plan.md` artifact for any change, regardless of how minor or trivial it seems. Do not skip the planning phase for simple tweaks or quick bug fixes.
- **No Unapproved Edits**: You are strictly prohibited from modifying any source code files, configurations, or running write/exec commands until the user has explicitly approved the implementation plan.
- **Discuss First**: Always discuss your proposed design choices with the user and wait for approval before shifting from the planning/research phase to the execution phase.
- **Mandatory Automatic Documentation Synchronization**: After every code change, specification and documentation files (`SPEC.md`, `README.md`, `docs/tag-schema.md`, and ADRs in `docs/adr/`) MUST be automatically updated to reflect the new codebase state, ensuring documentation is never outdated. In particular: `README.md` whenever setup requirements, config keys, scripts, or CLI options change; `docs/tag-schema.md`'s Mermaid ERD whenever a FLAC tag is added, removed, or its derivation changes.
- **`lrc_fix.py` / `lrc_format.py` Documentation Map**: `lrc_fix.py` has its own documentation set, and a change to `lrc_fix.py` or `lrc_format.py` MUST update, in the same commit: `README-lrc_fix.md` (the options table and the matching section), the `lrc_fix.py` section of `SPEC.md`, and `docs/adr/0009-lrc-fix-local-realignment.md` (edit it when a decision changes; when a decision is replaced, write a new ADR and mark 0009 Superseded). A change to the contract `lrc_format.py` shares with `update_lyrics.py` also updates ADR 0002 section 6; a change to the tags `lrc_fix.py` writes also updates `docs/tag-schema.md`. Run `uv run check_docs.py` before committing: it fails when a `lrc_fix.py` flag is missing from the README options table (or the table lists a flag that no longer exists), or a package pinned in `lrc_fix.py` is missing from the SPEC dependencies line.
- **Mandatory Meaningful Git Commits & Push**: After completing every code change and verifying tests/linting, all modified files MUST be committed with a concise, descriptive, and meaningful Git commit message summarizing the work completed, then immediately pushed to the `github` remote (`git push github main`). Do not let commits pile up unpushed.
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
- `fixtags.py`: Discogs API metadata enrichment & tag normalization; also writes the per-track `LYRICS_LANGUAGE` from MusicBrainz (`--languages-only` for just that).
- `bliss.py`: File/folder organization and MP3 mirror sync (`ffmpeg`).
- `album_list.py`: Scans FLAC library, outputs `albums.csv` and `albums_dr.png`.
- `update_lyrics.py`: Parallel lyrics fetcher from lrclib.net with backoff retry logic.
- `lrclib_submitter.py`: Submits FLAC file lyrics to LRCLIB API (`lrclib.net`) with PoW challenge solver.
- `calculate_dr.py`: Dynamic Range calculation per track and album (`drmeter`).
- `calculate_fp.py`: AcoustID acoustic fingerprint generation (`fpcalc` / `pyacoustid`).
- `convert_opus.py`: Transcodes FLAC to Opus format.
- `lrc_fix.py`: Local (no cloud API) LRC realignment via demucs vocal isolation + whisperx transcription + onset snapping. Own docs: `README-lrc_fix.md`; design: ADR 0009.
- `lrc_audit.py`: Audit of the `lrc_count.py --suspects` tracks (tag vs lrclib vs `lrc_fix` transcript); runs `lrc_fix.py --dry-run`, so it needs the `lrc_fix` environment. Its only library write is `fix --apply` (repair tiers `safe`/`instrumental`/`shifted`/`onetimestamp`, from the cache, old tags saved, `revert`). Report: `docs/lrc-suspects-audit.md`.
- `disc_layout.py`: Shared helpers for the multi-disc `Disc N` folder layout (no CLI) — imported by `bliss.py`, `fixtags.py`, `album_list.py`, `webui.py`, `calculate_dr.py`, `lrc_count.py`, `migrate_tags.py`. ADR 0005 §1.
- `lrc_format.py`: Shared LRC id-tag/header formatting (no CLI) — imported by `update_lyrics.py`, `lrc_fix.py`, and `lrc_count.py`.
- `musicbrainz_client.py`: MusicBrainz release lookup for the per-track sung languages (no CLI, cached, 1 request/s) — imported by `fixtags.py`. ADR 0002 §5b.
- `lrclib_client.py`: Shared lrclib.net client identification (`User-Agent` + public `Lrclib-App-Id`, no CLI) — imported by `update_lyrics.py` and `lrclib_submitter.py`. Limits/requirements: ADR 0007 §4.
- `check_docs.py`: Checks that `lrc_fix.py`'s flags and dependency pins match `README-lrc_fix.md` and `SPEC.md` (no config needed).
- `log.py`: Central structured logging (`structlog`).
- `SPEC.md`: Full CLI, API, tag contract, and web UI specification.
- `docs/tag-schema.md`: Mermaid ERD of the FLAC tag relationships (derived reference for ADR 0002/0008).

## Architectural Decision Records

Detailed architectural standards and design contracts, loaded automatically as project context:

@docs/adr/0001-general-python-rules.md
@docs/adr/0002-flac-tag-handling.md
@docs/adr/0003-webui-architecture-and-subprocess-management.md
@docs/adr/0004-performance-caching-and-lyrics-export-architecture.md
@docs/adr/0005-mp3-transcoding-and-library-comparison.md
@docs/adr/0007-lrclib-lyrics-submission-proof-of-work.md
@docs/adr/0008-roon-specific-tag-conventions.md
@docs/adr/0009-lrc-fix-local-realignment.md

## Approach
- Read existing files before writing. Don't re-read unless changed.
- Thorough in reasoning, concise in output.
- Skip files over 100KB unless required.
- No sycophantic openers or closing fluff.
- No emojis or em-dashes.
- Do not guess APIs, versions, flags, commit SHAs, or package names. Verify by reading code or docs before asserting.