import os, sys
from shlex import quote
from subprocess import call, DEVNULL
from rich import print as rprint
from datetime import datetime


# logging function
def timelog(txt1, txt2):
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

if len(sys.argv) != 2:
   from config import flacdir
else:
   flacdir = sys.argv[1]

call('dot_clean ' + quote(flacdir), shell=True, stdout=DEVNULL, stderr=DEVNULL)

call('python3 /Users/koehntopp/src/discogs/calculate_dr.py ' + quote(flacdir), shell=True)

timelog('Starting replay gain calculation in', flacdir)
call('/Applications/rsgain easy --skip-existing ' + quote(flacdir), shell=True, stdout=DEVNULL, stderr=DEVNULL)

call('python3 /Users/koehntopp/src/discogs/calculate_fp.py ' + quote(flacdir), shell=True)
call('python3 /Users/koehntopp/src/discogs/fixtags.py ' + quote(flacdir), shell=True)
call('python3 /Users/koehntopp/src/discogs/update_lyrics.py ' + quote(flacdir), shell=True)