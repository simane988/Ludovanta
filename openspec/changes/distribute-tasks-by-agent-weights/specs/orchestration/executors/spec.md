# Spec Delta

## MODIFIED Requirements

### Requirement: Agent choice
The executor's agent SHALL be the one agent assignment picks: the `--agent` option, else the card's pinned `agent`,
else for `agent: any` the weighted pick (see `orchestration/agent-assignment`). When `codex.sandbox` or `codex.model`
is set in `ludovanta.json` or `ludovanta.local.json`, Codex SHALL be started as `codex --sandbox ... --model ...` in an
Orca terminal, with the prompt typed in once its interface is ready.

#### Scenario: Codex with project settings
- **WHEN** `ludovanta.local.json` sets a Codex sandbox and model and the orchestrator starts a task with `--agent codex`
- **THEN** the agent terminal runs `codex --sandbox <sandbox> --model <model>` and then receives the task prompt

#### Scenario: Agent that never gets ready
- **WHEN** an agent terminal started by Ludovanta does not become ready within the start timeout
- **THEN** the command fails with `AGENT_NOT_READY`, no prompt is typed into it, and the message says how to give the task by hand

#### Scenario: General task
- **WHEN** a card says `agent: any` and `agentWeights` is set
- **THEN** the executor's agent is the one picked by the weights
