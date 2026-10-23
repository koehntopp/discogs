# Copy this file to /config/config.py and fill in your values.
# In Docker: all paths below are container-internal paths (from volume mounts).

config_dir = '/config'  # must match CONFIG_DIR env var

discogs_api_key = '<DISCOGS API KEY>'  # https://www.discogs.com/settings/developers

tagger_scheme = 'yate://load'  # URL scheme for your tagger app

# Container-internal path (Docker volume mount point)
flacroot = '/flac/'  # mapped from e.g. /volume1/FLAC on Synology
mp3root = '/mp3/'  # mapped from e.g. /volume1/MP3 on Synology

# Path as seen from the machine running the browser (for tagger links)
flacroot_local = '/volume1/FLAC/'

nzbdir = '/nzb/'  # mapped from e.g. /volume1/nzb/complete

# Library sync: ROCK pulls from the NAS with rsync over SSH (ADR 0010)
sync_host = 'user@rock'  # ssh target of ROCK, reachable from the container
sync_source = 'user@nas:/volume1/FLAC/'  # master, as seen from ROCK (keep the trailing slash)
sync_dest = '/mnt/flac/'  # library path on ROCK (keep the trailing slash)
# sync_ssh_key = '/config/id_ed25519'  # optional key for container -> ROCK

# Cover art
cover_max_size = 1500  # resize embedded cover art to this max dimension (px)
# fixtags: write LYRICS_LANGUAGE per track from MusicBrainz (needs MUSICBRAINZ_ALBUMID)
musicbrainz_languages = True

# rsgain ReplayGain settings
rsgain_loudness = -14
rsgain_clip_mode = 'a'
rsgain_max_peak = -1.0
rsgain_true_peak = True
rsgain_skip = True

# Logging
log_level = 'SUCCESS'  # 'INFO', 'SUCCESS', 'WARNING', or 'ERROR'
# syslog_host = '192.168.1.1'  # uncomment to enable Synology log server
# syslog_port = 514
log_file = 'discogs.log'
log_rotation = '10 MB'
log_retention = '30 days'
