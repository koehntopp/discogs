# Implementation plan: the web UI reads the album list from Tagwright

## Goal

`webui.py` and `mcp_albums.py` read `albums.csv`, which `album_list.py` builds by hand ("Refresh")
from the files on `flacroot`. Tagwright (192.168.1.97:8780) keeps the same facts current and serves
them as CSV: `GET /api/library/albums.csv?path_prefix=<flacroot>` (Tagwright ADR 0077, deployed).
Checked on the real library: 823 albums, every column identical to the current `albums.csv`.
`album_list.py` is not touched (it is what this replaces; it stays for CLI use).

## Facts checked

- The endpoint has the columns of `albums.csv`, in its order, incl. `Cover Art`, `_DIRECTORY_PATH`,
  `Directory`; `path_prefix` rewrites the folder paths to `flacroot` (`/Volumes/flac/`).
- First request after a Tagwright update can take about 30 s (summaries are re-read); later ones are
  fast.
- `webui.py` uses the CSV in four places: `_cache_load` (read, purge rows whose folder is gone and
  write the CSV back), `_cache_update` (write-through to `albums.csv` and `album_cache.json` after
  `/reprocess`), `_start_album_scan` (runs `album_list.py`; called by the Refresh button and after
  `bliss`), and the startup log line. `mcp_albums.py` reads the CSV file itself.
- `/reprocess` runs fixtags and bliss in the library; Tagwright's watcher sees that at its next pass
  (cooldown 60 s, check every 120 s), so Tagwright's list can lag a few minutes behind a reprocess.

## Design

Owner's answers: the web app runs in Dockge stack `discogs` on the same server (192.168.1.97, port 8765,
`flacroot` is `/flac/` inside the container), not on a Synology; it needs a **setting** for the source and
an **auto-refresh**, default 5 minutes.

1. **Settings** (the Settings dialog, stored in `config.py` like the other keys; read on every use, so
   a change needs no restart): `tagwright_url` (empty = no source, the table stays empty and the log says
   why; example `http://192.168.1.97:8780`) and `albums_refresh_minutes` (default 5, `0` = off).
   `config_demo.py` gets both. The MCP server reads the env var `TAGWRIGHT_URL`.
2. **`_cache_load`**: GET `<tagwright_url>/api/library/albums.csv?path_prefix=<flacroot>` (timeout 120 s),
   `pd.read_csv` from the text; rows whose folder does not exist on this host are dropped, in memory only.
   The result is cached in memory with its time; it is fetched again when it is older than the refresh
   interval (minus 10 s, so that every poll of the page fetches). On a network error it logs once and
   keeps the old cache.
3. **Auto-refresh of the page**: `render_table` puts `hx-get="/albums" hx-trigger="every <n>s"
   hx-include="[name='search']"` and the current `sort`/`order` (`hx-vals`) on `#albums-wrap`, so an open page
   re-reads the table without losing its search or sort. Interval 0: no trigger.
4. **`_cache_update` (after `/reprocess`)**: keeps the in-memory replacement of the rows, so the table
   shows the new values at once; no `albums.csv` or `album_cache.json` write. The `_cache_invalidate()`
   after it in `/reprocess` is removed, otherwise it would fetch Tagwright's older rows again; the
   next scheduled fetch (a few minutes, the lag of Tagwright's watcher) replaces them.
5. **Refresh button and after bliss** (`_start_album_scan`): no `album_list.py` subprocess. It
   invalidates the cache, fetches once (the log modal shows "fetched N albums from Tagwright" or the
   error) and sets `_refresh_done`. The `force` argument goes away.
6. **`mcp_albums.py`**: `_load()` fetches the URL with `urllib` (stdlib; no `path_prefix`).
7. **Docs (mandatory)**: new ADR `docs/adr/0011-album-list-from-tagwright.md`; `README.md`, `SPEC.md`,
   `INSTALL.md`, the comments in `docker-compose-synology.yml` and `config_demo.py`. `album_list.py` and
   its ADR 0004 are not changed.

## Verification (never on production data)

- Against a scratch Tagwright (synthetic albums, own port) and a scratch `flacroot`: the table shows the
  albums with the scratch paths; the Refresh button re-fetches; a change in the scratch Tagwright shows
  after the interval without reloading the page (interval 1 minute for the test); an unreachable URL gives
  a log line and an empty table (no traceback); `mcp_albums.py` `search_albums` returns rows; the
  Settings dialog saves both keys.
- `uv run ruff check` and `ruff format --check` on the changed files; `uv run check_docs.py`.
- Not verified: `/reprocess` end to end (it rewrites the library's tags), the image in Dockge.

## Out of this change

Rebuilding the `discogs:latest` image and redeploying the stack (`deploy-linux.sh`) happens only when you
ask; until then the old image keeps reading its `albums.csv`.
