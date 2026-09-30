#!/bin/sh
# Refuse edits while the tree is dirty.
if [ -n "$(git status --porcelain)" ]; then
  echo "commit first" >&2
  exit 2
fi
exit 0
