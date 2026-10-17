# Tasks

## 1. Prerequisite

- [ ] 1.1 Make sure `document-worker-orchestration` is applied and archived, so `openspec/specs/orchestration/executors`
  exists; verify `openspec validate distribute-tasks-by-agent-weights --strict` passes without the "target spec does
  not exist" note

## 2. Weights and usability

- [ ] 2.1 Read and validate `agentWeights` (merged config; known agents only; numbers >= 0; not all zero) with an
  error naming the setting; verify tests for a valid map, a local file replacing the project map, an unknown agent,
  a negative weight and all zeros
- [ ] 2.2 One shared check of whether an agent is usable (Claude always; Codex: CLI found and `codex login status`
  succeeds), reused by `doctor`; verify tests with `tests/fake_codex.py` logged in, logged out and missing, and that
  `doctor`'s Codex check still passes its tests
- [ ] 2.3 Unity MCP detection per agent, read only: Claude from the project's `.mcp.json` and `~/.claude.json` (user
  and this project's `mcpServers`), Codex from `codex mcp list --json` (extend `tests/fake_codex.py` to answer it);
  a server counts when its name or command mentions Unity and its `--project-path`, if any, is this project; an
  unreadable answer counts as no Unity MCP; `unityMcp` in the config overrides per agent; verify tests for the spec's
  scenarios (project `.mcp.json`, Codex bound to another project, empty list, override) and that no agent
  configuration file is modified

## 3. Picking the agent

- [ ] 3.1 Compute each agent's weight-assigned work from the plan (cards marked as assigned by weights, sizes
  S=1/M=2/L=4, not `todo` or `dropped`) and pick by lowest share after the task, ties to the higher weight then
  Claude; verify tests for the spec's scenarios "Two to one", "Size counts", "First task with equal weights" and
  "Dropped task"
- [ ] 3.2 Wire it into `worker start`: `--agent` first, then a pinned card, then the weights for `any`, then Claude
  without weights; record `agent` and the assigned-by-weights mark on the committed card; print the pick and the
  shares; verify tests in `tests/test_orca.py` for each branch and for the card contents in both working copies
- [ ] 3.3 Skip unusable agents in the pick with a note, and refuse a card pinned to an unusable agent with
  `AGENT_UNAVAILABLE` leaving the card `todo` and opening no terminal; verify tests for "Codex logged out" and
  "Pinned to an unusable agent"
- [ ] 3.4 For `editor: true` cards with `agent: any`, limit the pick to agents with Unity MCP when at least one has
  it, else all usable agents with a HEADLESS note; warn on a pinned or `--agent` Editor start for an agent without
  Unity MCP; verify tests for "Codex without Unity MCP", "Both agents have Unity MCP", "No agent has Unity MCP" and
  "Pinned to Codex without Unity MCP"
- [ ] 3.5 `doctor` reports the effective weights, which agents are usable, which have Unity MCP for this project and
  from which source; verify a test for its output with and without `agentWeights` and with a `unityMcp` override

## 4. Skills and README

- [ ] 4.1 Replace the "who does what" lists in "Splitting tasks between agents" (`payload/skills/ludovanta-plan/SKILL.md`)
  and "Tasks for Codex" (`payload/skills/ludovanta-codex/SKILL.md`) with one rule: pin an agent only for an ability
  the other lacks (today: image generation, Codex); leave everything else `any`, Editor tasks included (Unity MCP is
  detected); use `plan stats` to adjust weights; restart with `--agent` when a pick does not fit; the project's own
  rules in `AGENTS.md` still win; verify the installer tests still pass
- [ ] 4.2 Document `agentWeights` and `unityMcp` in the README (example, local override, `codex: 0` on machines
  without Codex, the count by size, how Unity MCP is detected and that Ludovanta never configures it) and mention
  them in the worker section; verify the example JSON parses and gives the pick the README describes

## 5. Integration check

- [ ] 5.1 Live run in Orca on a throwaway project with `agentWeights` `{"claude": 1, "codex": 1}`: three S tasks with
  `agent: any` and `editor: false`, one pinned `agent: codex` image task, and one `any` task with `editor: true` while
  only Claude has Unity MCP, started in that order; verify the worktree tasks alternate Claude, Codex, Claude, the pinned task goes to Codex
  without changing the shares, the Editor task goes to Claude with the Unity MCP note, every card records its agent,
  and `doctor` shows the same picture
- [ ] 5.2 Full test suite and `openspec validate distribute-tasks-by-agent-weights --strict` pass

## Workflow follow-up

- Archive after `document-worker-orchestration` is archived.
- Remove the throwaway project from Orca's sidebar after the live run.
