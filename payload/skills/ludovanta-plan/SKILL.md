---
name: ludovanta-plan
description: Plan the game and work by task cards. Use when the user asks to plan, break a goal down into tasks, show progress or "how much is done", pick the next task, or work on a task by id (T-001); also when a task fails repeatedly or the user rejects a result. Covers the plan/ folder, task cards with acceptance criteria, task statuses, splitting work between agents (Claude, Codex), and the stop-after-3-failed-attempts rule. For a new game or a big feature, the design pass (ludovanta-game-design) comes first.
---

# Project plan and task cards

The plan lives in the project (default folder `plan/`, set by `planDir` in `ludovanta.json`) and is
committed. It is the shared memory of what is being built: read it before planning or starting work.

```
plan/goal.md              what we are building, in and out of scope, "done when"
plan/design.md            fantasy, main verb, session walk-through, game feel, art direction, fidelity
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
- [ ] Each fare step ticks with a coin sound and the HUD number pops; the passenger comments when the
      driver brakes hard (screenshot and sound list in the report)
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
- A task that adds gameplay or something the player sees has at least one **feel criterion**: the
  feedback from the game feel table in `design.md` (animation, particles, sound, camera, UI, world
  reaction) or the look required by the fidelity. "The spell works" is not enough; "the cast has a
  charge glow, a beam, an impact burst with a sound and a camera shake, the rubble flies apart" is.
- `size`: S (under an hour of agent work), M (one to two hours), L (half a day). Split anything
  bigger.
- `agent`: who should do it: `claude`, `codex`, `any`, or a person. Leave `any` unless the user
  has a rule for this project, or the task clearly needs one agent's strengths. The user tunes
  these rules over time from the attempts history.
- `status`: `todo` -> `in-progress` -> `review` (agent finished, waiting for the user) -> `done`
  (the user accepted). Also `blocked` and `dropped` (out of scope; excluded from progress).
- Progress is weighted by size: S=1, M=2, L=4. Tasks in review are shown separately from done.

## Planning: breaking a goal down

1. Read `plan/goal.md`, `plan/design.md` and the existing milestones and tasks. If there is no plan,
   run `plan init`. If `design.md` is missing or its `fidelity` is not chosen, do the design pass
   first (skill `ludovanta-game-design`): planning without a design produces working mechanics
   nobody wants to play.
2. **The first milestone is the first playable**: the main verb in the player's hands, with its
   feedback, in a small representative piece of the world at the chosen fidelity. Not "walk around a
   greybox": movement and camera are part of it, not the milestone. If the art strategy is risky
   (a shader, a character style), prove it on this small piece before multiplying content.
3. Every milestone ends in something the user can try in Play mode and that is better to play than
   before (for example: "drive one block and feel the car", "one complete ride with a passenger who
   talks"). Its "Done when" includes one line about how it should feel, not only what works.
4. Order: controls and the core loop with feedback first, then challenge and progression, then more
   content. Menus, saving and settings come after the game is fun. Polish is part of each task, not
   a milestone at the end.
5. Scope: small in breadth, finished in feel. Out of scope go extra areas, mechanics and content, never
   the feedback, art or sound the fidelity requires. "Stubs only" is allowed only when the user chose
   it.
6. Tests protect rules that can silently break: quest and progression logic, economy, damage, saves,
   the route from start to end. Do not spend tasks on testing plumbing. Tests do not replace looking
   at the game: visual tasks are checked on screenshots.
7. Tasks are vertical: each one changes something visible or testable on its own. Prefer tasks that
   touch different files, so agents can work on them in parallel without merge conflicts.
8. Write the acceptance criteria for every task you create. A task without criteria cannot start.
9. Run the critic, checkpoint `plan` (skill `ludovanta-design-review`), and fix what it finds.
10. Show the user the design in short (fantasy, main verb, the first 2 minutes, fidelity) and the
    breakdown (milestones, task titles, sizes, agents), and ask for approval before committing it.
    Adjust the plan; do not argue for it.
11. Run `plan check` and fix every problem it reports.

Only one agent restructures the plan at a time (adds, splits or reorders tasks), in the main working
copy. Agents working on tasks in other worktrees change only their own task card.

## Working on a task

1. Pick: the task the user named, or the first one from `plan next --agent <you>`. Read the card,
   its dependencies, `goal.md` and `design.md` (the game feel and art direction the task must meet).
2. If the criteria are missing or ambiguous, propose criteria and ask the user before starting.
   Otherwise start without asking: the user prefers autonomy and a result to review.
3. `plan set T-xxx --status in-progress`.
4. Do the work. Verify each criterion yourself (compile, tests, Unity MCP, screenshots) and tick
   (`- [x]`) the ones you verified. Leave the ones only the user can judge unticked. For anything
   the player sees, capture the gameplay camera and look at it before calling it done.
5. When the task completes a milestone with new gameplay, run the critic first (skill
   `ludovanta-design-review`, checkpoint `first-playable` for the first milestone, `milestone` later)
   and fix its BLOCKER and MAJOR findings.
6. `plan set T-xxx --status review` and report with the format from `.ludovanta/AGENTS.platform.md`
   ("Task report"). Do not set `done` yourself: the user accepts the task. You may continue with the
   next tasks of the milestone while earlier ones wait in review (dependencies in review count as
   met); ask for the user's playtest at the end of the milestone rather than after every task.
7. If the user accepts, `plan set T-xxx --status done`. If the user rejects, record it:
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
