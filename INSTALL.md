# Installation Guide — Docker

This guide walks through setting up the Discogs Music Library Manager in Docker, from a minimal working installation to full configuration.

## Prerequisites

- Docker (Docker Desktop on Mac/Windows, or Docker Engine on Linux)
- A FLAC music library with albums tagged with `DISCOGS_RELEASE_ID` (set via [Yate](https://2manyrobots.com/yate/) or similar)
- A [Discogs API token](https://www.discogs.com/settings/developers) (free account required)

---

## Part 1: Minimal Setup

### 1. Get the code

```bash
git clone https://codeberg.org/koehntopp/discogs.git
cd discogs
```

### 2. Create the config directory and config file

```bash
mkdir -p config
cp config_demo.py config/config.py
```

Open `config/config.py` and fill in the three required values:

```python
config_dir = '/config'  # leave as-is for Docker

discogs_api_key = 'YOUR_TOKEN'  # from https://www.discogs.com/settings/developers

flacroot = '/flac/'  # path inside the container — matches the volume mount below
```

Everything else can stay at its default for now.

### 3. Create a docker-compose.yml

The file is gitignored (it may contain credentials). Create it yourself:

```yaml
services:
  discogs:
    build: .
    container_name: discogs
    ports:
      - "8765:8000"
    volumes:
      - ./config:/config        # config.py, logs, albums.csv
      - /path/to/your/flac:/flac
    environment:
      - CONFIG_DIR=/config
      - PORT=8000
    restart: unless-stopped
```

Replace `/path/to/your/flac` with the actual path to your FLAC library on the host.

### 4. Build and start

```bash
docker compose up --build
```

The first build takes a few minutes — it compiles TagLib 2.x and rsgain from source. Subsequent starts are instant.

Open **http://localhost:8765** in your browser.

---

## What you get out of the box

### Web UI

The main view is a table of your albums, scanned from `flacroot`. Each row shows:

| Column | Description |
|--------|-------------|
| Album Artist | Artist name |
| Album | Title with year, format, and bitrate (e.g. `Kind of Blue [1959 CD 44kHz DR13]`) |
| DR | Dynamic Range score; coloured green → red; links to loudness-war.info search |
| Original Date | First ever release year |
| Release Date | This specific release year |
| Catalog | Catalogue number |
| Cover Art | Thumbnail link to albumartexchange.com |
| Version | Format variant (SACD, 5.1, Qobuz, etc.) |

### Toolbar buttons

- **Refresh** — scans `flacroot` and rebuilds the album table
- **Lyrics** — fetches lyrics for all albums in `nzbdir` (see Part 2)
- **Bliss** — organises files into `Artist/Album/track.flac` structure (see Part 2)
- **Sync** — makes ROCK pull the library from the NAS with rsync (see Part 3)
- **Log** — opens the live log modal; shows output from any running process
- **Settings** — edit all config values in the browser; saves to `config/config.py`

### Search and sort

Type in the search box to filter by artist or album name. Click any column header to sort. The table updates without a page reload.

---

## Part 2: Tag Enrichment and File Organisation

### What these features do

**Tag enrichment (`fixtags.py`)** — given a FLAC file with `DISCOGS_RELEASE_ID` set, queries the Discogs API and:
- Fills in `DATE` (this release), `ORIGINALRELEASEDATE` (first ever release), `ORIGINAL_TITLE`
- Rewrites the `ALBUM` tag to `Title [YEAR FORMAT BITRATE]`

**File organisation (`bliss.py`)** — moves files into a consistent folder structure:
```
flacroot/
  Album Artist/
    Album Title [2024 CD 44kHz DR10]/
      01_Track Title.flac
```

**Lyrics (`update_lyrics.py`)** — fetches synced (LRC) or plain lyrics from [lrclib.net](https://lrclib.net) and stores them in the `LYRICS` FLAC tag. Uses 32 parallel workers. Detects and clears malformed LRC; upgrades bare LRC to versions with metadata headers.

### Additional config for staging

These features work on a staging directory (`nzbdir`) where you drop freshly tagged files before they are enriched and moved into the library:

```python
nzbdir = '/nzb/'  # staging area for new albums

flacroot_local = '/Volumes/FLAC/'  # path to flacroot as seen from your Mac
# used for tagger deep-links in the UI
```

Add a volume mount for the staging directory in `docker-compose.yml`:

```yaml
volumes:
  - ./config:/config
  - /path/to/your/flac:/flac
  - /path/to/your/nzb:/nzb       # add this
```

### Typical workflow

1. Tag new albums in Yate (or similar): assign `DISCOGS_RELEASE_ID`, `ALBUMARTIST`, `ALBUM`, cover art
2. Move the folder into `nzbdir`
3. Click **Refresh** in the web UI (or run `uv run nzbfix.py` directly) — this runs DR calculation, ReplayGain, fingerprinting, tag enrichment, lyrics, and file organisation in sequence
4. Files land in `flacroot` under `Artist/Album/`

### MP3 mirror (optional)

If you want a parallel MP3 copy of your library (for mobile / car):

```python
mp3root = '/mp3/'
```

```yaml
volumes:
  - /path/to/your/mp3:/mp3       # add this
```

MP3 copies are created by running bliss.py with `--mp3` directly — this is not exposed in the web UI:

```bash
docker exec discogs uv run bliss.py --mp3
```

---

## Part 3: Library Sync

The **Sync** button runs a shell script you provide, so the sync itself is entirely yours to define.
The template `sync_demo.sh` makes ROCK pull the library from the NAS with rsync over SSH, so the
data goes NAS to ROCK directly and not through the Docker host. rsync sends only the changed
blocks of retagged files; `--delete` removes files on ROCK that are gone from the NAS and `@eaDir/`
is excluded. Design: ADR 0010.

### Setup

1. Copy `sync_demo.sh` to `config/sync.sh` (next to `config.py`) and edit the host names and paths.
2. Set `sync_script = 'sync.sh'` in `config.py` (or in Settings). A bare name is looked up in the
   config directory; an absolute path also works.
3. Make the host's SSH keys visible to the container: mount the host's SSH folder read-only at
   `/root/.ssh` (see the volume line in the compose files). It needs the private key that ROCK
   accepts and a `known_hosts` entry for ROCK (`ssh-keyscan -H <rock-ip> >> known_hosts`).
   The script then needs no key setting. The image contains the `ssh` client.
4. ROCK needs its own key on the NAS (rsync service enabled in DSM, SSH port 22). On ROCK:
   `ssh-keygen -t ed25519 -N ''`, append the public key to the NAS user's `~/.ssh/authorized_keys`
   and accept the host key once with `ssh <nas-user>@<nas> true`. On Synology the user's home
   directory and `~/.ssh` must not be group- or world-writable.
5. Test the script from the Docker host before using the button: `bash config/sync.sh`
   (add `n` to `-rlti` for a dry run).

Start the long-running command with `exec` (as the template does): Kill then ends the remote rsync.
The log modal shows every line the script prints; rsync progress lines are shown at most every 5 s.

### Config value

```python
sync_script = 'sync.sh'  # script in the config directory (or an absolute path)
```

---

## Part 4: Syslog Forwarding

To forward logs to a Synology log server (or any syslog daemon):

```python
syslog_host = '192.168.1.1'  # IP of your log server
syslog_port = 514  # UDP port (514 is standard)
```

No restart needed after adding these via the Settings UI — they are read at startup. If you add them manually to `config.py`, restart the container.

---

## Part 5: Toolbar Link Buttons

Add up to 5 custom buttons to the toolbar — useful for linking to related apps (your NAS UI, Prowlarr, etc.).

In Settings, fill in **Link button #1** through **#5** with full URLs. The button appears immediately; the favicon is fetched and cached automatically.

If the app requires authentication to serve its favicon, you can place the icon file manually:

```
config/link_favicon_1.ico   # for Link button #1
config/link_favicon_2.ico   # for Link button #2
# etc.
```

Any image format works (PNG, ICO, SVG, GIF, JPEG).

---

## Synology NAS

The Synology workflow differs because Container Manager doesn't support `docker compose build` from source.

### Build the image on your Mac

```bash
./build_synology.sh          # produces discogs-synology-amd64.tar (~400 MB)
```

For ARM-based Synology:
```bash
./build_synology.sh arm64
```

### Import on Synology

1. Copy the `.tar` file to your Synology (e.g. via File Station)
2. Container Manager → **Image** → **Add** → **Import from file** → select the tar
3. Container Manager → **Container** → **Create** → select the `discogs:latest` image

### Container settings

| Setting | Value |
|---------|-------|
| Port | `8765` (host) → `8000` (container) |
| Volume: config | `/volume1/docker/discogs/config` → `/config` |
| Volume: FLAC | `/volume1/FLAC` → `/flac` |
| Env: `CONFIG_DIR` | `/config` |
| Env: `PORT` | `8000` |
| Restart policy | Unless stopped |

Create `/volume1/docker/discogs/config/config.py` from `config_demo.py` before starting the container.

Open **http://synology-ip:8765**

---

## Logging

Logs are written to `config/discogs.log` (JSON format). The **Log** button in the UI shows live output from any running process.

To change verbosity:
```yaml
environment:
  - LOG_LEVEL=DEBUG
```

---

## Updating

```bash
git pull
docker compose up --build
```

The build reuses Docker layer cache — only changed layers rebuild. Python dependencies are pre-installed at build time, so startup remains instant.
