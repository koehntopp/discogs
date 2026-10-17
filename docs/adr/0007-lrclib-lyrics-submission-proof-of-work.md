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

### 4. API Submission, Client Identification & Rate Limits
* Sends `POST https://lrclib.net/api/publish` with JSON payload. Every lrclib.net request in this project (the `request-challenge` and `publish` calls here, and `GET /api/get` in `update_lyrics.py`) carries the headers from `lrclib_client.lrclib_headers()`: `User-Agent: DiscogsMusicManager/1.0 (+https://github.com/koehntopp/discogs)` and `Lrclib-App-Id: <registered id>`.
* **Client identification** follows lrclib's documented requirements: https://lrclib.net/docs#implementation-requirements-client-identification. The User-Agent names the application, its version and a link. `Lrclib-App-Id` is the header for registered *client-side* applications; lrclib states that the ID "is not a secret, so it is safe to ship in a client", so it is a constant in `lrclib_client.py` (shared by both scripts) rather than a `config.py` setting. The secret `Lrclib-Api-Key` header (server-side applications) is not used. Headers are optional to lrclib, but an invalid value is rejected with `401 Unauthorized`; `update_lyrics.py` logs that once and does not retry.
* **Rate limits** (approximate, per IP, may change without notice; see the same URL): about 90 requests/min with a User-Agent alone, about 180/min with a registered `Lrclib-App-Id`, plus an app-wide allowance. `update_lyrics.py` therefore spaces requests 0.4 s apart at best (150/min) and must honor `Retry-After` with up to 30% random jitter. `lrclib_submitter.py` sends a handful of requests per run and needs no pacing.
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
