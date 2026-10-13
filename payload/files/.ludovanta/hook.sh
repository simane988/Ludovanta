#!/bin/sh
# Runs a Ludovanta Claude Code hook (see ludovanta_lib/hooks.py) with the first Python 3.9+ found.
# Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
# A hook must never break the session, so this script always exits 0.
cd "$(dirname "$0")/.." || exit 0
for py in python3 python "py -3"; do
  if $py -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    $py .ludovanta/ludovanta.py hook "$@"
    exit 0
  fi
done
exit 0
