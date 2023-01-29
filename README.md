# discogs

A collection of python scripts to manage my local music files

Goal: Make sure all my files

- have associated Discogs releases
- allow for their album names to be generated based on those tags

There are three Python scripts to get there:

fixtags.py <folder> will walk through folder hierarchy and rename files according to the tags found in the file. It will skip files that do not have a Discogs release assigned. 

In order to call the Discogs API you need to create a file called "config.py" and add a Discogs API key in there (as "api_key = xxxxx")


