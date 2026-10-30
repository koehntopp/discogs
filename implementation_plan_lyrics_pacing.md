# Implementation plan: update_lyrics.py burst allowance for small runs

## Problem

`Pacer` (`update_lyrics.py`) starts lrclib requests at least `BASE_INTERVAL` = 0.5 s apart, always.
That is 120 requests/min, so a set of 12 tracks takes 6 s of pure waiting even though lrclib allows
~180/min for a registered `Lrclib-App-Id`. The spacing only matters once a run would exceed the
per-minute allowance.

## Design: sliding-window budget instead of a fixed gap

Replace "one start per 0.5 s" by "at most `REQUESTS_PER_MINUTE` (120) request starts in any 60 s
window". Same average rate as today, but front-loaded:

- A run needing at most 120 lrclib requests (tracks already holding LRC need none) never waits:
  requests go back to back, limited only by round-trip time.
- A larger run sends the first 120 immediately, then each further start waits until the oldest start
  in the window ages out, which converges to the current 0.5 s steady state. Total time for large
  runs is unchanged; small runs get much faster.
- No pre-count is needed: the window gives the result the user asked for (little work = no brakes)
  without a separate planning pass, and also adapts when some tracks need no request.

Kept as is: one request in flight (`_slot` semaphore), `Retry-After` floor, 5xx/network plain backoff,
circuit breaker, retry rounds.

### 429 handling (safety net)

A burst is a bet that lrclib tolerates it. If lrclib answers 429 anyway:

- Burst mode is switched off for the rest of the run (`_burst_ok = False`).
- Spacing falls back to the existing adaptive interval (starts at `60 / REQUESTS_PER_MINUTE` = 0.5 s,
  doubles on 429, relaxes after 10 successes), exactly the current behaviour.

So the worst case equals today's behaviour plus one 429 (the existing code already handles it).

## Code changes (`update_lyrics.py` only)

1. `BASE_INTERVAL = 0.5` -> `REQUESTS_PER_MINUTE = 120`, `WINDOW = 60.0`,
   `BASE_INTERVAL = WINDOW / REQUESTS_PER_MINUTE` (still the steady-state/fallback gap).
2. `Pacer.__init__`: `self._starts = collections.deque()` (monotonic start times), `self._burst_ok = True`.
3. `Pacer.acquire`: when `_burst_ok` and the interval is still `BASE_INTERVAL`, drop starts older than
   `WINDOW`; if fewer than `REQUESTS_PER_MINUTE` remain, `start = max(now, _floor_until)` with no gap;
   otherwise `start = max(now, _starts[0] + WINDOW, _floor_until)`. Record `start`. When burst is off,
   keep the current `_next_start`/`_interval` logic unchanged.
4. `Pacer.failure`: on `rate_limited`, set `_burst_ok = False` (and seed `_next_start` from the last
   start so the fallback spacing begins at once).
5. Log line at start of fetch (`Fetching lyrics for N tracks ...`) unchanged; add one `logger.info`
   when the budget is exhausted ("120 requests used, pacing to 0.5 s") so a long wait is explained.
6. Update the comment above the constants (drop "inside the 200-500 ms between requests").

## Documentation (CLAUDE.md sync rule)

- `SPEC.md` lines 316 and 335 (Pacer description, "at least 0.5 s apart").
- `docs/adr/0007-lrclib-lyrics-submission-proof-of-work.md` section 4: pacing rule, and state that it
  now deliberately bursts up to 120 requests/min, deviating from lrclib's "200-500 ms between
  requests" recommendation; a 429 ends the burst.
- `docs/adr/0001-general-python-rules.md` section 6: mentions the single pacer; check wording stays true.
- `README.md`: only if it states the 0.5 s figure (grep found none).

## Verification

- Throwaway script in the scratchpad driving `Pacer.acquire/release` with a fake clock or short
  `WINDOW`: N <= budget -> no sleeps; N > budget -> the extra starts are spaced; after a simulated
  429 -> spacing returns to the interval.
- `uvx ruff format . && uvx ruff check .`
- Live check on a copy of a few FLACs under `/tmp` (never `/Volumes/FLAC`), `update_lyrics.py` on
  e.g. 10 tracks lacking lyrics: confirm wall time drops from ~5 s of waiting to round-trip time only.

## Decisions for you

1. **Budget size.** Recommend 120/min (current average, two thirds of the ~180 allowance). 150/min is
   possible but leaves little margin against the app-wide allowance and other clients on your IP.
2. **Deviation from lrclib's advice** (sequential, 200-500 ms apart): a burst ignores the gap for
   up to 120 requests. Requests stay sequential and the allowance is respected, but this is a
   conscious departure from the recommendation. Alternative: a 0.2 s minimum gap inside the burst
   (120 tracks in 24 s instead of ~15 s); costs little, keeps some spacing. Recommend this 0.2 s floor.
3. The earlier "drop `BASE_INTERVAL` to 0.35 s" idea is dropped: the window makes it unnecessary
   for small runs, and large runs stay at the safe 120/min.

Then: commit and `git push github main`.
