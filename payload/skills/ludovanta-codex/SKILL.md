---
name: ludovanta-codex
description: Use the OpenAI Codex CLI as a plan task executor and to generate reference images (concept art, mood, characters, UI mockups) with its built-in image generation. Use when a task card says agent codex, when the user asks to give work to Codex, or when the art direction needs visual references.
---

# Codex: a task executor and a reference image generator

The orchestrator (usually Claude, see "Running the plan" in `ludovanta-plan`) stays in charge: it
picks the tasks, verifies the results and talks to the user. Codex works through `codex exec`
(non-interactive) with the user's own Codex login; Ludovanta wraps it so the output is short.

Check first: `python3 .ludovanta/ludovanta.py status` prints `codex cli: <path>` or `not found`.
Not found means: do not delegate, tell the user once (install: `npm install -g @openai/codex`,
then `codex login`; or set `codexPath` in `ludovanta.local.json`). Never change a task's `agent`
silently to get around it; ask the user.

## Tasks for Codex

The project's own rules in `AGENTS.md` win. Otherwise pin only for an ability the other agent lacks
(today: image generation, Codex). Leave everything else `agent: any`, Editor tasks included: `worker
start` uses `agentWeights` and detects Unity MCP per agent. Use `plan stats` to adjust weights; if a
pick does not fit, end the existing executor and restart with `worker start T-xxx --agent claude|codex`.

Codex reads the same rules as Claude: `AGENTS.md` with the Ludovanta block, and the `ludovanta-*`
skills in `.agents/skills` (in `skillTargets` of `ludovanta.json`; `status` warns when it is missing).
The same applies when the user works with Codex directly, for example in Orca.

When Orca is running (`status`), give a task to Codex with `worker start T-012 --agent codex`: Codex
then works in Orca, visible to the user, and the orchestrator follows it with `worker wait` and ends it
with `worker finish` (skill `ludovanta-plan`). Tasks with `editor: false` run in
their own worktree; Editor tasks prefer eligible agents with Unity MCP. Without it the executor
gets a warning: it can work only HEADLESS with the Editor closed. Codex
does not commit there: its sandbox keeps `.git` read-only, and a worktree's git data lives in the main
folder's `.git`; `worker finish` commits for it. Orca starts Codex with its own settings; when
`codex.sandbox`, `codex.model` or `codex.approval` is set in `ludovanta.json` (per machine: `ludovanta.local.json`),
`worker start` starts `codex --sandbox ... --model ...` with them instead.
`codex.approval` sets `--ask-for-approval`: `untrusted`, `on-failure`, `on-request` or `never`; no default.
If Codex in a worktree
cannot run Unity or write what it needs, set `"codex": {"sandbox": "danger-full-access"}` in
`ludovanta.local.json`: the worktree is a separate checkout, but this lifts the sandbox completely. `codex run` below is for
when Orca is not available.

```
python3 .ludovanta/ludovanta.py codex run T-012 [--model <id>] [--timeout 3600] [--json]
```

- It writes the task brief (`plan brief T-012` with the executor rules) to
  `Logs/ludovanta/codex/`, runs `codex exec` in the project folder with sandbox `workspace-write`
  (change it with `"codex": {"sandbox": "...", "model": "..."}` in `ludovanta.json`), and prints
  Codex's report, the task status and the changed files.
- It takes minutes: in Claude Code run it in the background and keep talking to the user.
- One writer at a time in one folder: do not run a Claude executor and Codex in the same project
  folder at once. In parallel only in separate git worktrees.
- Codex's sandbox may not let Unity start (licensing). Then it moves the task to review with
  `--unverified` and its report says "not compiled"; you
  compile and run the tests (Unity MCP in LIVE mode, `compile`/`test` in HEADLESS).
- Verify before reporting: review the diff, compile, run the tests, tick or untick the criteria.
  A failed result is `plan fail T-012 "..."`, like any other attempt. Exit codes: 0 done, 1 refused
  (no criteria), 2 Codex missing or failed (login, network), 4 timeout.

## Reference images

Codex has built-in image generation (`$imagegen`, gpt-image models) that runs on the user's ChatGPT
plan. Use it for **references**: concept art for the art direction, character sheets, the mood of
an area, a palette, a UI mockup. The game itself still gets its assets from the pipeline chosen in
the design (procedural, modelled, imported).

```
python3 .ludovanta/ludovanta.py codex image "<description>" --out Art/References/<name>.png [--timeout 900]
```

- Keep references outside `Assets/` (`Art/References/`), so Unity does not import them. Commit
  them: they are part of the design.
- Write the description like an art brief: subject, framing and camera, style (for example
  "anime cel shading, soft watercolor backgrounds"), palette, lighting, mood, what to avoid. Name
  the game's style from `design.md` in every prompt, so a set looks like one game.
- Generate a few variants of the key things (the hero, the first area, the main verb in action),
  show them to the user and let them pick. Then link the chosen ones in the art direction of
  `design.md` and describe what to take from each (shapes, palette, lighting), because executors
  read the design, not the pictures.
- Look at every generated image yourself before showing it: wrong anatomy, text artefacts and an
  off style are common.
- Image generation uses the user's plan limits several times faster than text: ask before
  generating more than a handful, and do not loop on "one more variant". No transparent
  backgrounds: ask for a flat chroma-key colour if a cut-out is needed.
- Fan projects: references inspired by an existing work are for the user's private use; do not
  ask for copies of official art.
