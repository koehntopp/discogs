# import system libraries
import subprocess, json, time, sys, os

# import music libraries
from mutagen.flac import FLAC, StreamInfo
# music_tag was the only library I found that allows me to delete the YEAR tag to make sure I only have one in there
import music_tag

# define the application you want to run to tag your files with Discogs metadata
tagger = "/Applications/Yate.app/Contents/MacOS/Yate"

def query_yes_no(question, default="yes"):
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

def main():
    mode = 0
    if len(sys.argv) != 2:
        print("path to FLAC files missing")
        exit(1)
    else:
        flacdir = sys.argv[1]

    current_album = ""
    current_artist = ""

    # walk through directory given as ARGV and all subdirs
    currentDirectory = os.getcwd()
    for (subdir,dirs,files) in os.walk(flacdir):
        for filename in files:
            filepath = subdir + os.sep + filename
            if filepath.endswith(".flac"):
                tag = music_tag.load_file(filepath)
                # Do we have a new album to process?
                if (str(tag['albumartist']) != current_artist) or (str(tag['album']) != current_album):
                    current_album = str(tag['album'])
                    current_artist = str(tag['albumartist'])
                    # get FLAC metadata
                    audio = FLAC(filepath)
                    # Look in the comments for either ##nodiscogs## (leave me alone) or ###<title>### (special title to assign)
                    discogs_comments_raw = str(audio.vc)
                    comment_pos = discogs_comments_raw.find('COMMENT')
                    if comment_pos:
                        discogs_comments_raw = discogs_comments_raw[comment_pos:10000]
                        comment_pos = discogs_comments_raw.find('\')')
                        discogs_comments_raw = discogs_comments_raw[11:comment_pos]
                        # no Discogs release available? Skip album.
                        if "##nodiscogs##" in discogs_comments_raw:
                            message = "[Skipped, no Discogs release] - "
                            print (message + current_artist + " - " + current_album)
                            break

                    # does it have a Discogs release assigned we can use for tagging?
                    if not ("DISCOGS_RELEASE_ID" in audio):
                        # No Discogs release assigned: ask to run the tagge 
                        if query_yes_no(current_artist + " - "+ current_album + ": No Discogs release assigned. Start Tagger?"):
                            directory = os.path.join(currentDirectory, subdir)
                            return_code = subprocess.call(tagger + " \"" + directory + "\"", shell=True) 


if __name__ == "__main__":
    main()

