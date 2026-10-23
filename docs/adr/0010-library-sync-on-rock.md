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

### 1. ROCK pulls; the container only runs the user's script

`webui.py` `GET /sync` runs `bash <sync_script>`. The script is the user's own and holds the host
names and flags; the repository ships a template, `sync_demo.sh`, in which a local `ssh` to ROCK
runs `rsync` against the NAS over SSH (port 22). The data path is NAS to ROCK. The container needs
an `ssh` client and the host's SSH folder mounted read-only at `/root/.ssh` (key and
`known_hosts`); ROCK needs its own key on the NAS. Nothing about hosts, paths or keys lives in
`config.py` except the script name (`sync_script`, a bare name is resolved in the config
directory), so the code does not encode one installation.

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
`--info=stats2,progress2` for the summary and progress. The flags live in the user's script. rclone is gone from the Docker image.

### 4. Script contract and log handling

The script's stdout and stderr are merged and streamed to the log modal. The reader splits on `\r`
and `\n` (rsync redraws progress with `\r`, and `ssh -tt` turns `\n` into `\r\n`); rsync progress
lines are shown at most every 5 s; a non-zero exit is logged as a failure. The template uses
`ssh -tt` so the remote rsync is tied to the connection and writes line by line, and starts it
with `exec`: Kill sends SIGTERM to the script, which is then the ssh process, and the remote rsync
receives SIGHUP. `BatchMode=yes` makes a missing key or host key fail instead of prompting. If
`sync_script` is unset or the file is missing, an error is logged and nothing starts.

## Consequences

### Positive
* Data goes NAS to ROCK once; the Docker host does no copying.
* Retagged files transfer as deltas.
* No credentials for the NAS in the container; no host-specific settings in the code.

### Negative / Trade-offs
* ROCK must have `rsync`, SSH key access to the NAS, and a writable library path.
* The container sees the mounted SSH folder, so it can run commands on ROCK; mount a dedicated folder, not the whole home `~/.ssh`.
* rsync gives no live percentage per file in the log beyond the throttled progress line.
