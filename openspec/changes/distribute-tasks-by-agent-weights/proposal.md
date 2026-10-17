# Proposal

## Why

Codex is now installed next to Claude Code and is meant to take a real share of the plan. Today every task marked
`agent: any` goes to Claude, so Codex gets only the tasks a planner pins to it by hand. Few tasks truly belong to one
agent: only Codex generates images. Tasks that need the Unity Editor need Unity MCP, which is a per-machine setup
rather than an ability of either agent: today it is connected for Claude only. Everything else should be split
between the two in proportions the user sets in the configuration.

## What Changes

- New `agentWeights` setting, for example `{"claude": 2, "codex": 1}`, in `ludovanta.json`; `ludovanta.local.json` on
  one machine replaces it as a whole (for example `{"codex": 0}` where Codex is not installed).
- `worker start` for a card with `agent: any` picks the agent by the weights: the one furthest below its share of the
  work assigned this way so far, counted by task size (S=1, M=2, L=4). The card records the chosen agent and that it
  was assigned by weights; the output says why this agent was picked.
- A card with an explicit `agent` (`claude` or `codex`) is never reassigned and does not count toward the shares.
  `--agent` on the command line still wins over both.
- An agent that cannot run on this machine (Codex not found or not logged in) is skipped by the weights, with a note;
  a card pinned to it is refused with a clear message instead of starting an agent that fails.
- An `any` task with `editor: true` goes to an agent that has Unity MCP for this project whenever at least one has
  it; Unity MCP is found by reading the agents' own configuration (read only), or set in `ludovanta.json` /
  `ludovanta.local.json` when that reading is wrong. A pinned Editor task for an agent without Unity MCP still
  starts, with a warning that it can work only HEADLESS. `doctor` shows which agents have Unity MCP.
- Ludovanta installs or configures nothing for the agents: connecting Unity MCP to Codex stays the user's step.
- Without `agentWeights` nothing changes: `any` goes to Claude.
- The orchestrator stays a Claude Code session; this change is only about executors.
- Skills: `ludovanta-plan` and `ludovanta-codex` replace the "who does what" lists with one rule: pin an agent only for
  an ability the other one lacks (today: image generation, Codex); leave the rest `any` for the weights and let
  `plan stats` show whether that needs a correction.

## Capabilities

### New Capabilities
- `orchestration/agent-assignment`: which agent executes a task: pinned agents, the weighted split of general tasks,
  agent availability on this machine (installed, logged in, Unity MCP for Editor tasks), and how the choice is
  recorded.

### Modified Capabilities
- `orchestration/executors`: the "Agent choice" requirement (introduced by `document-worker-orchestration`) now
  defers `any` cards to agent assignment instead of always choosing Claude.

## Impact

- Code: `orca.py` (`worker start`), `plan.py` (card field for weight-assigned agents, reading shares), config
  validation, `doctor.py` (report the weights, which agents are usable, which have Unity MCP). Reads, never writes,
  `.mcp.json`, `~/.claude.json` and the output of `codex mcp list --json`.
- Skills: `payload/skills/ludovanta-plan/SKILL.md` ("Splitting tasks between agents"), `ludovanta-codex`.
- README: the configuration section and the worker section.
- Depends on `document-worker-orchestration`: that change creates the `orchestration/executors` spec this one
  modifies, so it is archived first.
