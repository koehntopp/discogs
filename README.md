# discogs

A collection of python scripts to manage my local music files

Goal: Make sure all my files

- have associated Discogs releases
- allow for their album names to be generated based on those tags

There are three Python scripts to get there:

fixtags.py <folder> will walk through folder hierarchy and rename files according to the tags found in the file. It will skip files that do not have a Discogs release assigned. 

drmeter.py is a slightly adapted version of https://github.com/janw/drmeter/blob/master/drmeter.py 

bliss.py (hat tip to https://www.blisshq.com/) takes the properly tagged files that you drop from staging to /flac und renames them and puts them into /flac/artist/album folders, then creates a synchronized mp3 copy in /mp3 (needs ffmpeg) 

In order to call the Discogs API you need to create a file called "config.py" and add a Discogs API key in there (as "api_key = xxxxx") - look into the sample config file for details.


