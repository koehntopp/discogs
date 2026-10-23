# ADR 0010: Library Sync Runs on ROCK and Pulls from the NAS (rsync over SSH)

- **Status**: Accepted
- **Date**: 2026-10-23
- **Authors**: Discogs Project Maintainers

## Context

The Sync button used to run rclone inside the Docker container: NAS (SMB remote) to Docker host to
ROCK (SFTP remote), so every byte crossed the Docker host twice. The NAS (a Synology) is the
master library; ROCK holds the copy Roon plays from. Both are Linux hosts on one LAN, and the
Docker host sits between them for no reason other than where rclone ran.

## Decision

### 1. ROCK pulls; the container only sends a command

`webui.py` `GET /sync` starts a local `ssh` to ROCK, and ROCK runs `rsync` against the NAS over
SSH (port 22). The data path is NAS to ROCK. The container needs an `ssh` client and a key for
ROCK; ROCK needs its own key on the NAS.

### 2. No mounted file system

Over an SMB or NFS mount both sides look local and rsync falls back to whole-file copies. The
tag-writing scripts rewrite tags in thousands of FLACs, and rsync's delta transfer (remote source,
`--inplace`) sends only the changed blocks. A mount would also add a kernel client on ROCK, a
mount unit and stale-mount failure modes. If a mount were ever needed, NFS is preferred over SMB
for Linux to Linux (mtimes, permissions, no stored password).

### 3. rsync, not rclone

rclone re-copies a whole file whenever size or mtime differs and has no delta transfer. The flags
map onto the old call: `-rlt` (no owner/group/permission flags, they fail on ROCK), `--delete`,
`--inplace`, `--exclude '@eaDir/'` (Synology metadata), `-i` for one line per change,
`--info=stats2,progress2` for the summary and progress. The flags are fixed in `webui.py`, not a
config value. rclone is gone from the Docker image.

### 4. Log handling

`ssh -tt` is used so the remote rsync is tied to the connection (Kill terminates the local ssh and
the remote rsync receives SIGHUP) and so rsync writes line by line. rsync redraws progress with
`\r` and the pty turns `\n` into `\r\n`, so `_sync_lines` splits on both; itemized changes are
logged individually, progress lines at most every 5 s, stderr is merged into stdout. Configuration
(`sync_host`, `sync_source`, `sync_dest`, optional `sync_ssh_key`) is in `config.py`; if a required
key is missing, an error is logged and nothing starts. Host keys come from the mounted
`known_hosts`; `BatchMode=yes` makes a missing key or host key fail instead of prompting.

## Consequences

### Positive
* Data goes NAS to ROCK once; the Docker host does no copying.
* Retagged files transfer as deltas.
* No credentials for the NAS in the container.

### Negative / Trade-offs
* ROCK must have `rsync`, SSH key access to the NAS, and a writable library path.
* The container holds an SSH key that can run commands on ROCK.
* rsync gives no live percentage per file in the log beyond the throttled progress line.
