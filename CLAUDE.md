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

# Code Style
Enforced by ruff. Key rules:

Line length: 100
Import order: stdlib → third-party → local, separated by blank lines
No unused imports — ruff will catch them
f-strings over .format() and % formatting
Walrus operator (:=) for pattern-match assignments only
Type annotations required for:

All function signatures (parameters + return type)
Class attributes
Module-level variables that are not obvious primitives
Anti-Patterns
No bare except: — always except SpecificError: or except (Error1, Error2):
No from module import *
No print() for debug output — use logging.getLogger(__name__)
No hardcoded credentials or connection strings — use environment variables
No mutable default arguments: def f(x: list = []) is wrong
No type: ignore comments without an explanation of why
No Any unless genuinely necessary (document why)

## Python formatting & linting

## Python: linting, formatting, code style

### Tooling
- Ruff is the only linter and formatter. Do not install or run Black, isort, or flake8.
- Always run Ruff through uv: `uv run ruff ...`.
- Config lives in `pyproject.toml`. Do not modify `[tool.ruff]` unless the task is about tooling.
- If a lint rule seems wrong for the codebase, say so in your summary instead of disabling it.

### Workflow
After editing any Python file, run these in order on the files you changed:
1. `uv run ruff check --fix <changed files>`
2. `uv run ruff format <changed files>`
3. `uv run ruff check <changed files>` (must report zero errors)

- Format only the files you changed. Never run `uv run ruff format .` on the whole
  repo unless explicitly asked, because unrelated reformatting pollutes the diff.
- Do not use `--unsafe-fixes` unless asked.
- Never hand-format code to "look nicer". The formatter's output is final.

### Before marking done
- `uv run ruff check .` passes
- `uv run ruff format --check .` passes (read-only check; it does not rewrite files)

### Style
- Line length: 100.
- Imports: stdlib → third-party → local, separated by blank lines. Ruff sorts them
  (rule set `I`), so don't reorder them manually.
- No unused imports.
- Use f-strings, not `.format()` or `%` formatting.
- Use the walrus operator (`:=`) only to bind a match result in a condition,
  e.g. `if m := re.match(...)`.

### Type annotations
Required for:
- all function signatures (every parameter and the return type)
- class attributes
- module-level variables, unless they are obvious primitives

Avoid `Any`. If it's genuinely necessary, add a comment saying why.

### Anti-patterns
- No bare `except:`. Catch specific errors: `except ValueError:` or `except (A, B):`.
- No `from module import *`.
- No `print()` for debug output. Use `logging.getLogger(__name__)`.
- No hardcoded credentials or connection strings. Use environment variables.
- No mutable default arguments: `def f(x: list = [])` is wrong; use `None` and
  create the list inside the function.

### Suppressions
- Don't add `# noqa`, `# fmt: off`, or `# type: ignore` to silence a warning.
  Fix the underlying issue.
- If suppression is truly required, use the narrowest form (`# noqa: B008`,
  `# type: ignore[arg-type]`, never bare) and add a one-line reason.
  
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
- `calculate_dr.py`: Dynamic Range calculation per track and album (wraps the `drcalc` binary).
- `calculate_fp.py`: AcoustID acoustic fingerprint generation (`fpcalc` / `pyacoustid`).
- `convert_opus.py`: Transcodes FLAC to Opus format.
- `lrc_fix.py`: Local (no cloud API) LRC realignment via demucs vocal isolation + whisperx transcription + onset snapping. Own docs: `README-lrc_fix.md`; design: ADR 0009.
- `lrc_audit.py`: Audit of the `lrc_count.py --suspects` tracks (tag vs lrclib vs `lrc_fix` transcript); runs `lrc_fix.py --dry-run`, so it needs the `lrc_fix` environment. Its only library write is `fix --apply` (repair tiers `safe`/`instrumental`/`shifted`/`onetimestamp`, from the cache, old tags saved, `revert`). Report: `docs/lrc-suspects-audit.md`.
- `check_multidisc.py`: Read-only report (CSV with Yate links) of albums that classify as multi disc: disc count > 1 (tags or `Disc N` folders), more than one `SET SUBTITLE`, or mixed sample rate / bit depth.
- `scan_progress.py`: Shared progress display for directory scanners (no CLI): rich bar in a TTY, 5-second `logger.info` lines in the web app. Rule: SPEC.md "Progress reporting for scanners".
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
@docs/adr/0010-library-sync-on-rock.md

## Approach
- Read existing files before writing. Don't re-read unless changed.
- Thorough in reasoning, concise in output.
- Skip files over 100KB unless required.
- No sycophantic openers or closing fluff.
- No emojis or em-dashes.
- Do not guess APIs, versions, flags, commit SHAs, or package names. Verify by reading code or docs before asserting.