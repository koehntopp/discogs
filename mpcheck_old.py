
def checkMP3():
   print("Checking MP3 folders in " + mp3root)
   for (root,dirs,files) in os.walk(mp3root, topdown = True):
      for dirname in dirs:
         if not hasSubDirs(dirname):
            mp3dir = os.path.join(mp3root, dirname)
            flacdir = os.path.join(flacroot, dirname)
            mp3time = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(mp3dir)))
            flactime = "00000000"
            if os.path.exists(flacdir):
               flactime = time.strftime('%Y%m%d', time.localtime(os.path.getmtime(flacdir)))
            else:
               print ("   " + mp3time + "  -  " + root + "  -  " + dirname)
               print ("       -  FLAC directory does not exist - deleting MP3 folder.")
#               try:
#                  shutil.rmtree(mp3dir)
#               except OSError as err:
#                  print(err)
            if mp3time < flactime:
               print ("   " + flactime + "  -  FLAC - " + root + "  -  " + dirname)
               print ("   " + mp3time + "  -  MP3  - " + root + "  -  " + dirname)
               print ("       -  FLAC directory is newer - deleting MP3 folder.")
#               try:
#                  shutil.rmtree(mp3dir)
#               except OSError as err:
#                  print(err)
   print("\nDone.\n")