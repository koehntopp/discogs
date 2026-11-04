# ADR 0007: LRCLIB Lyrics Submission & Proof-of-Work Challenge Solver Architecture

- **Status**: Accepted
- **Date**: 2026-08-05 (Updated 2026-11-04: section 4 pacing, no burst)
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
* **Rate limits** (approximate, per IP, may change without notice; see the same URL): about 90 requests/min with a User-Agent alone, about 180/min with a registered `Lrclib-App-Id`, plus an app-wide allowance. lrclib also recommends sending requests sequentially with 200-500 ms between them. `update_lyrics.py` therefore keeps one request in flight and paces them like the official client, lrcget (https://github.com/tranxuanthang/lrcget, `src-tauri/src/lrclib/client.rs`, `src/composables/downloader.js`): after each response it waits 0.5 s plus 0 to 0.25 s of random jitter before the next request starts, about 85 requests/min including latency, steady from the first request. There is no burst allowance. An earlier version started the first 120 requests 0.2 s apart (300/min, above even the registered allowance) to finish small runs quickly; it provoked 429s and a slow fallback, while lrcget fetched 69 files in one run without interruption, so the speed-up was dropped. A 429 doubles the spacing (up to 8 s), every 10 consecutive good answers shrink it by a quarter, `Retry-After` is honored with up to 30% random jitter (a 429 without the header is treated as 1 s, as lrcget does) and delays every worker, and 5xx/network errors are retried with a plain backoff (4 attempts, as lrcget's batch policy) without changing the pacing. The registered `Lrclib-App-Id` is kept. `lrclib_submitter.py` sends a handful of requests per run and needs no pacing.
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
