---
name: ludovanta-plan
description: Plan the game and work by task cards. Use when the user asks to plan, break a goal down into tasks, show progress or "how much is done", pick the next task, or work on a task by id (T-001); also when a task fails repeatedly or the user rejects a result. Covers the plan/ folder, task cards with acceptance criteria, task statuses, splitting work between agents (Claude, Codex), and the stop-after-3-failed-attempts rule.
---

# Project plan and task cards

The plan lives in the project (default folder `plan/`, set by `planDir` in `ludovanta.json`) and is
committed. It is the shared memory of what is being built: read it before planning or starting work.

```
plan/goal.md              what we are building, in and out of scope, "done when"
plan/milestones/M1.md     milestones in order
plan/tasks/T-001.md       one task card per file
```

## Commands

```
python3 .ludovanta/ludovanta.py plan                       # progress by milestone, review queue, next tasks
python3 .ludovanta/ludovanta.py plan next [--agent codex]  # tasks ready to start
python3 .ludovanta/ludovanta.py plan check                 # validate the plan after editing it
python3 .ludovanta/ludovanta.py plan init --title "..."    # create the folder
python3 .ludovanta/ludovanta.py plan add-milestone --title "..."
python3 .ludovanta/ludovanta.py plan add-task --milestone M1 --title "..." [--agent claude|codex|any] [--size S|M|L] [--depends T-001 ...]
python3 .ludovanta/ludovanta.py plan set T-001 --status in-progress|review|done|blocked|dropped|todo [--agent ...]
python3 .ludovanta/ludovanta.py plan fail T-001 "why the attempt failed"
```

On Windows use `python` (or `py -3`) if `python3` is not available. `plan`, `plan check` and
`plan next` accept `--json`. Create cards with `add-milestone` / `add-task` (they assign ids), then
edit the card text directly. Change statuses with `plan set` (it enforces the task contract).

## Task card

```markdown
---
id: T-007
title: Taxi meter counts the fare
milestone: M2
status: todo
agent: any
size: M
depends: [T-004]
attempts: 0
---

## Goal
One or two sentences: what the player gets.

## Acceptance criteria
- [ ] The fare starts at the base price when a passenger gets in
- [ ] The fare grows with distance; the HUD shows it with two decimals
- [ ] EditMode test FareCalculatorTests passes

## Do not touch
Car physics (T-004 is in review).

## Notes
```

- Write the card text in the user's language (headings too, if the user prefers). Only the header
  keys and the `- [ ]` checkbox syntax are fixed.
- Every checkbox in the body is an acceptance criterion. Criteria are observable: what the user sees
  in Play mode or on a screenshot, a test name, a number. Not "code is clean", not "works well".
  Two to five criteria per task.
- `size`: S (under an hour of agent work), M (one to two hours), L (half a day). Split anything
  bigger.
- `agent`: who should do it: `claude`, `codex`, `any`, or a person. Leave `any` unless the user
  has a rule for this project, or the task clearly needs one agent's strengths. The user tunes
  these rules over time from the attempts history.
- `status`: `todo` -> `in-progress` -> `review` (agent finished, waiting for the user) -> `done`
  (the user accepted). Also `blocked` and `dropped` (out of scope; excluded from progress).
- Progress is weighted by size: S=1, M=2, L=4. Tasks in review are shown separately from done.

## Planning: breaking a goal down

1. Read `plan/goal.md` and the existing milestones and tasks. If there is no plan, run `plan init`
   and fill `goal.md` with the user: goal, in scope, out of scope, done when.
2. Milestones are playable steps, each ending in something the user can try in Play mode (for
   example: "drive the car around one block", "one complete ride with a passenger").
3. Tasks are vertical: each one changes something visible or testable on its own. Prefer tasks that
   touch different files, so agents can work on them in parallel without merge conflicts.
4. Write the acceptance criteria for every task you create. A task without criteria cannot start.
5. Show the user the breakdown (milestones, task titles, sizes, agents) and ask for approval before
   committing it. Adjust the plan; do not argue for it.
6. Run `plan check` and fix every problem it reports.

Only one agent restructures the plan at a time (adds, splits or reorders tasks), in the main working
copy. Agents working on tasks in other worktrees change only their own task card.

## Working on a task

1. Pick: the task the user named, or the first one from `plan next --agent <you>`. Read the card,
   its dependencies and `goal.md`.
2. If the criteria are missing or ambiguous, propose criteria and ask the user before starting.
   Otherwise start without asking: the user prefers autonomy and a result to review.
3. `plan set T-xxx --status in-progress`.
4. Do the work. Verify each criterion yourself (compile, tests, Unity MCP, screenshots) and tick
   (`- [x]`) the ones you verified. Leave the ones only the user can judge unticked.
5. `plan set T-xxx --status review` and report with the format from `.ludovanta/AGENTS.platform.md`
   ("Task report"). Do not set `done` yourself: the user accepts the task.
6. If the user accepts, `plan set T-xxx --status done`. If the user rejects, record it:
   `plan fail T-xxx "user: <their reason>"`, then continue.

## Failed attempts: stop instead of looping

An attempt has failed when your own verification of the criteria fails after you thought the task
was done, or when the user rejects the result. Record every failed attempt:

```
python3 .ludovanta/ludovanta.py plan fail T-xxx "what failed and why"
```

- Before the next attempt, change the approach. Re-read the criteria and the log in the card; do not
  repeat what already failed.
- When the command prints `STOP` (exit code 1, after 3 failed attempts by default, `maxAttempts` in
  `ludovanta.json`), stop working on the task. Tell the user what you tried, why each attempt failed,
  your hypotheses, and ask ONE concrete question or for one decision. After the user answers you
  get another 3 attempts.
- Compile errors and failing tests while you are still working are not failed attempts: they are
  normal iteration.

## Showing progress

When the user asks how things are going, run `plan` and present it briefly in the user's language:
overall percent, each milestone's percent, what waits for the user's review (list these first: the
user is the bottleneck there), what is blocked or stopped, and what comes next.
