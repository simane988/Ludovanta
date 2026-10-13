## Ludovanta: rules for AI agents

This project uses Ludovanta, a platform for AI-first Unity development. These rules apply to every
agent (Claude Code, Codex and others): Codex reads this file directly, Claude through `CLAUDE.md`.
This block is overwritten on every platform update. Project rules and preferences belong in this
file outside the block, and they win over the defaults here.

### Running Ludovanta commands

All commands go through one entry point, run from the project root (Python 3.9+, no packages needed):

```
python3 .ludovanta/ludovanta.py <command> [options]
```

On Windows use `python` (or `py -3`) if `python3` is not available. Every command accepts `--json`.

| Command | Purpose |
|---|---|
| `status` | Mode (LIVE/HEADLESS), Unity version, whether the Unity Editor executable, Codex and Orca are found |
| `compile` | Compile the project in batchmode, list compiler errors as `path:line:col CODE message` |
| `test [--platform EditMode\|PlayMode] [--filter X] [--category Y] [--repeat N]` | Run tests, list failures; failed tests are rerun once to tell flaky from broken |
| `test-audit` | Brittle, slow and flaky tests, found without Unity |
| `validate-assets [--roots Assets ...]` | Missing/orphan `.meta` files and duplicate GUIDs (no Unity needed) |
| `plan [status\|check\|next\|brief\|stats\|add-task\|set\|fail\|close ...]` | Project plan: progress, next tasks, task cards, briefs for fresh sessions and executors, agent statistics, closing a finished plan (skill `ludovanta-plan`) |
| `codex run T-xxx` / `codex image "..." --out <file>` | Codex CLI as an executor of small tasks and as a reference image generator (skill `ludovanta-codex`) |
| `feedback add "..."` / `feedback show` | Friction log: what gets in the user's way (skill `ludovanta-feedback`) |
| `worker start T-xxx [--agent claude\|codex]` / `wait` / `list` / `send T-xxx "..."` / `finish T-xxx` | Executors in Orca, one agent per task: tasks that need the Unity Editor one at a time in the main working copy, the others in parallel worktrees (skill `ludovanta-plan`) |
| `worktree clean [--dry-run]` | Remove the git worktrees (and branches) whose work is merged into the main branch; the hooks run it on their own (skill `ludovanta-plan`) |
| `screenshot [--scene X] [--camera C] [--play SEC] [--frames N] [--label L]` | What a camera sees, with the HUD, as PNG: in batchmode or through the open Editor (skill `ludovanta-screenshot`) |
| `doctor [--offline]` | Unity, git, Python, Claude, Codex, Orca, Unity MCP and the platform itself: what is missing and what to fix first |
| `hook session-start\|stop` | Called by the Claude Code hooks Ludovanta installs; not for manual use |
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

### Two working modes

Before running anything that starts Unity, run `python3 .ludovanta/ludovanta.py status`:

- **LIVE**: Unity Editor has this project open. Unity cannot run a second instance on the same
  folder, so `compile` and `test` return `EDITOR_OPEN` (exit code 3). Work through the Unity MCP
  tools (names start with `Unity_`): read the console, inspect and change scenes/GameObjects.
  If no Unity MCP tools are available in your session, ask the user to check the Editor or to
  close it. Never kill the Unity process.
- **HEADLESS**: no Editor is open (typical for parallel agents in their own git worktree).
  Use the Ludovanta commands.

### Language and style

- Talk to the user, write reports, task cards and handoffs in the language from the project
  preferences, otherwise in the language the user writes in. Keep technical terms in English: Unity
  APIs, components, file names, commands, error messages.
- Be short. Explain a term or a decision only when the user asks or the preferences say so.
- **Project preferences** (language, how much to explain, how to split tasks between Claude and Codex)
  live in this file, `AGENTS.md`, outside the Ludovanta block, under a heading such as
  `## Preferences`: here both Claude and Codex see them, in every session and every worktree. When the
  user states a lasting preference ("always answer in Russian", "give Codex the UI code"), add it there in
  one line and say so in one short line. Do not put preferences in `CLAUDE.md` or a local config:
  the other agent would not see them.

### The goal is a game that is fun to play

Compiling code, green tests and ticked criteria are the floor, not the goal. The user wants a game
that feels like a game in the first minute and looks as polished as the fidelity they chose.

- Before planning a new game or a big feature, do the design pass (skill `ludovanta-game-design`):
  fantasy, main verb, session walk-through, game feel, art direction and the graphics fidelity,
  kept in `plan/design.md`. Ask the user about the fidelity instead of defaulting to placeholders.
- Never present raw greybox (grey capsules and boxes) below the chosen fidelity, and never leave an
  important event as a silent state change: it gets animation, effects, sound or a world reaction.
- Look at what you built: `screenshot` the gameplay camera (skill `ludovanta-screenshot`) and open
  the images, do not judge visuals from code. Visual tasks get a before and an after shot.
- When something in the environment fails (Unity not found, a license, an agent or Unity MCP missing),
  run `doctor` and give the user its one next step instead of guessing.
- A critic reviews the plan before the user sees it and the first playable before it is reported
  (skill `ludovanta-design-review`). Use it too when the user says the game is boring or raw.

### Context: the plan is the memory, sessions are disposable

Long sessions get expensive: every step re-sends the whole context. With a plan, the session that
talks to the user is the orchestrator and gives each task to an executor with a fresh context (a
subagent or Codex), then reads its short report (skill `ludovanta-plan`, "Running the plan").
Decisions live in the plan files, not in the chat. At the end of a milestone in a long session,
write `plan/handoff.md` and ask the user to type `/clear`; the next session starts from
`plan brief`. In Claude Code, Ludovanta hooks load the brief at session start and ask for the
handoff when the context grows large.

### Tasks: agree on the result, report against it, stop instead of looping

These rules apply to every task, whether it comes from the plan or from a chat message.

1. **Know the acceptance criteria before you start.** If the project has a `plan/` folder, work by
   task cards and read skill `ludovanta-plan`: a card's `- [ ]` lines are the criteria. For a request
   bigger than a small fix that has no card, state the 2-5 criteria you will check against in your
   first reply and then start. Ask first only if the request is genuinely ambiguous: the user prefers
   autonomy and a result to review over questions at every step.
2. **Report against the criteria.** Finish every task with this report, short, in the user's language
   (see "Language and style"):
   - **What changed**: what the player will notice and feel, then the main files.
   - **How to check**: the scene to open and what to do in Play mode, or the screenshot.
     For gameplay, say what to try and what should feel good.
   - **Not done or uncertain**: criteria you could not verify, shortcuts taken, known problems,
     and what still feels flat or looks unfinished. Never leave this out to make the result look
     better; write "nothing" if there is nothing.
   - **Next**: one or two suggested next steps.
3. **Stop after 3 failed attempts.** If the result fails your own verification of the criteria, or
   the user rejects it, three times in a row, stop. Do not start a fourth rewrite. Tell the user what
   you tried, why it failed, your hypotheses, and ask one concrete question. With a plan, record each
   failed attempt with `plan fail` (it tells you when to stop).

### Feedback loop

1. After changing C# code, `.asmdef` files or packages: compile (skill `ludovanta-unity-compile`).
2. Before reporting a task as done: run the relevant tests (skill `ludovanta-unity-test`) and
   `validate-assets` (skill `ludovanta-unity-assets`).
3. Never report success while compilation, tests or asset validation fail. If something cannot
   be verified (for example the environment fails with exit code 2), say so explicitly.
   With a plan this is enforced: `plan set --status review` refuses (`TESTS_NOT_GREEN`) until the last
   full `test` run of each test platform is green and newer than the code. Flaky and quarantined
   tests do not block. When Ludovanta cannot run the tests (Editor open, a sandbox), verify another
   way and pass `--unverified "<why, what you checked>"`: it is logged in the card, and the
   orchestrator runs the tests before reporting to the user.
4. A failing test is not fixed by changing what it expects. Decide whether the code or the test is
   wrong (skill `ludovanta-unity-test`, "Good tests"). Every changed expectation, `[Ignore]`, quarantine
   or deleted test is recorded in the task card's `## Log` (no card: the commit message) and in an
   executor's report to the orchestrator.

**Tests are the agents' self-check, not the user's work.** The user does not write, run, review or
decide anything about tests. Never ask them about tests, never make a test an acceptance criterion or
a plan task, and keep test details out of reports to the user: at most one line in "Not done or
uncertain" when something could not be verified. A failing, flaky or brittle test is yours to sort
out (skill `ludovanta-unity-test`: flaky tests, audit).

Batchmode runs take from seconds to several minutes (the first run in a fresh worktree imports
every asset). Batch your edits and verify once per batch, not after every line. Never run two
Unity commands in parallel for the same folder.

When the user says that something in the work gets in the way ("запиши, что неудобно", "this is
annoying"), record it in the friction log (skill `ludovanta-feedback`), then carry on.

### Rules

- Every file and folder under `Assets/` has a `.meta` file with a GUID. Read skill
  `ludovanta-unity-assets` before creating, moving, renaming or deleting assets.
- Do not hand-edit scenes, prefabs or other Unity YAML assets while the Editor is open.
- Never touch `Library/`, `Temp/`, `Logs/`, `UserSettings/`, `obj/`: they are generated.
- Platform-owned files (`.ludovanta/`, skills named `ludovanta-*`, `ludovanta:managed` blocks) are
  overwritten on update. Do not edit them; see skill `ludovanta-platform-update`.
