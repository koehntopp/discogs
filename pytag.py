import taglib 
song = taglib.File("/Volumes/Frank/00NZB/complete/paradise/07..She.Cares.flac")

def flactag(song, tag):
   try:
      tmp = song.tags[tag][0]
   except: 
      tmp = ""
   return(tmp)


#print(song.tags)
#print(song.length)
#{'ARTIST': ['piman', 'jzig'], 'ALBUM': ['Quod Libet Test Data'], 'TITLE': ['Silence'], 'GENRE': ['Silence'], 'TRACKNUMBER': ['02/10'], 'DATE': ['2004']}

#song.tags["ALBUM"] = ["White Album"] # always use lists, even for single values
#del song.tags["DATE"]
#song.tags["GENRE"] = ["Vocal", "Classical"]
#song.tags["PERFORMER:HARPSICHORD"] = ["Ton Koopman"]

#song.tags["ORIGINALRELEASEDATE"] = ["1981"]
#song.save()

print(song.bitrate)
print(int(song.sampleRate/1000))
print(song.channels)

print(flactag(song, "ALBUM DYNAMIC RANGE"))
print(flactag(song, "DYNAMIC RANGE"))
print(flactag(song, "ALBUM"))
print(flactag(song, "ALBUMARTIST"))
print(flactag(song, "DISCOGS_RELEASE_ID"))
print(flactag(song, "ORIGINAL FILENAME"))
print(flactag(song, "TITLE"))
print(flactag(song, "SUBTITLE"))
print(flactag(song, "YEAR"))
#print(flactag(song, "LYRICS"))
print(flactag(song, "DATE"))
print(flactag(song, "RELEASEDATE"))
print(flactag(song, "ORIGINALRELEASEDATE"))
print(flactag(song, "VERSION"))
print(flactag(song, "ORIGINAL_TITLE"))
print(flactag(song, "ORIGINALRELEASEDATE"))
print(flactag(song, "ORIGINALRELEASEDATE"))
