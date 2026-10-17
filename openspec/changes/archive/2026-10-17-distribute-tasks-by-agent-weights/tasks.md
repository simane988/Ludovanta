# Tasks

## 1. Prerequisite

- [x] 1.1 Make sure `document-worker-orchestration` is applied and archived, so `openspec/specs/orchestration/executors`
  exists; verify `openspec validate distribute-tasks-by-agent-weights --strict` passes without the "target spec does
  not exist" note

## 2. Weights and usability

- [x] 2.1 Read and validate `agentWeights` (merged config; known agents only; numbers >= 0; not all zero) with an
  error naming the setting; verify tests for a valid map, a local file replacing the project map, an unknown agent,
  a negative weight and all zeros
- [x] 2.2 One shared check of whether an agent is usable (Claude always; Codex: CLI found and `codex login status`
  succeeds), reused by `doctor`; verify tests with `tests/fake_codex.py` logged in, logged out and missing, and that
  `doctor`'s Codex check still passes its tests
- [x] 2.3 Unity MCP detection per agent, read only: Claude from the project's `.mcp.json` and `~/.claude.json` (user
  and this project's `mcpServers`), Codex from `codex mcp list --json` (extend `tests/fake_codex.py` to answer it);
  a server counts when its name or command mentions Unity and its `--project-path`, if any, is this project; an
  unreadable answer counts as no Unity MCP; `unityMcp` in the config overrides per agent; verify tests for the spec's
  scenarios (project `.mcp.json`, Codex bound to another project, empty list, override) and that no agent
  configuration file is modified

## 3. Picking the agent

- [x] 3.1 Compute each agent's weight-assigned work from the plan (cards marked as assigned by weights, sizes
  S=1/M=2/L=4, not `todo` or `dropped`) and pick by lowest share after the task, ties to the higher weight then
  Claude; verify tests for the spec's scenarios "Two to one", "Size counts", "First task with equal weights" and
  "Dropped task"
- [x] 3.2 Wire it into `worker start`: `--agent` first, then a pinned card, then the weights for `any`, then Claude
  without weights; record `agent` and the assigned-by-weights mark on the committed card; print the pick and the
  shares; verify tests in `tests/test_orca.py` for each branch and for the card contents in both working copies
- [x] 3.3 Skip unusable agents in the pick with a note, and refuse a card pinned to an unusable agent with
  `AGENT_UNAVAILABLE` leaving the card `todo` and opening no terminal; verify tests for "Codex logged out" and
  "Pinned to an unusable agent"
- [x] 3.4 For `editor: true` cards with `agent: any`, limit the pick to agents with Unity MCP when at least one has
  it, else all usable agents with a HEADLESS note; warn on a pinned or `--agent` Editor start for an agent without
  Unity MCP; verify tests for "Codex without Unity MCP", "Both agents have Unity MCP", "No agent has Unity MCP" and
  "Pinned to Codex without Unity MCP"
- [x] 3.5 `doctor` reports the effective weights, which agents are usable, which have Unity MCP for this project and
  from which source; verify a test for its output with and without `agentWeights` and with a `unityMcp` override

## 4. Skills and README

- [x] 4.1 Replace the "who does what" lists in "Splitting tasks between agents" (`payload/skills/ludovanta-plan/SKILL.md`)
  and "Tasks for Codex" (`payload/skills/ludovanta-codex/SKILL.md`) with one rule: pin an agent only for an ability
  the other lacks (today: image generation, Codex); leave everything else `any`, Editor tasks included (Unity MCP is
  detected); use `plan stats` to adjust weights; restart with `--agent` when a pick does not fit; the project's own
  rules in `AGENTS.md` still win; verify the installer tests still pass
- [x] 4.2 Document `agentWeights` and `unityMcp` in the README (example, local override, `codex: 0` on machines
  without Codex, the count by size, how Unity MCP is detected and that Ludovanta never configures it) and mention
  them in the worker section; verify the example JSON parses and gives the pick the README describes

## 5. Integration check

- [x] 5.1 Live run in Orca on a throwaway project with `agentWeights` `{"claude": 1, "codex": 1}`: three S tasks with
  `agent: any` and `editor: false`, one pinned `agent: codex` image task, and one `any` task with `editor: true` while
  only Claude has Unity MCP, started in that order; verify the worktree tasks alternate Claude, Codex, Claude, the pinned task goes to Codex
  without changing the shares, the Editor task goes to Claude with the Unity MCP note, every card records its agent,
  and `doctor` shows the same picture
- [x] 5.2 Full test suite and `openspec validate distribute-tasks-by-agent-weights --strict` pass

## Workflow follow-up

- Archive after `document-worker-orchestration` is archived.
- Remove the throwaway project from Orca's sidebar after the live run.

## 6. Codex approval policy

- [x] 6.1 `codex.approval` (`untrusted`, `on-failure`, `on-request`, `never`) starts Codex with `--ask-for-approval`,
  alone or with `codex.sandbox` / `codex.model`; an unknown value fails `worker start` before the card is committed;
  verify tests for "Codex with an approval policy" and "Unknown approval value", and that existing sandbox/model
  tests still pass
- [x] 6.2 Document `codex.approval` in the README (Codex section and worker section) and in the `ludovanta-codex`
  skill in one line; verify the README example parses

## 7. Executors that are not ready

- [x] 7.1 `AGENT_NOT_READY` reads the terminal's screen and names Codex's "Trust this folder?" and sandbox setup
  dialogs when it sees them, says the user answers them in Orca, and gives `worker send T-xxx`; extend
  `tests/fake_orca.py` so a terminal can show such a screen; verify tests for "Agent that never gets ready" and
  "Codex asks to trust the folder"
- [x] 7.2 `worker send T-xxx` without text types the task prompt `worker start` builds for that lane; verify a test
  for "Task prompt after a dialog" and that `worker send T-xxx "text"` is unchanged
- [x] 7.3 Mention both in the skill's `AGENT_NOT_READY` line and the README; verify the skill stays short (one line)

## 8. Watcher and dialogs

- [x] 8.1 Treat `agent_prompt_blocked` from `terminal send` as holding back (logged as an open dialog, with the
  5-minute repeat), not as a failed round, and keep it out of the 10-minute limit; verify tests for "Dialog open in
  the orchestrator's terminal" and "Dialog open for a long time" with `tests/fake_orca.py` refusing input
- [x] 8.2 Log the same failed-round message at most once per 5 minutes; verify a test for "Same failure every round"
- [x] 8.3 Type the line with `--wait-submit` and log when Orca accepts it without confirming a submission; teach
  `tests/fake_orca.py` both receipts; verify a test for "Line not submitted" and that a confirmed line logs as before
- [x] 8.4 Update the README watcher paragraph (dialogs, log repeats, delivery check); the skill needs no change;
  verify by reading it against the watcher delta spec

## 9. Integration check

- [x] 9.1 Live run in Orca on the throwaway project with `"codex": {"sandbox": "danger-full-access", "approval":
  "never"}`: a Codex executor finishes a task with no confirmations; while the orchestrator shows a question dialog
  an executor finishes, and the watcher log shows the dialog wait (not failures) and a confirmed delivery after it
  closes; verify in the watcher log and the executor's terminal
- [x] 9.2 Full test suite and `openspec validate distribute-tasks-by-agent-weights --strict` pass

## Findings

- Requirements: **General tasks split by weighted work**, **Only usable agents**, **Weights in the configuration**
  (tasks 3.1 and 3.3). A valid configuration such as `{"claude": 0, "codex": 1}` leaves no eligible agent when
  Codex is missing or logged out: the weighted pick requires a usable agent with a positive weight. The spec
  defines `AGENT_UNAVAILABLE` for a pinned card, but does not define the result for an `any` card with no eligible
  agent. Falling back to Claude would ignore its zero weight; choosing a failure result requires an additional
  policy. Recommendation: explicitly require `AGENT_UNAVAILABLE` for an empty eligible set, explain how to fix
  availability or weights, leave the card unchanged and open no terminal. Add a scenario covering this case.
  Decision (user, 2026-10-17): `AGENT_UNAVAILABLE`, never override a zero weight. Spec amended: new requirement
  "No agent left by the weights" with the scenario "Claude at zero, Codex logged out", and "Editor tasks go to
  agents with Unity MCP" now looks for Unity MCP only among usable agents with a weight above zero (scenario
  "Unity MCP only at weight zero").
- Review (orchestrator, 2026-10-17), requirement **Weights in the configuration**: `agentWeights` is validated in
  `common.load_config`, which every command calls, so a typo in the weights would break `compile`, `test`, `status`
  and `doctor` too, while the requirement fails only `worker start`. Decision: validate where the weights are used
  (`worker start`); `doctor` reports an invalid `agentWeights` as a warning with the same message instead of failing.
  Resolution (executor): validation moved to `assignment.validate_weights`, called by `worker start` and caught
  by `doctor` as an `agent weights` warning. Regression tests verify invalid weights do not break `status`,
  doctor continues its checks, and worker start fails with the same message without starting an executor.
  Verified: `.venv/Scripts/python.exe -m pytest -q` — 314 passed, 1 skipped (POSIX shell required).
- Live run (orchestrator, 2026-10-17), outside the change's first specs; the user decided to add all three to
  this change (groups 6-8, specs and design amended):
  - Codex executors stop on first-run dialogs in a new project: "Trust this folder?" and, on Windows, the
    agent sandbox setup. `worker start` reports `AGENT_NOT_READY` correctly, but the orchestrator then has to
    rebuild the task prompt for `worker send`; the message could give the exact command.
  - Codex executors started by Ludovanta (`codex.sandbox` set) ask approval for every command: there is no
    setting for Codex's approval policy (`--ask-for-approval`), so an unattended executor waits on the first
    command. Proposal: `codex.approval` next to `codex.sandbox` and `codex.model`.
  - Watcher: while the orchestrator shows a selection dialog, Orca refuses `terminal send` with
    `agent_prompt_blocked` (and a retry id). The watcher counted it as a failed round, and after the 10-minute
    limit retried every 15 s, logging each failure (31 KB of log). It should treat it as "busy", log it once,
    and keep the 10-minute limit from hammering a blocked terminal.
  - The line the watcher typed at 13:47 (after `agent_prompt_blocked` let it through) never reached the
    orchestrator as a message: the orchestrator had a question dialog open for the user at the time. Where it
    went is not known; typing into a terminal that shows a dialog should be avoided, not just retried.
- Live run 9.1 (orchestrator, 2026-10-17): T-014 (`any`) went to Codex by the weights (shares 4.0 vs 2.0) and ran with
  `--ask-for-approval never` without a single confirmation. A question dialog stayed open for 13 minutes: the watcher
  logged "an open dialog blocks input" every 5 minutes and no failures (505-byte log). When the dialog closed the
  orchestrator was still busy, so the watcher typed after the 10-minute limit; Claude Code delivered the line inside the
  running turn, and the log said "typed but not confirmed as submitted", since Orca confirms only a new turn. A
  confirmed `turn_started` receipt was checked against real Orca with an idle Codex terminal.
