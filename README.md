# discogs

A collection of python scripts to manage my local music files

Goal: Make sure all my files
- have associated Discogs releases
- allow for their album names to be generated based on those tags

## Here's how I use this:
- For each album, add Discogs (https://www.discogs.com/) tags for the exact release with your favourite tagger (I use https://2manyrobots.com/yate/).
- (To satify my OCD, I also add MusicBrainz (https://musicbrainz.org/) tags for good measure) 
- Add decent cover art
- Run fixtags.py to normalize tags
- Run bliss.py to normalize file and folder names, and create MP3 copies for mobile/car use

## This looks terribly complicated, why would you do that?

If you have a music collection that has, for example, different version of the same song (original, acoustic, live, remaster), the 'automated' discovery in tools like Apple Music might not share your enthusiasm and map them all to the same metadata. I have tried *multiple* automated taggers, and they have consistently messed up my music.

So now, I will not allow any program to touch my tags. Assigning to a Discogs release makes sure I always know exactly which version of a song I'm listening to. The rest is really just OCD and consistency.

Tagging with Discogs and MusicBrainz releases may also allow me to recover from accidential access by other tools, as log as the release tags are still there.

## Details

### Prerequisites

In order to call the Discogs API you need to create a file called "config.py" and add a Discogs API key in there (as "api_key = xxxxx") - look into the sample config file for details.

### fixtags.py 

fixtags.py <folder> will walk through a folder hierarchy and rename files according to the tags found in the file. It will skip files that do not have a Discogs release assigned. 

In detail:
- find all FLAC files with Discogs tags
- find the master release
- get the original release date from the master
- add custom name fields if available ("SACD")
- rewrite album title to add release year, custom tags, bitrate to allow differentiation of multiple releases of the same album
- try to get lyrics (LRC synced lyrics, preferrably) for each title

### bliss.py

bliss.py (hat tip to https://www.blisshq.com/) takes the properly tagged files that you drop from staging to /flac und renames them and puts them into /flac/artist/album folders, then creates a synchronized mp3 copy in /mp3 (needs ffmpeg) 

In detail:
- move files below $flacroot as <album artist>/<album>/<disc#>_<title#>_<title> files
- check for tag errors and write album.csv file
- remove empty directories
- check for MP3 files with changed source FLAC files
- create missing MP3 files 

## Libraries and tools used

- Python Discogs client https://github.com/joalla/discogs_client
- Python tagger MusicTag https://github.com/KristoforMaynard/music-tag
- Python Dynamic Range calculation by https://github.com/janw/drmeter/
- Lyrics API by https://github.com/tranxuanthang/lrcget

## To Do

Make a proper requirements.txt file