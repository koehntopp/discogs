#!/usr/bin/env bash
# Library sync, run by the web UI's Sync button (copy to <config dir>/sync.sh and edit; ADR 0010).
# ROCK pulls the library from the NAS, so the data does not pass through the Docker host.
# Uses the SSH keys and known_hosts the container sees in /root/.ssh (mount the host's SSH folder).
# `exec` makes the ssh process the script itself, so the Kill button ends the remote rsync too.
exec ssh -tt -o BatchMode=yes user@rock \
	"rsync -rlti --delete --inplace --exclude '@eaDir/' --info=stats2,progress2 -e ssh user@nas:/volume1/flac/ /mnt/flac/"
