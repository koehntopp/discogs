# ADR 0007: LRCLIB Lyrics Submission & Proof-of-Work Challenge Solver Architecture

- **Status**: Accepted
- **Date**: 2026-08-05
- **Authors**: Discogs Project Maintainers

## Context

Submitting user-verified and Whisper-aligned synchronized lyrics to public repositories (such as LRCLIB at `lrclib.net`) enables community sharing and backup. LRCLIB requires a Proof-of-Work (PoW) anti-spam mechanism (`X-Publish-Token`) for all publication requests (`POST /api/publish`).

To provide seamless, single-command submission of FLAC `LYRICS` tags directly to LRCLIB, we created `lrclib_submitter.py`.

---

## Decision

We establish the following architectural rules for LRCLIB lyrics publication via `lrclib_submitter.py`:

### 1. FLAC Tag Metadata Contract
* `lrclib_submitter.py` operates on a single `.flac` target file.
* Reads required track metadata:
  * `trackName`: derived from `TITLE`
  * `artistName`: derived from `ARTIST` or `ALBUMARTIST`
  * `albumName`: derived from `ALBUM`
  * `duration`: rounded integer seconds from `FLAC.info.length`
  * `lyrics`: strictly derived from the FLAC `LYRICS` tag.

### 2. Synced vs. Plain Lyrics Routing
* If the `LYRICS` string contains `[MM:SS.xx]` timestamp patterns (`re.compile(r'\[\d{2}:\d{2}\.\d{2}\]')`), it is routed as `syncedLyrics` in the API payload.
* Otherwise, it is routed as `plainLyrics`.

### 3. Automated Proof-of-Work (PoW) Solver
* **Challenge Request**: Sends `POST https://lrclib.net/api/request-challenge` to obtain `prefix` and hexadecimal `target`.
* **Hash Puzzle Solver**: Iterates an integer counter `nonce` starting at 0 to find a SHA-256 hash satisfying `int(SHA256(prefix + nonce), 16) < int(target, 16)`.
* **Publish Token**: Constructs `X-Publish-Token: {prefix}:{nonce}` header.

### 4. API Submission & User-Agent
* Sends `POST https://lrclib.net/api/publish` with JSON payload and header `User-Agent: DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)`.
* Logs structured events (`logger.info("lyrics_published", ...)`).
* Supports `--dry-run` to preview metadata payloads without solving the PoW puzzle or contacting the publish endpoint.

---

## Consequences

* **Pros**:
  * Enables single-command submission of local FLAC `LYRICS` tags to LRCLIB.
  * Handles PoW challenge generation and SHA-256 puzzle solving automatically.
  * Preserves user tag authority and prevents malformed submissions via validation.
* **Cons**:
  * Requires active internet connectivity to `lrclib.net`.
