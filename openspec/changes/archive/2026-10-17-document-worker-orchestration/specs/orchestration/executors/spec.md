# Spec Delta

## Purpose

Runs the tasks of a plan as separate executor agents in Orca (Claude Code or Codex), each with a fresh context, while
the orchestrator, a Claude Code session that talks to the user, starts them, judges their state, answers them and takes
their work in.

## ADDED Requirements

### Requirement: Lane chosen by the card's editor field
A task card with `editor: true` (the default) SHALL run in a new agent terminal in the main working copy, without a
worktree. A card with `editor: false` SHALL run in its own Orca worktree created from the current branch, HEADLESS,
without Unity MCP.

#### Scenario: Task that needs the Unity Editor
- **WHEN** the orchestrator runs `worker start T-003` for a card with `editor: true`
- **THEN** an agent terminal titled with the task id and title opens in the main working copy and no worktree is created

#### Scenario: Task without the Editor
- **WHEN** the orchestrator runs `worker start T-001` for a card with `editor: false`
- **THEN** Orca creates a worktree based on the current branch with the agent in it, and the agent is told to work HEADLESS without Unity MCP

### Requirement: One Editor task at a time
While an executor works in the Editor lane, starting another Editor task SHALL be refused with `EDITOR_BUSY` naming the
busy task. Worktree tasks SHALL still start in parallel.

#### Scenario: Second Editor task
- **WHEN** T-003 runs in the Editor lane and the orchestrator starts T-004, also `editor: true`
- **THEN** the command fails with `EDITOR_BUSY` and names T-003

#### Scenario: Worktree task during an Editor task
- **WHEN** T-003 runs in the Editor lane and the orchestrator starts T-001 with `editor: false`
- **THEN** T-001 starts in its own worktree

### Requirement: Start only what an executor can finish
`worker start` SHALL refuse with `NOT_STARTABLE` and list every reason when the card has no acceptance criteria, is not
`todo` or `in-progress`, has unfinished dependencies (finished means `review` or `done`), the plan folder has
uncommitted changes, the main working copy is on a detached HEAD, or the command runs in a linked worktree.

#### Scenario: Uncommitted plan
- **WHEN** `plan/` has uncommitted changes and the orchestrator starts a task
- **THEN** the command fails with `NOT_STARTABLE`, says to commit the plan first, and nothing is started

#### Scenario: Unfinished dependency
- **WHEN** T-002 depends on T-001, which is still `todo`
- **THEN** `worker start T-002` fails with `NOT_STARTABLE` naming T-001

### Requirement: Card committed as in-progress before the start
Before the agent starts, `worker start` SHALL set the card to `in-progress`, record the agent, and commit the card on
the current branch, so that the executor's later change to `review` merges cleanly.

#### Scenario: Card state seen by both sides
- **WHEN** `worker start T-001` succeeds
- **THEN** the card is `in-progress` both in the main working copy (committed) and in the executor's worktree

### Requirement: Only one executor per task
`worker start` SHALL refuse with `WORKER_EXISTS` when the task already has an executor.

#### Scenario: Starting the same task twice
- **WHEN** T-001 has an executor and the orchestrator runs `worker start T-001` again
- **THEN** the command fails with `WORKER_EXISTS` and nothing new is started

### Requirement: Agent choice
The executor's agent SHALL be the `--agent` option, else the card's `agent` (`claude` or `codex`), else `claude`.
When `codex.sandbox` or `codex.model` is set in `ludovanta.json` or `ludovanta.local.json`, Codex SHALL be started as
`codex --sandbox ... --model ...` in an Orca terminal, with the prompt typed in once its interface is ready.

#### Scenario: Codex with project settings
- **WHEN** `ludovanta.local.json` sets a Codex sandbox and model and the orchestrator starts a task with `--agent codex`
- **THEN** the agent terminal runs `codex --sandbox <sandbox> --model <model>` and then receives the task prompt

#### Scenario: Agent that never gets ready
- **WHEN** an agent terminal started by Ludovanta does not become ready within the start timeout
- **THEN** the command fails with `AGENT_NOT_READY`, no prompt is typed into it, and the message says how to give the task by hand

### Requirement: The executor's prompt
The prompt SHALL tell the executor its task id and lane, to run `plan brief <task>` and work by its rules, not to
commit, merge or push, and that its final message is the task report.

#### Scenario: Prompt of a worktree executor
- **WHEN** a worktree executor starts
- **THEN** its prompt names the task, says HEADLESS without Unity MCP, points to `plan brief`, and forbids committing

### Requirement: Executor state
Each executor SHALL be judged as one of: `running` (its agent works, or it started less than 90 seconds ago and its
card is not finished or blocked), `finished` (card in `review` or `done`), `blocked` (card `blocked`), `stopped` (agent
idle, card not finished) or `gone` (its folder no longer exists, or Orca no longer lists it). Once the agent is idle,
the card is the source of truth.

#### Scenario: Agent idle with the card in review
- **WHEN** an executor's agent is idle and its card says `review`
- **THEN** the executor is `finished`

#### Scenario: Agent idle with the card still in progress
- **WHEN** an executor's agent is idle, its card says `in-progress` and the start was more than 90 seconds ago
- **THEN** the executor is `stopped`: it asked a question, failed, or hit a STOP

#### Scenario: Worktree unknown to Orca
- **WHEN** Orca no longer lists an executor's worktree, although its folder is still on disk
- **THEN** the executor is `gone`: without Orca's listing its agent cannot be judged

### Requirement: A working agent comes first
While an executor's agent works, the executor SHALL be `running` whatever its card says: an executor sets its card to
`review` before it writes its final report, and finishing it then would take a half-written report and merge work
mid-turn.

#### Scenario: Card in review, agent still writing
- **WHEN** an executor has set its card to `review` and its agent is still working
- **THEN** the executor is `running`, and `worker wait` keeps waiting for it

#### Scenario: Editor executor next to the orchestrator
- **WHEN** an Editor-lane executor and the orchestrator both have agents in the main working copy
- **THEN** the executor is judged by its own terminal pane, never by the orchestrator's agent

### Requirement: Waiting for executors
`worker wait [T-xxx ...]` SHALL return as soon as at least one of the given executors (default: all) is not `running`,
or after its timeout (default 540 seconds), and print each executor's state with the last 40 lines of the final
message of every settled one as its report. `worker list` SHALL print the same without waiting.

#### Scenario: One executor finishes
- **WHEN** T-001 finishes while T-002 still runs
- **THEN** `worker wait` returns `WORKERS_SETTLED`, shows T-001 `FINISHED` with its report and T-002 `RUNNING`

#### Scenario: Nothing settles in time
- **WHEN** no executor settles before the timeout
- **THEN** `worker wait` returns `WORKERS_RUNNING` and says to run it again

#### Scenario: Finished worktree on the Orca board
- **WHEN** `worker wait` reports a worktree executor as finished
- **THEN** its Orca worktree is marked as in review and unread

### Requirement: Messages to an executor
`worker send T-xxx "text"` SHALL type the text as one line into the executor's agent terminal, found again through
Orca when its handle changed, and SHALL treat the executor as running again for the start grace period.

#### Scenario: Answer to a stopped executor
- **WHEN** T-001 is stopped with a question and the orchestrator sends the answer
- **THEN** the answer arrives in T-001's terminal and T-001 is `running` again

### Requirement: Finishing a worktree executor
`worker finish T-xxx` for a worktree executor SHALL commit everything in its worktree, merge its branch into the
branch it started from with `--no-ff`, then remove the worktree through Orca and delete the branch. The executor
itself never commits.

#### Scenario: Clean merge
- **WHEN** a finished worktree executor is finished
- **THEN** its work is on the base branch in a merge commit named after the task, its worktree and branch are gone, and the main working copy is clean

#### Scenario: Merge conflict
- **WHEN** the executor's branch conflicts with the base branch
- **THEN** the command fails with `MERGE_CONFLICT`, lists the files, aborts the merge so nothing is merged, and says to have the executor merge the base branch and resolve

#### Scenario: Wrong branch checked out
- **WHEN** the main working copy is on a different branch than the executor started from
- **THEN** the command fails with `WRONG_BRANCH` and merges nothing

#### Scenario: Nothing to merge
- **WHEN** the executor's branch has no commits beyond the base branch after its work is committed
- **THEN** the command fails with `NOTHING_TO_MERGE`

### Requirement: No merges under a working Editor
`worker finish` of a worktree executor SHALL be refused with `EDITOR_BUSY` while an Editor-lane executor works.

#### Scenario: Merge during an Editor task
- **WHEN** T-003 works in the Editor lane and the orchestrator finishes worktree task T-001
- **THEN** the command fails with `EDITOR_BUSY` and nothing is merged

### Requirement: Finishing an Editor executor
`worker finish T-xxx` for an Editor-lane executor SHALL require the card in `review` or `done`, commit only the files
changed since the start (files already uncommitted at the start stay out and are listed), and close the executor's
agent terminal.

#### Scenario: User's own work in progress
- **WHEN** the user had an uncommitted file before T-003 started and T-003 is finished
- **THEN** the commit holds only T-003's files, the user's file stays uncommitted, and only T-003's terminal is closed

#### Scenario: Executor not done
- **WHEN** the card of an Editor-lane executor is still `in-progress`
- **THEN** the command fails with `NOT_FINISHED` and commits nothing

### Requirement: Without Orca
When Orca is not running, worker commands SHALL fail with `ORCA_UNAVAILABLE` without changing the plan, and
`worker start` SHALL point to executors without Orca: a subagent, or `codex run`.

#### Scenario: Orca closed
- **WHEN** Orca is not running and the orchestrator runs `worker start T-001`
- **THEN** the command fails with `ORCA_UNAVAILABLE`, T-001 stays `todo`, and the message names the alternatives
