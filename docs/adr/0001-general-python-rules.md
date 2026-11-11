# ADR 0001: General Python Conventions and Architectural Rules

- **Status**: Accepted
- **Date**: 2026-07-27
- **Authors**: Discogs Project Maintainers

## Context

The Discogs Music Library Manager project is a Python-based ecosystem comprising core CLI batch processing tools, parallel audio file taggers, transcoding utilities, and a FastAPI/HTMX web interface. As the codebase grew to handle complex FLAC metadata parsing, parallel API integrations, tag preservation, and live logging across interactive TTY and Web UI subprocess environments, establishing clear and binding Python standards became essential.

This decision record codifies the core Python conventions, runtime expectations, logging mechanics, and code architecture rules for the repository.

---

## Decision

We adopt the following general Python standards and architectural rules across all scripts and modules in this project:

### 1. Environment & Dependency Management (`uv` & PEP 723)
* **Python Target**: Python >= 3.14.
* **Execution**: Scripts are executed exclusively via `uv run <script>.py [args]`.
* **Inline Dependencies**: Every standalone script must declare its dependencies inline using PEP 723 metadata headers (`# /// script ... # ///`). This ensures scripts remain self-contained and reproducible without manual virtual environment management.

### 2. Code Formatting & Style (Ruff Standard)
* **Style**: ruff's formatter defaults (Black-compatible: 4-space indentation, double quotes), line length 88. `target-version = "py313"` in `pyproject.toml` keeps `except (A, B):` parenthesized, because scripts run on interpreters older than 3.14 where the unparenthesized form is a syntax error.
* **Lint rules** (`[tool.ruff.lint]`): `E4 E7 E9 F I UP B SIM ANN T20 PGH`: unused imports, import order, f-strings, bare `except`, mutable defaults, required annotations, no `print()`, no blanket `noqa`/`type: ignore`. Per-file ignores, each with a reason in `pyproject.toml`: `T201` for `lrc_fix.py` (ADR 0009 section 7) and `lrc_audit.py` (CLI report output); `E402` for `bliss.py`, `fixtags.py`, `webui.py`, `lrc_fix.py` (`CONFIG_DIR` goes on `sys.path` before `from config import`).
* **Tooling**: ruff is a dev dependency, run via `uv run ruff`. After editing, on the changed files only: `ruff check --fix`, `ruff format`, `ruff check`. Before finishing, `uv run ruff check .` and `uv run ruff format --check .` pass.

### 3. Logging & Structured Diagnostics (`structlog`)
* **Unified Import**: All scripts must use the central `log.py` module (`from log import logger`).
* **Log Levels**: Standard log levels must be strictly observed (`logger.info()`, `logger.warning()`, `logger.error()`).
* **Environment-Aware Formatting**:
  * **Interactive TTY**: Outputs pretty console-rendered, colorized logs to `sys.stderr`.
  * **Subprocess / Non-TTY (Web UI Child Process)**: Outputs structured JSON lines to `sys.stdout` for line-by-line consumption and UI rendering by `webui.py`.
* **No Raw `print()`**: Raw `print()` calls in core processing logic are prohibited in favor of structured logging (enforced by rule `T20`; exceptions listed in section 2).

### 4. Progress Bars & CLI Display (`rich`)
* **Console Target**: `rich.progress.Progress` instances must attach to `Console(stderr=True)` to avoid corrupting stdout JSON streams in non-interactive modes.
* **TTY Detection**: Progress bars must evaluate terminal interactive state via `disable=not sys.stderr.isatty()`:
  * **Interactive TTY**: Displays live updating progress bars with fixed positional counter fields (`LRC`, `TXT`, `None`, `New`).
  * **Non-TTY (Web UI / Background Tasks)**: Disables ANSI terminal control codes to prevent log output corruption, falling back to periodic `logger.info()` progress broadcasts every 5 seconds.

* **Directory Scanners**: Programs that scan many album directories use the shared `scan_progress.py` (`with scan_progress(total, label, **counters) as tick:`), which implements the two modes above with the album count as total and a 5-second log interval (SPEC.md "Progress reporting for scanners").

### 5. Tagging Safety & Metadata Preservation (`mutagen`)
* **Authority Anchor**: User-set tags (e.g. `DISCOGS_RELEASE_ID`) are treated as authoritative and must never be overwritten arbitrarily.
* **Header Parsing Robustness**: Metadata header parsing and regex operations (such as LRC tag headers `[ar:...]`, `[ti:...]`) must use greedy line-boundary matching (e.g. `^\[([a-zA-Z]{2,10}):.*\]\s*$`) to safely handle bracketed values (e.g. titles with `[Remaster]`) without generating duplicate metadata entries. For LRC headers specifically, only the tool's own managed keys (`ar`/`ti`/`al`/`length`) are rewritten in place; any other id-tag line (e.g. another tool's `[re:...]`) must be left untouched at its original position rather than stripped and relocated — see ADR 0002 §6.

### 6. Concurrency & Network Operations
* **Parallel Execution**: Network-bound or batch tasks (e.g. lyrics fetching) must use `concurrent.futures.ThreadPoolExecutor` paired with thread-safe `requests.Session` and connection pooling (`HTTPAdapter`).
* **Resilience**: Network integrations must implement exponential backoff retries for rate-limiting (HTTP 429) and transient server errors. With parallel workers the back-off is shared (a single pacer sends one request at a time and widens the spacing on a real rate limit, HTTP 429, so workers do not pause and then burst together; 5xx and network errors are retried with a plain backoff and do not change the pacing), and a request that still fails is reported as failed, never as "not found": it is retried in a later pass, nothing is written or deleted on its behalf, and what remains failed is listed by name (`update_lyrics.py` is the reference implementation). Request rates follow the service's documented limits; for lrclib.net see ADR 0007 §4 (https://lrclib.net/docs#implementation-requirements-client-identification).

### 7. Configuration & Secret Isolation
* **Config File**: Configuration is managed via `config.py` (copied from `config_demo.py`).
* **Secret Protection**: Credentials, API tokens, local file paths, and environment-specific endpoints must reside in `config.py` and **must never be committed to git repositories**.

---

## Consequences

### Positive
* **Zero Environment Drift**: Scripts remain 100% reproducible via `uv run`.
* **Clean Log Window Streaming**: The Web UI log modal receives clean JSON streams without ANSI escape code garbage.
* **Metadata Integrity**: Protects audio files against tag corruption or duplicate header accumulation.
* **Maintainability**: Enforces uniform code style across all contributors and AI pair programmers.

### Negative / Trade-offs
* **Tooling Dependency**: Requires `uv` to be installed on developer workstations and deployment containers.
* **Dual Logging Boilerplate**: Terminal progress bars require explicit TTY detection logic to handle both interactive terminals and background Web UI subprocess execution cleanly.
