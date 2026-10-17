# Design

## Context

`worker start` resolves the agent in `orca.start`: `--agent`, else the card's `agent` if it is `claude` or `codex`,
else `claude`; it then writes the chosen agent into the card and commits it. Cards already carry `size` (S/M/L,
weighted 1/2/4 for progress in `plan.SIZES`) and `agent`. `load_config` merges `ludovanta.json` and
`ludovanta.local.json` key by key, the local file winning. `doctor` already checks that Codex is installed and
logged in (`codex login status`). The orchestrator is Claude Code, so Claude is always usable on the machine where
`worker start` runs.

## Goals / Non-Goals

**Goals:**
- The split is deterministic: the same plan and settings give the same pick, so tests can state exact outcomes.
- The plan files remain the only state: shares are computed from cards, nothing new to keep in sync.

**Non-Goals:**
- No automatic tuning of weights from `plan stats`; the user changes the numbers.
- No assignment at `plan add-task` time, no reassignment of tasks already started.
- No new agents beyond Claude Code and Codex; the setting rejects other names until a later change adds them.
- No change to who orchestrates.
- Ludovanta installs and configures nothing for the agents: connecting Unity MCP to Codex is the user's step.

## Decisions

**Pick the agent with the lowest share after taking the task** (deficit by weighted work), not random sampling.
Randomness drifts badly over the 10-30 tasks of a plan and needs a fixed seed in tests. Lowest share after the task,
rather than lowest share now, keeps an L task from going to an agent that is only slightly behind.

**Count only weight-assigned cards.** Pinned tasks are pinned for an ability (images, Unity MCP), not for load; if
they counted, ten image tasks would starve Codex of general work. The card gets a field (`assigned: weights`) next to
`agent`. Alternative: a line in the card's log. Rejected: fields are what `plan.py` parses, logs are free text.

**Count from the plan, by status.** In-progress, review, done and blocked cards count; todo and dropped do not.
Archived milestones are out of the plan and drop out of the count, so a new milestone starts close to the configured
proportions.

**`agentWeights` as a flat top-level key.** `load_config` merges only top-level keys, so the local file replaces the
whole map. This matches the "replace as a whole" requirement without a deep merge, and makes `{"codex": 0}` in the
local file mean exactly "no Codex here".

**Pin only for an ability the other agent lacks.** Today that is image generation (Codex). Unity MCP is not an
ability of either agent but a per-machine connection (on this machine: Claude through the game project's `.mcp.json`;
Codex has no MCP servers), so it is detected, not pinned: when Codex gets Unity MCP, Editor tasks start going to it by
the weights without editing any card. Size rules ("Codex only S") and "visual judgement to Claude" are not encoded:
both agents read screenshots, and `plan stats` shows per agent and size whether a weight needs to change.

**Unity MCP is a preference for Editor tasks, not a requirement.** An Editor-lane executor can work HEADLESS while
the Editor is closed (the prompt tells it to check the mode), and `doctor` only warns when Unity MCP is missing.
Refusing Editor tasks without Unity MCP would break projects that work today. So the weights prefer agents with Unity
MCP when one has it, and a pinned start for an agent without it warns instead of failing.

**Unity MCP detection reads what the agents read.** Claude: the project's `.mcp.json` and `~/.claude.json` (user and
per-project `mcpServers`), plain JSON. Codex: `codex mcp list --json`, which applies Codex's own config rules (global
and project), so Ludovanta does not parse TOML (`tomllib` is not in Python 3.9). `claude mcp list` is not used: it
connects to every server, which starts Unity's relay. A server counts as Unity's when its name or command mentions
Unity; Unity's relay takes `--project-path`, so a server bound to another project does not count. `unityMcp` in the
config overrides per agent when this guess is wrong. Nothing is ever written to an agent's configuration.

**Codex usability checked at start, cached for the command.** `codex login status` costs a process start; it runs
once per `worker start`, only when the pick involves Codex. Doctor and start share the same check.

## Risks / Trade-offs

- [Unity MCP detection misses a setup or counts a wrong one (an unusual server name, a config Claude reads that
  Ludovanta does not)] → `unityMcp` in the config overrides it; `doctor` shows what was detected and from where.
- [`codex mcp list --json` changes its output in a new Codex version] → an unreadable answer counts as "no Unity MCP"
  with a note in `doctor`, so tasks fall back to Claude rather than to an agent that cannot reach the Editor.
- [A Codex executor gets an Editor task through `--agent` without Unity MCP while the Editor is open] → the start
  warns; the executor's own mode check (`status`) tells it it cannot work there, and it stops with a question.
- [Codex is logged in but its run fails later (quota, sandbox)] → the executor stops, `worker wait` reports it, and
  the orchestrator retries with `--agent claude`; no automatic fallback mid-task.
- [Shares look wrong after manual card edits] → the card field is plain text the user can see; `plan stats` shows
  who did what.

## Migration Plan

Existing projects have no `agentWeights`, so behavior is unchanged until the user adds it. Cards assigned before
this change have no `assigned` field and do not count toward shares. Rollback: remove the setting.
