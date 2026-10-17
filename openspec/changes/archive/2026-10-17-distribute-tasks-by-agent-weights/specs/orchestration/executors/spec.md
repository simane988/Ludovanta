# Spec Delta

## MODIFIED Requirements

### Requirement: Agent choice
The executor's agent SHALL be the one agent assignment picks: the `--agent` option, else the card's pinned `agent`,
else for `agent: any` the weighted pick (see `orchestration/agent-assignment`). When `codex.sandbox`, `codex.model` or
`codex.approval` is set in `ludovanta.json` or `ludovanta.local.json`, Codex SHALL be started by Ludovanta in an Orca
terminal with `--sandbox`, `--model` and `--ask-for-approval` for the settings given, the prompt typed in once ready.

#### Scenario: Codex with project settings
- **WHEN** `ludovanta.local.json` sets a Codex sandbox and model and the orchestrator starts a task with `--agent codex`
- **THEN** the agent terminal runs `codex --sandbox <sandbox> --model <model>` and then receives the task prompt

#### Scenario: Codex with an approval policy
- **WHEN** `ludovanta.local.json` sets `"codex": {"sandbox": "danger-full-access", "approval": "never"}` and a task starts with Codex
- **THEN** the agent terminal runs `codex --sandbox danger-full-access --ask-for-approval never`, and the executor runs its commands without waiting for confirmations

#### Scenario: Agent that never gets ready
- **WHEN** an agent terminal started by Ludovanta does not become ready within the start timeout
- **THEN** the command fails with `AGENT_NOT_READY`, no prompt is typed into it, and the message says to look at the terminal and then run `worker send T-xxx` to give the task

#### Scenario: Codex asks to trust the folder
- **WHEN** a Codex terminal is not ready because Codex asks "Trust this folder?" or to set up its sandbox
- **THEN** `AGENT_NOT_READY` names that dialog, says that the user answers it in Orca, and gives `worker send T-xxx` for afterwards

#### Scenario: General task
- **WHEN** a card says `agent: any` and `agentWeights` is set
- **THEN** the executor's agent is the one picked by the weights

### Requirement: Messages to an executor
`worker send T-xxx "text"` SHALL type the text as one line into the executor's agent terminal, found again through
Orca when its handle changed, and SHALL treat the executor as running again for the start grace period. Without
text, `worker send T-xxx` SHALL type the task prompt that `worker start` gives the executor.

#### Scenario: Answer to a stopped executor
- **WHEN** T-001 is stopped with a question and the orchestrator sends the answer
- **THEN** the answer arrives in T-001's terminal and T-001 is `running` again

#### Scenario: Task prompt after a dialog
- **WHEN** T-010's Codex terminal was not ready at the start, the user has answered its dialog, and the orchestrator runs `worker send T-010`
- **THEN** T-010's terminal receives the same task prompt `worker start` would have typed, and T-010 is `running`

## ADDED Requirements

### Requirement: Codex approval setting checked
`codex.approval` SHALL be one of `untrusted`, `on-failure`, `on-request` and `never`; another value SHALL fail
`worker start` for a Codex executor with a message naming the setting, before anything is committed or started.

#### Scenario: Unknown approval value
- **WHEN** `ludovanta.local.json` has `"codex": {"approval": "always"}` and a task starts with Codex
- **THEN** `worker start` fails naming `codex.approval` and its allowed values, the card stays `todo`, and nothing starts
