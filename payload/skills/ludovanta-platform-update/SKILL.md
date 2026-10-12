---
name: ludovanta-platform-update
description: Inspect, update or repair Ludovanta installed in this project (the .ludovanta/ folder, ludovanta-* skills and ludovanta:managed blocks). Use when the user asks to update, upgrade or pin the platform version, when a Ludovanta update fails, or when Ludovanta files have merge conflicts.
---

# Updating Ludovanta

- Installed version: `version` in `.ludovanta/lock.json`. Wanted version: `ref` in `ludovanta.json`
  (a git tag such as `v0.2.0` or a branch).
- `ludovanta.json` belongs to the project. Per-machine settings (for example `unityEditorPath`) go to
  `ludovanta.local.json`, which is gitignored.

## Commands

```
python3 .ludovanta/ludovanta.py update --dry-run          # show what would change
python3 .ludovanta/ludovanta.py update                    # update to the ref in ludovanta.json
python3 .ludovanta/ludovanta.py update --ref v0.2.0       # switch to another version (also updates ludovanta.json)
```

On Windows use `python` (or `py -3`) if `python3` is not available. Requires git.

After an update, show the user the summary and suggest a separate commit containing only the
Ludovanta changes, for example `chore(ludovanta): update to 0.2.0`.

## When the update stops with exit code 1

Ludovanta refuses to overwrite platform files that were changed locally and lists them. Platform
files must not be edited. Explain this to the user and suggest moving the customization to a
place the project owns:

- own skills: a skill folder without the `ludovanta-` prefix;
- own agent instructions: `AGENTS.md` / `CLAUDE.md` outside the `ludovanta:managed` block.

Only with the user's consent re-run with `--force`: the changed files are backed up to
`.ludovanta-backup/<timestamp>/` and replaced.

## Merge conflicts in Ludovanta files

Conflicts in `.ludovanta/**`, `ludovanta-*` skills, `ludovanta:managed` blocks or `.ludovanta/lock.json` should not be
resolved by hand: all of it is generated.

1. Resolve `ludovanta.json` if it conflicts (choose the `ref`, usually the newer one).
2. If `.ludovanta/ludovanta.py` or `.ludovanta/ludovanta_lib/update.py` contain conflict markers, first run
   `git checkout --theirs -- .ludovanta` (or `--ours`) to get a runnable copy.
3. Run `python3 .ludovanta/ludovanta.py update --force`: it regenerates every managed file and block for that ref.
4. `git add` the result and continue the merge.

Never edit `.ludovanta/lock.json` by hand.
