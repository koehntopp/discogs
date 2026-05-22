#!/usr/bin/env python3
# /// script
# dependencies = [
#     "python-slugify",
# ]
# ///

"""List all directories in /Volumes/flac with names filtered through python-slugify."""

import os
from pathlib import Path
from slugify import slugify


def main():
	"""Walk through /Volumes/flac and list directory names with slugified versions."""
	flac_dir = Path('/Volumes/flac')

	if not flac_dir.exists():
		print(f'Error: {flac_dir} does not exist')
		return

	dirs = []
	for item in flac_dir.iterdir():
		if item.is_dir():
			dirs.append(item.name)

	dirs.sort()

	print(f'Found {len(dirs)} directories:\n')
	for dir_name in dirs:
		slugified = slugify(dir_name, lowercase=False, separator='_')
		print(f'{dir_name:60} → {slugified}')


if __name__ == '__main__':
	main()
