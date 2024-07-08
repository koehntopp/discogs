import os, sys
from shlex import quote
 
if len(sys.argv) != 2:
   from config import flacdir
else:
   flacdir = sys.argv[1]

os.system('/Applications/rsgain easy --skip-existing ' + quote(flacdir))

os.system('python3 /Users/koehntopp/src/discogs/calculate_fp.py ' + quote(flacdir))
os.system('python3 /Users/koehntopp/src/discogs/calculate_dr.py ' + quote(flacdir))
os.system('python3 /Users/koehntopp/src/discogs/fixtags.py ' + quote(flacdir))
os.system('python3 /Users/koehntopp/src/discogs/update_lyrics.py ' + quote(flacdir))
