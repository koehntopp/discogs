#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "wordcloud",
#   "matplotlib",
#   "numpy",
#   "pillow",
#   "pytaglib",
# ]
# ///

# import system libraries
import os
from pathlib import Path, PurePosixPath

import matplotlib.pyplot as plt
import numpy as np
import taglib
from PIL import Image
from wordcloud import STOPWORDS, ImageColorGenerator, WordCloud

lyricscloud = ''


# walk flacdir searching for directories holding albums with flac files
def walkdirs(fixdir: str) -> None:
	"""Accumulate all LYRICS tag content from FLAC files under fixdir into lyricscloud.

	Appends the LYRICS tag of every FLAC file found (recursively) to the global
	lyricscloud string.  Files without a LYRICS tag are silently skipped.

	Args:
	    fixdir: Root directory to search for FLAC files.
	"""
	global lyricscloud
	for p in Path(fixdir).rglob('*.flac'):
		fullfilename = str(PurePosixPath(p))
		tags = taglib.File(fullfilename)
		try:
			lyrics = tags.tags['LYRICS'][0].strip()
			lyricscloud += lyrics
			print(fullfilename)
		except KeyError:
			pass


def main() -> None:
	"""Generate a word-cloud image from lyrics embedded in a FLAC library.

	Collects all LYRICS tags from the hardcoded Taylor Swift directory, then renders
	two output images using a mask PNG:
	    swiftie_colour.png  – three-panel matplotlib figure (plain, recoloured, mask)
	    swiftie_cloud.png   – standalone word-cloud PNG

	Paths are currently hardcoded; edit flacdir and the mask/colour PNG paths to adapt.
	"""
	# flacdir = "/Volumes/Frank/00NZB/complete"
	flacdir = '/Volumes/FLAC/Taylor_Swift'
	flac_directories = []
	for root, dirs, files in os.walk(flacdir):
		for file in files:
			if file.endswith('.flac'):
				flac_directories.append(root)
				break

	for directory in flac_directories:
		walkdirs(directory)

	mask = np.array(Image.open('swiftie_mask.png'))

	stopwords = set(STOPWORDS)
	stopwords.add('said')
	stopwords.add('ah ah')
	stopwords.add('ah ha')
	stopwords.add("ain't")
	stopwords.add('will')
	stopwords.add('gonna')
	stopwords.add('eh eh')
	stopwords.add('might')
	stopwords.add('la la')
	stopwords.add('til')
	stopwords.add('let')
	stopwords.add('ah')
	stopwords.add('ooh ooh')
	stopwords.add('woah oh')
	stopwords.add('eh')

	wc = WordCloud(
		background_color='white',
		max_words=2000,
		mask=mask,
		stopwords=stopwords,
		contour_width=3,
		contour_color='steelblue',
	)

	# generate word cloud
	wc.generate(lyricscloud)

	# create coloring from image
	alice_coloring = np.array(Image.open('RG_6K.png'))
	image_colors = ImageColorGenerator(alice_coloring)

	# show
	_, axes = plt.subplots(1, 3)
	axes[0].imshow(wc, interpolation='bilinear')
	# recolor wordcloud and show
	# we could also give color_func=image_colors directly in the constructor
	axes[1].imshow(wc.recolor(color_func=image_colors), interpolation='bilinear')
	axes[2].imshow(alice_coloring, cmap=plt.cm.gray, interpolation='bilinear')
	for ax in axes:
		ax.set_axis_off()
	# plt.show()

	# store to file
	plt.savefig('swiftie_colour.png', dpi=300)
	wc.to_file('swiftie_cloud.png')


if __name__ == '__main__':
	main()
