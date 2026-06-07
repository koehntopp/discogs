# Copy this file to /config/config.py and fill in your values.
# In Docker: all paths below are container-internal paths (from volume mounts).

config_dir = '/config'          # must match CONFIG_DIR env var

discogs_api_key = '<DISCOGS API KEY>'   # https://www.discogs.com/settings/developers

tagger_scheme = 'yate://load'   # URL scheme for your tagger app

# Container-internal path (Docker volume mount point)
flacroot    = '/flac/'          # mapped from e.g. /volume1/FLAC on Synology
mp3root     = '/mp3/'           # mapped from e.g. /volume1/MP3 on Synology

# Path as seen from the machine running the browser (for tagger links)
flacroot_local = '/volume1/FLAC/'

nzbdir      = '/nzb/'           # mapped from e.g. /volume1/nzb/complete

# rclone sync to remote
flacroot_remote  = 'REMOTE:/path/'
rclone_flags     = 'sync'
rclone_transfers = 8
rclone_stats     = '5s'

# rsgain ReplayGain settings
rsgain_loudness    = -14
rsgain_clip_mode   = 'a'
rsgain_max_peak    = -1.0
rsgain_true_peak   = True
rsgain_opus_mode   = 'd'
rsgain_skip        = True

# Logging
log_file      = 'discogs.log'
log_rotation  = '10 MB'
log_retention = '30 days'
