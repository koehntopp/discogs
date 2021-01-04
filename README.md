# discogs

Playing with the Discogs Python API

Goal: Make sure all my files

- have associated Discogs releases
- have their album names reflect those in a consistent manner

There are three Python scripts to get there:

discogs_list.py <folder> will walk through folder hierarchy (assumption: one folder for all FLAC files of an album) and simply list files as "<album artist> - <album>" with whatever tags they currently have. I recommend to do this and save the result in a text file in case anything gets lost at a later stage (I had some albums marked as "Deluxe" that is not in the official album title).

discogs_tagger.py <folder> will walk through folder hierarchy and identify albums that do not have a Discogs release assigned, and ask you to start a tagger (can be defined in the script, in my case Yate https://2manyrobots.com/yate/ works quite well).

discogs_rename.py <folder> will walk through folder hierarchy and rename files according to the tags found in the file. It will skip files that do not have a Discogs release assigned, will not re-write tags if they are OK already. 

In order to call the Discogs API you need to create a file called "config.py" and add a Discogs API key in there (as "api_key = xxxxx")

There are a few special cases I have coded:
- Discogs has some HDTracks.com releases only as "File", but HDTracks is mentioned in Discogs remarks. I'm pulling that from there and put it into the album title
- The album title usually omits remarks about the release (like "Remastered" or "Deluxe Edition"). You can put them into the file while tagging as comments, I will pull anything between two pairs of '###' (i.e. ###Remastered###) and add that to the album title