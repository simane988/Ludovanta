# orchestration/watcher Specification

## Purpose
Wakes the orchestrator when an executor finishes, stops or is blocked, also after the orchestrator has ended its turn,
because an agent between turns wakes only on input and `worker wait` lives inside one turn.

## Requirements

### Requirement: Orchestrator's terminal remembered
`worker start`, and `wait`, `list` and `send` while executors exist, SHALL record the Orca terminal they run in
(handle, pane, workspace) as the orchestrator's, unless that terminal belongs to one of the executors. Outside an Orca
terminal nothing is recorded.

#### Scenario: Orchestrator in Orca
- **WHEN** the orchestrator runs `worker start T-001` in an Orca terminal
- **THEN** that terminal is on record as the orchestrator's

#### Scenario: Command from an executor's terminal
- **WHEN** a worker command runs in the terminal of an executor
- **THEN** the orchestrator on record does not change

### Requirement: Watcher kept running
While executors exist and an orchestrator is on record, the worker commands and the start of a Claude Code session
SHALL start a background `worker watch` for the project unless one is running. One watcher SHALL run per project; a
watcher silent for 5 minutes counts as dead.

#### Scenario: First executor started
- **WHEN** `worker start` succeeds in an Orca terminal and no watcher runs
- **THEN** a watcher starts in the background and the output says that the orchestrator may end its turn and will be woken

#### Scenario: Second watcher
- **WHEN** a watcher already runs for the project and another one is started
- **THEN** the second one exits at once with `WATCH_BUSY`

#### Scenario: Orchestrator outside Orca
- **WHEN** no orchestrator terminal is on record
- **THEN** no watcher starts and the worker command says that nothing will wake the orchestrator, so it keeps running `worker wait`

### Requirement: One line per settled state
About every 15 seconds the watcher SHALL look at every executor. For those `finished`, `stopped`, `blocked` or `gone`
that have not been announced in that state, it SHALL type one line into the orchestrator's terminal, press Enter, and
then count them as announced.

#### Scenario: Executor finishes after the orchestrator ended its turn
- **WHEN** the orchestrator is idle and T-004 finishes
- **THEN** a line like "Ludovanta watcher: executor T-004 finished (card in review). Run ludovanta.py worker wait ..." arrives in its terminal

#### Scenario: Others still working
- **WHEN** T-003 finishes while T-004 still runs
- **THEN** the line announces T-003 and says that 1 other executor keeps working

#### Scenario: Several at once
- **WHEN** T-001 and T-002 finish in the same round
- **THEN** a single line announces both

### Requirement: Each state announced once
A state shown to the orchestrator by `worker wait` or `worker list`, or already announced, SHALL NOT be announced
again. When an executor runs again (for example after `worker send`), its next settled state SHALL be news.

#### Scenario: Already seen in worker list
- **WHEN** `worker list` showed T-001 as stopped
- **THEN** the watcher does not announce T-001's stop

#### Scenario: Stopped again after an answer
- **WHEN** the orchestrator answered stopped T-001 with `worker send`, and T-001 stops again later
- **THEN** the watcher announces the new stop

### Requirement: No line into a busy terminal or a draft
The watcher SHALL hold the line back while the orchestrator's agent is not idle, or while its terminal had output in
the last 60 seconds (typing shows as output, and the line would land in the user's draft).

#### Scenario: Orchestrator working
- **WHEN** an executor finishes while the orchestrator's agent is busy
- **THEN** nothing is typed until the agent is idle

#### Scenario: User typing an answer
- **WHEN** an executor stops while the user is typing in the orchestrator's terminal
- **THEN** nothing is typed until the terminal has been quiet for 60 seconds

### Requirement: Holding back is limited
When news has waited 10 minutes because the terminal looked busy or typed in, the watcher SHALL type the line anyway.
Every reason for holding back SHALL be written to `Logs/ludovanta/worker-watch.log` when it starts and every 5 minutes.

#### Scenario: Terminal that never looks free
- **WHEN** news has been held back for more than 10 minutes
- **THEN** the line is typed although the terminal still looks busy, and the log says so

### Requirement: Orchestrator's terminal found again
When Orca restarts and terminal handles change, the watcher SHALL find the orchestrator's terminal by its pane. When
the terminal is closed, nothing SHALL be typed.

#### Scenario: New handle, same pane
- **WHEN** the recorded handle no longer exists but a terminal in the same pane does
- **THEN** the line goes to that terminal

### Requirement: Watcher ends by itself
The watcher SHALL exit when no executors are left, when another watcher has taken over, or when Orca has been
unreachable for 10 minutes. A failed round SHALL be logged and SHALL NOT stop the watcher.

#### Scenario: Last executor finished
- **WHEN** the orchestrator runs `worker finish` for the last executor
- **THEN** the watcher exits within one round and logs "exited: no executors left"

#### Scenario: Round fails
- **WHEN** a call to Orca fails during a round
- **THEN** the failure is logged and the next round runs as usual
