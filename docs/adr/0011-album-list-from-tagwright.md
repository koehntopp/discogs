# ADR 0011: The web UI reads the album list from Tagwright

- **Status**: Accepted
- **Date**: 2026-11-13
- **Authors**: Discogs Project Maintainers

## Context

The web UI showed `albums.csv`, which `album_list.py` built by reading the first FLAC of every album on
`flacroot` (the Refresh button, a few minutes on the NAS share) and which `/reprocess` patched in place.
Tagwright (the owner's other program, running on the same Docker host) already keeps the same facts
current and serves them: `GET /api/library/albums.csv?path_prefix=<flacroot>` returns the same columns,
with the folders as seen from this container (Tagwright ADR 0077). Checked on the real library: 823 albums,
every column identical to the CSV.

## Decision

- The album table, and `mcp_albums.py`, take the list from Tagwright, not from a file. Setting
  `tagwright_url` (Settings dialog, `config.py`; the MCP server reads the env var `TAGWRIGHT_URL`), for
  example `http://192.168.1.97:8780`. Without it the table is empty and the log says why. There is no
  fallback to `albums.csv`.
- The list is cached in memory and fetched again when it is older than the setting
  `albums_refresh_minutes` (default 5; 0 turns the refresh off). An open page re-reads the table by itself
  at the same interval (HTMX `every`), keeping its search and sort.
- The Refresh button (and the rescan after bliss) fetches the list again; it no longer runs `album_list.py`.
- `/reprocess` still reads the reprocessed albums from disk and replaces their rows in the in-memory list so
  that the table is right at once; nothing is written to `albums.csv` or `album_cache.json`. Tagwright's own
  list follows after its watcher has seen the change (a few minutes), and replaces the in-memory rows at the
  next fetch.
- A failed fetch is logged and the old list stays; the next try is at the next interval.
- `album_list.py` itself is unchanged: it is still the way to build `albums.csv` for the scripts that read
  that file (`find_audiophile_upgrades.py`, `check_*`), and it writes `albums_dr.png`.

## Consequences

- The web UI needs Tagwright to be reachable and its library index to be current; the first request after a
  Tagwright update can take about 30 seconds while its summaries are read again.
- A reprocessed album can briefly show its old values after the next fetch, until Tagwright has caught up.
- `albums.csv` in the config directory is no longer kept current by the web UI.
