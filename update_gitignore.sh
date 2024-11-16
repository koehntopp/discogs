#!/bin/sh
git ls-files -ci --exclude-standard -z | xargs -0 git rm --cached
git commit -am "Removed unwanted files marked in .gitignore"