# Spec Delta

## MODIFIED Requirements

### Requirement: No line into a busy terminal or a draft
The watcher SHALL hold the line back while the orchestrator's agent is not idle, while its terminal had output in
the last 60 seconds (typing shows as output, and the line would land in the user's draft), or while Orca refuses
input because the agent shows a dialog (`agent_prompt_blocked`). A refusal SHALL count as holding back, not as a
failure.

#### Scenario: Orchestrator working
- **WHEN** an executor finishes while the orchestrator's agent is busy
- **THEN** nothing is typed until the agent is idle

#### Scenario: User typing an answer
- **WHEN** an executor stops while the user is typing in the orchestrator's terminal
- **THEN** nothing is typed until the terminal has been quiet for 60 seconds

#### Scenario: Dialog open in the orchestrator's terminal
- **WHEN** an executor finishes while the orchestrator shows a question dialog and Orca answers the line with `agent_prompt_blocked`
- **THEN** the watcher logs that a dialog is open, keeps the news, and tries again next round without counting a failure

### Requirement: Holding back is limited
When news has waited 10 minutes because the terminal looked busy or typed in, the watcher SHALL type the line anyway.
An open dialog SHALL NOT be subject to this limit: Orca refuses the line, so the watcher keeps waiting. Every reason for
holding back SHALL be written to `Logs/ludovanta/worker-watch.log` when it starts and every 5 minutes.

#### Scenario: Terminal that never looks free
- **WHEN** news has been held back for more than 10 minutes
- **THEN** the line is typed although the terminal still looks busy, and the log says so

#### Scenario: Dialog open for a long time
- **WHEN** the orchestrator's dialog stays open for 30 minutes while news waits
- **THEN** the watcher types nothing until Orca accepts the line, and the log holds one line about the dialog per 5 minutes

### Requirement: Watcher ends by itself
The watcher SHALL exit when no executors are left, when another watcher has taken over, or when Orca has been
unreachable for 10 minutes. A failed round SHALL be logged, the same failure at most once per 5 minutes, and SHALL NOT
stop the watcher.

#### Scenario: Last executor finished
- **WHEN** the orchestrator runs `worker finish` for the last executor
- **THEN** the watcher exits within one round and logs "exited: no executors left"

#### Scenario: Round fails
- **WHEN** a call to Orca fails during a round
- **THEN** the failure is logged and the next round runs as usual

#### Scenario: Same failure every round
- **WHEN** the same call to Orca fails in every round for 12 minutes
- **THEN** the log holds that failure three times, not once per round

## ADDED Requirements

### Requirement: Delivery of the line checked
After typing the line, the watcher SHALL ask Orca to confirm that it was submitted as the agent's prompt, and SHALL
write to the log when Orca accepted the input but does not confirm a submission, so a line that never reached the
orchestrator is visible.

#### Scenario: Line not submitted
- **WHEN** Orca accepts the typed line but reports no submission within the wait
- **THEN** the log says that the line for those executors was typed but not confirmed as submitted
