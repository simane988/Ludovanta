# Ludovanta: instructions for AI agents

This file is managed by Ludovanta and overwritten on every platform update. Do not edit it.
Project-specific instructions belong in `AGENTS.md` / `CLAUDE.md` outside the `ludovanta:managed` block.

## Running Ludovanta commands

All commands go through one entry point, run from the project root (Python 3.9+, no packages needed):

```
python3 .ludovanta/ludovanta.py <command> [options]
```

On Windows use `python` (or `py -3`) if `python3` is not available. Every command accepts `--json`.

| Command | Purpose |
|---|---|
| `status` | Mode (LIVE/HEADLESS), Unity version, whether the Unity Editor executable is found |
| `compile` | Compile the project in batchmode, list compiler errors as `path:line:col CODE message` |
| `test [--platform EditMode\|PlayMode] [--filter X] [--category Y]` | Run tests, list failures |
| `validate-assets [--roots Assets ...]` | Missing/orphan `.meta` files and duplicate GUIDs (no Unity needed) |
| `plan [status\|check\|next\|add-task\|set\|fail ...]` | Project plan: progress, next tasks, task cards (skill `ludovanta-plan`) |
| `update [--ref vX.Y.Z] [--dry-run]` | Update the platform itself (skill `ludovanta-platform-update`) |

Exit codes (all commands):

| Code | Meaning | Your action |
|---|---|---|
| 0 | OK | continue |
| 1 | project problems (compile errors, failed tests, invalid assets) | fix them |
| 2 | environment failure (Unity not found, license, crash) | do not change game code because of it; report the printed reason |
| 3 | EDITOR_OPEN | switch to live mode |
| 4 | timeout | report to the user |

Full Unity logs are written to `Logs/ludovanta/`. Search them (grep for `error`, `Exception`) instead of
reading them whole: they are large.

## Two working modes

Before running anything that starts Unity, run `python3 .ludovanta/ludovanta.py status`:

- **LIVE**: Unity Editor has this project open. Unity cannot run a second instance on the same
  folder, so `compile` and `test` return `EDITOR_OPEN` (exit code 3). Work through the Unity MCP
  tools (names start with `Unity_`): read the console, inspect and change scenes/GameObjects.
  If no Unity MCP tools are available in your session, ask the user to check the Editor or to
  close it. Never kill the Unity process.
- **HEADLESS**: no Editor is open (typical for parallel agents in their own git worktree).
  Use the Ludovanta commands.

## Tasks: agree on the result, report against it, stop instead of looping

These rules apply to every task, whether it comes from the plan or from a chat message.

1. **Know the acceptance criteria before you start.** If the project has a `plan/` folder, work by
   task cards and read skill `ludovanta-plan`: a card's `- [ ]` lines are the criteria. For a request
   bigger than a small fix that has no card, state the 2-5 criteria you will check against in your
   first reply and then start. Ask first only if the request is genuinely ambiguous: the user prefers
   autonomy and a result to review over questions at every step.
2. **Report against the criteria.** Finish every task with this report, in the user's language,
   short, technical terms may stay in English:
   - **What changed**: what the user will notice, then the main files.
   - **How to check**: the scene to open and what to do in Play mode, or the screenshot, or the test.
   - **Not done or uncertain**: criteria you could not verify, shortcuts taken, known problems.
     Never leave this out to make the result look better; write "nothing" if there is nothing.
   - **Next**: one or two suggested next steps.
3. **Stop after 3 failed attempts.** If the result fails your own verification of the criteria, or
   the user rejects it, three times in a row, stop. Do not start a fourth rewrite. Tell the user what
   you tried, why it failed, your hypotheses, and ask one concrete question. With a plan, record each
   failed attempt with `plan fail` (it tells you when to stop).

## Feedback loop

1. After changing C# code, `.asmdef` files or packages: compile (skill `ludovanta-unity-compile`).
2. Before reporting a task as done: run the relevant tests (skill `ludovanta-unity-test`) and
   `validate-assets` (skill `ludovanta-unity-assets`).
3. Never report success while compilation, tests or asset validation fail. If something cannot
   be verified (for example the environment fails with exit code 2), say so explicitly.

Batchmode runs take from seconds to several minutes (the first run in a fresh worktree imports
every asset). Batch your edits and verify once per batch, not after every line. Never run two
Unity commands in parallel for the same folder.

## Rules

- Every file and folder under `Assets/` has a `.meta` file with a GUID. Read skill
  `ludovanta-unity-assets` before creating, moving, renaming or deleting assets.
- Do not hand-edit scenes, prefabs or other Unity YAML assets while the Editor is open.
- Never touch `Library/`, `Temp/`, `Logs/`, `UserSettings/`, `obj/`: they are generated.
- Platform-owned files (`.ludovanta/`, skills named `ludovanta-*`, `ludovanta:managed` blocks) are overwritten on
  update. Do not edit them; see skill `ludovanta-platform-update`.
