# Spec Delta

## Purpose

Decides which agent, Claude Code or Codex, executes a plan task: pinned tasks go to their agent, and general tasks
are split between the agents usable on this machine in the proportions the user configured.

## ADDED Requirements

### Requirement: Pinned agent wins
A card whose `agent` is `claude` or `codex` SHALL be executed by that agent, never reassigned by the weights, and SHALL
NOT count toward any agent's share. `worker start --agent` SHALL override both the card and the weights.

#### Scenario: Image task pinned to Codex
- **WHEN** a card says `agent: codex` and the weights favour Claude
- **THEN** `worker start` starts Codex for it

#### Scenario: Override on the command line
- **WHEN** a card says `agent: any` and the orchestrator runs `worker start T-007 --agent claude`
- **THEN** Claude executes it and the weights are not consulted

### Requirement: Weights in the configuration
Weights SHALL be read from `agentWeights` in `ludovanta.json`, an object from agent name to a number of zero or more;
`agentWeights` in `ludovanta.local.json` SHALL replace it as a whole. An unknown agent name, a negative or non-numeric
weight, or all weights zero SHALL fail `worker start` with a message naming the setting.

#### Scenario: Machine without Codex
- **WHEN** `ludovanta.json` has `{"claude": 2, "codex": 1}` and `ludovanta.local.json` has `{"claude": 1, "codex": 0}`
- **THEN** on this machine every `any` task goes to Claude

#### Scenario: Invalid weights
- **WHEN** `agentWeights` is `{"claude": 1, "gemini": 1}`
- **THEN** `worker start` of an `any` card fails, names `agentWeights` and the unknown agent, and starts nothing

### Requirement: General tasks split by weighted work
For a card with `agent: any`, `worker start` SHALL pick, among usable agents with a weight above zero, the one whose
share stays lowest after taking the task: (its weight-assigned work + this task's size) divided by its weight, sizes
S=1, M=2, L=4. Ties SHALL go to the higher weight, then to Claude.

#### Scenario: Two to one
- **WHEN** weights are `{"claude": 2, "codex": 1}` and six S tasks with `agent: any` are started one after another
- **THEN** Claude gets four and Codex gets two

#### Scenario: Size counts
- **WHEN** weights are equal, Claude already holds one weight-assigned L task (4) and Codex holds one S task (1)
- **THEN** the next `any` task, of size M, goes to Codex

#### Scenario: First task with equal weights
- **WHEN** weights are `{"claude": 1, "codex": 1}` and no task has been assigned by weights yet
- **THEN** the first `any` task goes to Claude

### Requirement: Weight-assigned work counted from the plan
An agent's weight-assigned work SHALL be the sum of sizes of the plan's cards that were assigned to it by the weights
and are not `todo` or `dropped`, so a task sent back to `todo` or dropped frees its share.

#### Scenario: Dropped task
- **WHEN** a weight-assigned Codex task is dropped
- **THEN** it no longer counts toward Codex's share for the next pick

### Requirement: Choice recorded on the card
When the weights pick the agent, the card SHALL record the agent in `agent` and that it was assigned by weights, and
`worker start` SHALL say which agent was picked and the shares that led to it.

#### Scenario: Card after a weighted start
- **WHEN** `worker start T-007` picks Codex for an `any` card
- **THEN** the committed card says `agent: codex` and is marked as assigned by weights, and the output names Codex with each agent's share

### Requirement: Only usable agents
Claude SHALL count as usable. Codex SHALL count as usable when its CLI is found and it is logged in. The weights SHALL
skip an agent that is not usable and say so. A card pinned to an agent that is not usable SHALL be refused with
`AGENT_UNAVAILABLE`, naming what to fix, and nothing SHALL start.

#### Scenario: Codex logged out
- **WHEN** weights favour Codex but Codex is not logged in
- **THEN** the `any` task goes to Claude and the output says that Codex was skipped and how to log in

#### Scenario: Pinned to an unusable agent
- **WHEN** a card says `agent: codex` and the Codex CLI is not found
- **THEN** `worker start` fails with `AGENT_UNAVAILABLE`, the card stays `todo`, and no terminal is opened

### Requirement: Editor tasks go to agents with Unity MCP
For a card with `editor: true` and `agent: any`, the weights SHALL consider only agents that have Unity MCP for this
project, as long as at least one has it; when none has it, all usable agents SHALL be considered, as before. Cards with
`editor: false` are not affected.

#### Scenario: Codex without Unity MCP
- **WHEN** weights are `{"claude": 1, "codex": 1}`, only Claude has Unity MCP, and an `any` card with `editor: true` is started
- **THEN** Claude gets it as a weight-assigned task, and the output says that Codex was left out for lacking Unity MCP in this project

#### Scenario: Both agents have Unity MCP
- **WHEN** Claude and Codex both have Unity MCP for this project and an `any` card with `editor: true` is started
- **THEN** the weights pick between both, as for any other task

#### Scenario: No agent has Unity MCP
- **WHEN** no agent has Unity MCP for this project and an `any` card with `editor: true` is started
- **THEN** the weights pick among all usable agents, and the output says that the executor can work only HEADLESS while the Editor is closed

### Requirement: Warning for a pinned Editor task without Unity MCP
When a card with `editor: true` is started for an agent without Unity MCP for this project (pinned or `--agent`), the
executor SHALL start, and the output SHALL warn that it can work only HEADLESS, with the Unity Editor closed.

#### Scenario: Pinned to Codex without Unity MCP
- **WHEN** a card with `editor: true` says `agent: codex` and Codex has no Unity MCP for this project
- **THEN** Codex starts and the output warns that it cannot use the open Editor

### Requirement: Unity MCP found from the agents' own configuration
An agent SHALL count as having Unity MCP for this project when its configuration lists an MCP server that is
Unity's (its name or command mentions Unity) and that, if it names a project path, names this project. Claude: the
project's `.mcp.json` and `~/.claude.json`; Codex: `codex mcp list --json`. These SHALL only be read.

#### Scenario: Claude through the project's .mcp.json
- **WHEN** the project's `.mcp.json` has a `unity-mcp` server running Unity's relay with `--project-path` set to this project
- **THEN** Claude has Unity MCP for this project

#### Scenario: Codex bound to another project
- **WHEN** Codex lists a Unity MCP server whose `--project-path` is a different project
- **THEN** Codex does not have Unity MCP for this project

#### Scenario: Codex without MCP servers
- **WHEN** `codex mcp list --json` returns an empty list
- **THEN** Codex does not have Unity MCP

### Requirement: Unity MCP set by hand when detection is wrong
`unityMcp` in `ludovanta.json` or `ludovanta.local.json`, an object from agent name to true or false, SHALL override
what was read from the agents' configuration for the named agents.

#### Scenario: Override for Codex
- **WHEN** detection finds no Unity MCP for Codex but `ludovanta.local.json` has `"unityMcp": {"codex": true}`
- **THEN** Codex counts as having Unity MCP for this project

### Requirement: Doctor shows assignment
`doctor` SHALL show the effective weights, which agents are usable on this machine, and which have Unity MCP for this
project, with the source (configuration or `unityMcp`), and SHALL write nothing to any agent's configuration.

#### Scenario: Doctor on this machine today
- **WHEN** only Claude has Unity MCP and `agentWeights` is `{"claude": 2, "codex": 1}`
- **THEN** `doctor` lists the weights, both agents as usable, Unity MCP for Claude only, and that Editor tasks will all go to Claude

### Requirement: Without weights nothing changes
When `agentWeights` is not set, a card with `agent: any` SHALL go to Claude, as before.

#### Scenario: No setting
- **WHEN** neither configuration file has `agentWeights`
- **THEN** `worker start` of an `any` card starts Claude and does not mark the card as assigned by weights
