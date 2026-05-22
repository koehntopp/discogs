# /// script
# dependencies = [
#   "rich",
# ]
# ///

import os, sys
from subprocess import call, Popen, DEVNULL
from pathlib import Path
from rich import print as rprint
from datetime import datetime

SCRIPTS_DIR = Path(__file__).parent


# logging function
def timelog(txt1: str, txt2: str) -> None:
   """Print a timestamped log line with rich color formatting (green label).

   Args:
       txt1: Label text displayed in green.
       txt2: Value text appended after the label.
   """
   log_msg = '[green]' + txt1 + '[/green]'
   log_msg = log_msg + ' ' * (60 - len(log_msg))
   rprint('[white]' + datetime.now().strftime('%H:%M:%S') + '[/white] ' + log_msg + txt2)

if len(sys.argv) != 2:
   from config import flacdir
else:
   flacdir = sys.argv[1]

call(['dot_clean', flacdir], stdout=DEVNULL, stderr=DEVNULL)

timelog('Starting parallel processing in', flacdir)
parallel = [
    ('calculate_dr',  Popen(['uv', 'run', str(SCRIPTS_DIR / 'calculate_dr.py'), flacdir])),
    ('rsgain',        Popen(['rsgain', 'easy', '-p', 'rsgain', '-m', 'MAX', flacdir], stdout=DEVNULL, stderr=DEVNULL)),
    ('calculate_fp',  Popen(['uv', 'run', str(SCRIPTS_DIR / 'calculate_fp.py'), flacdir])),
]
for name, p in parallel:
    if p.wait() != 0:
        timelog('Warning: non-zero exit from', name)

call(['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), flacdir])
call(['uv', 'run', str(SCRIPTS_DIR / 'update_lyrics.py'), flacdir])
