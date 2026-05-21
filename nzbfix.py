# /// script
# dependencies = [
#   "rich",
# ]
# ///

import os, sys
from subprocess import call, DEVNULL
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

call(['uv', 'run', str(SCRIPTS_DIR / 'calculate_dr.py'), flacdir])

timelog('Starting replay gain calculation in', flacdir)
call(['rsgain', 'easy', '-p', 'rsgain', '-m', 'MAX', flacdir],
     stdout=DEVNULL, stderr=DEVNULL)

call(['uv', 'run', str(SCRIPTS_DIR / 'calculate_fp.py'), flacdir])
call(['uv', 'run', str(SCRIPTS_DIR / 'fixtags.py'), flacdir])
call(['uv', 'run', str(SCRIPTS_DIR / 'update_lyrics.py'), flacdir])
