---
name: ludovanta-plan
description: Plan the game and work by task cards. Use when the user asks to plan, break a goal down into tasks, show progress or "how much is done", pick the next task, continue the plan, or work on a task by id (T-001); also when a task fails repeatedly, the user rejects a result, a milestone is finished, the session context is large, or the plan is complete. Covers the plan/ folder, task cards with acceptance criteria, task statuses, running the plan as an orchestrator with one executor (subagent or Codex) per task, handoff and fresh sessions, closing a finished plan, the stop-after-3-failed-attempts rule, and splitting tasks between Claude and Codex with per-agent statistics (plan stats). Also use when the user asks which agent does what better. For a new game or a big feature, the design pass (ludovanta-game-design) comes first.
---

# Project plan and task cards

The plan lives in the project (default folder `plan/`, set by `planDir` in `ludovanta.json`) and is
committed. It is the shared memory of what is being built: read it before planning or starting work.

```
plan/goal.md              what we are building, in and out of scope, "done when"
plan/design.md            fantasy, main verb, session walk-through, game feel, art direction, fidelity
plan/milestones/M1.md     milestones in order
plan/tasks/T-001.md       one task card per file
plan/handoff.md           written before a fresh session: where we are, what is next
plan/archive/01-<name>/   closed plans (goal, milestones, tasks, SUMMARY.md); not read by 'plan'
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
python3 .ludovanta/ludovanta.py plan brief                 # state + handoff, what a fresh session needs
python3 .ludovanta/ludovanta.py plan brief T-001           # everything an executor needs for one task
python3 .ludovanta/ludovanta.py plan stats                 # per agent: accepted tasks, first-try rate, failed attempts
python3 .ludovanta/ludovanta.py plan close [--carry]       # archive a finished plan, numbering continues
```

On Windows use `python` (or `py -3`) if `python3` is not available. `plan`, `plan check`,
`plan next` and `plan stats` accept `--json`. Create cards with `add-milestone` / `add-task` (they assign ids), then
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
- [ ] At the end of the ride the fare is added to the day's earnings on the HUD

## Do not touch
Car physics (T-004 is in review).

## Notes

## Handoff
Written by the executor when the task is finished: what exists now (files, scene objects,
public API), decisions and gotchas the dependent tasks need. 'plan brief' passes it on.
```

- Write the card text in the user's language (headings too, if the user prefers). Only the header
  keys, the `- [ ]` checkbox syntax and the `## Handoff` heading are fixed.
- Every checkbox in the body is an acceptance criterion. Criteria are what the user can observe: in
  Play mode, on a screenshot, a number on the screen. Not "code is clean", not "works well", and not
  tests: tests are the executor's own check, the user never reviews them. Two to five criteria per task.
- A task that adds gameplay or something the player sees has at least one **feel criterion**: the
  feedback from the game feel table in `design.md` (animation, particles, sound, camera, UI, world
  reaction) or the look required by the fidelity. "The spell works" is not enough; "the cast has a
  charge glow, a beam, an impact burst with a sound and a camera shake, the rubble flies apart" is.
- `size`: S (under an hour of agent work), M (one to two hours), L (half a day). Split anything
  bigger.
- `agent`: who should do it: `claude`, `codex`, `any`, or a person. When work starts, the
  executor replaces `any` with itself (`plan set T-xxx --agent claude`), so the card records who
  did it; `plan stats` compares the agents by it. See "Splitting tasks between agents".
- `status`: `todo` -> `in-progress` -> `review` (agent finished, waiting for the user) -> `done`
  (the user accepted). Also `blocked` and `dropped` (out of scope; excluded from progress).
- Progress is weighted by size: S=1, M=2, L=4. Tasks in review are shown separately from done.

## Splitting tasks between agents

The project's rules for who does what are in `AGENTS.md`, outside the Ludovanta block (a heading such
as `## Preferences`). Follow them when you set `agent` on new cards. Without project rules, start from
these defaults; they are a hypothesis, not a law:

- `codex`: small (S), self-contained code with clear criteria that needs no Unity Editor or scene
  work: a calculator or data class with its EditMode tests, a parser, a config, an editor utility
  (skill `ludovanta-codex`).
- `claude`: scene and prefab wiring, anything that needs Unity MCP, game feel and visuals that must
  be judged on screenshots, tasks whose criteria still need refining.
- `any`: either fits; leave it when unsure.

The rules are revised from data, not impressions. Every finished card records its executor and its
failed attempts. When the user asks how the agents compare, at a plan's retrospective, or after two or
three weeks of work, run `plan stats`: per agent, how many tasks were accepted, how many on the first
try, failed attempts per task, how many hit the stop, by size. Show it in a few lines, propose one or two
rule changes ("Codex fails M tasks: give it only S"), and after the user agrees write them into the
preferences in `AGENTS.md`.

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
6. Tests are not planned: no test tasks, no test criteria. The executor of a task covers the rules
   that can silently break (quest and progression logic, economy, damage, saves, the route from start
   to end) with tests as part of the task, and keeps the suite healthy on its own (skill
   `ludovanta-unity-test`). Tests do not replace looking at the game: visual tasks are checked on
   screenshots.
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

## Running the plan: an orchestrator and one executor per task

A plan runs for hours. If one session does every task itself, its context grows with every file it
writes and reads, and each step re-sends all of it: a day of work reaches hundreds of thousands of
tokens per step. So the session that talks to the user is the **orchestrator** and does not build
the game itself. Each task goes to an **executor** with a fresh context, and only its short report
comes back.

Orchestrator, for each task (`plan next`, or the one the user named):

1. Pick the executor by the card's `agent`: `codex` -> `ludovanta.py codex run T-xxx` (skill
   `ludovanta-codex`); `claude` or `any` -> a subagent (Claude Code: the Agent tool, general-purpose).
   Without subagents, do the task yourself (see "Working on a task") and rely on the handoff below
   to keep the context small.
2. Subagent prompt, nothing more: "You are the executor of Ludovanta task T-xxx in this Unity
   project. Run `python3 .ludovanta/ludovanta.py plan brief T-xxx` (on Windows `python` or `py -3`)
   and do the task by its rules." plus only what the card cannot know (the user's latest words about
   this task). The brief carries the design, the card, the dependencies' handoffs and the rules.
3. One executor at a time while the Unity Editor is open (LIVE): they share the Editor and its
   compilation. Parallel executors only in their own git worktrees (HEADLESS).
4. Read the report. Check the claims that matter cheaply: the card's ticked criteria, the compile
   and test status, a screenshot for anything visible. An executor's report is not proof. A task that
   went to review `--unverified` (see the card's log) is not verified: run the full tests yourself
   (`test`, or Unity MCP in LIVE mode) before reporting to the user. If it lists
   "Tests changed", look at those diffs: an expectation bent to fit the code is a failed attempt.
5. If the executor came back with a question, ask the user, then start a new executor with the
   answer. If it failed, `plan fail` and start a new one with a different approach.
6. At the end of a milestone: the critic (skill `ludovanta-design-review`), then one report to the
   user and a playtest request (see "Working on a task", steps 5-7).
7. Test upkeep is yours, not the user's, and not in the plan: when tests got in an executor's way
   (flaky, quarantined, rewritten often) and at the end of a milestone, run `test-audit` and give the
   cleanup to an executor without a task card (skill `ludovanta-unity-test`, "Audit"). Do not report it
   to the user unless it changed how the game behaves.

User feedback goes into the plan, not only into the conversation: a new criterion on a card, a fix
task, or a line in `design.md` (art and feel preferences). Then the next executor sees it.

## Context and handoff

The plan files are the memory, so a fresh session loses nothing that was written down. In Claude
Code, Ludovanta hooks print `plan brief` (state plus `plan/handoff.md`) into every new session,
after `/clear` and after compaction. After each reply, a hook checks the context size: when a
milestone was just finished and the context is over `handoff.milestoneTokens` (default 100000 in
`ludovanta.json`), or any task was finished over `handoff.taskTokens` (default 300000), it asks for
a handoff.

Handoff (also do it unasked at the end of a milestone in a long session, and in agents without hooks):

1. Durable decisions go where they belong: `design.md` (the user's art and feel preferences),
   task cards (new criteria, `## Handoff`).
2. Overwrite `plan/handoff.md`, short, in the user's language: where we are; what the user said
   that is not recorded elsewhere; what is next (task ids) and how the user likes to work;
   open questions. Not a history of the session.
3. Finish the report with one line asking the user to type `/clear` and then "continue" (for
   example «Набери /clear, затем «продолжай»»). Do not start the next task in the same session.
   Hooks cannot clear the context themselves; the user's `/clear` is the one manual step. In an
   agent without hooks, the new session starts with `plan brief`.

## Working on a task

1. Pick: the task the user named, or the first one from `plan next --agent <you>`. Read
   `plan brief T-xxx`: the card, its dependencies' handoffs, `goal.md` and `design.md` (the game
   feel and art direction the task must meet).
2. If the criteria are missing or ambiguous, propose criteria and ask the user before starting.
   Otherwise start without asking: the user prefers autonomy and a result to review.
3. `plan set T-xxx --status in-progress --agent claude` (or whoever you are).
4. Do the work. Verify each criterion yourself (compile, tests, Unity MCP, screenshots) and tick
   (`- [x]`) the ones you verified. Leave the ones only the user can judge unticked. For anything
   the player sees, capture the gameplay camera and look at it before calling it done.
5. When the task completes a milestone with new gameplay, run the critic first (skill
   `ludovanta-design-review`, checkpoint `first-playable` for the first milestone, `milestone` later)
   and fix its BLOCKER and MAJOR findings.
6. `plan set T-xxx --status review` (the test gate: it needs a green full `test` run newer than the
   code, see `AGENTS.md`, Feedback loop) and report with the format from `AGENTS.md`
   ("Report against the criteria"). Do not set `done` yourself: the user accepts the task. You may continue with the
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

## When the plan is complete

`plan` prints PLAN_COMPLETE when every task is `done` or `dropped`. A plan is one iteration; the game
and `design.md` go on.

1. Tasks still in review: ask the user to accept them first. Tasks left over: ask whether to drop
   them or carry them into the next plan (`plan close --carry`).
2. `plan close` moves `goal.md`, `handoff.md`, the milestones and the tasks to
   `plan/archive/NN-<title>/` and writes `SUMMARY.md` there. Task and milestone numbers continue in
   the next plan; tasks of closed plans count as done dependencies.
3. Fill the `## Retrospective` in `SUMMARY.md` with the user: what the playtest showed, what was fun
   and what was boring, which tasks failed and why, what to change in how agents work (sizes, the
   `agent` field; `plan stats` gives the numbers, see "Splitting tasks between agents").
4. The next iteration starts with the design (skill `ludovanta-game-design`, "Next iteration"), then
   `plan init --title "..."` for the new `goal.md`, then planning as above.
5. Commit the closed plan and the new plan separately.

Older plans are read only when needed (for example "why did we do X"): they are history, not
context for every session.

## Showing progress

When the user asks how things are going, run `plan` and present it briefly in the user's language:
overall percent, each milestone's percent, what waits for the user's review (list these first: the
user is the bottleneck there), what is blocked or stopped, and what comes next.
