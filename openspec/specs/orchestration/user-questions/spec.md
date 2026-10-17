# orchestration/user-questions Specification

## Purpose
Makes sure every question an executor asks and every task waiting for the user's acceptance reaches the user, even
when several pile up, labelled by task, and that each answer goes back to the executor that asked.

## Requirements

### Requirement: Everything waiting for the user in one block
`worker wait` and `worker list` SHALL end with a `WAITING FOR THE USER` block when anything waits for the user:
every `stopped` or `blocked` executor, and every task in `review` in the main working copy that no executor holds. The
block SHALL include items shown before that are still open.

#### Scenario: Second question while the first is unanswered
- **WHEN** T-005 stopped with a question that the user has not answered, and T-006 then stops with its own
- **THEN** `worker wait` lists 1. T-005 with its question and 2. T-006 with its question

#### Scenario: Task waiting for acceptance
- **WHEN** T-004 is in `review` on the current branch and no executor holds it
- **THEN** the block lists T-004 as done and waiting for the user to check and accept it

#### Scenario: No executors left
- **WHEN** every executor has been finished and T-004 still waits in `review`
- **THEN** `worker list` reports that there are no executors and still ends with the block listing T-004

#### Scenario: Nothing open
- **WHEN** no executor is stopped or blocked and no task waits in review
- **THEN** there is no block

### Requirement: Items numbered and labelled by task
Each item SHALL carry a number, the task id and title. A question item SHALL quote the paragraphs of the executor's
whole final message (not only the report's last lines) that contain a question mark, up to 8 lines, or its last
paragraph when none does.

#### Scenario: Question first, report after it
- **WHEN** an executor's final message starts with its question and ends with "What changed" bullets
- **THEN** the item quotes the question, not the bullets

#### Scenario: Question at the top of a long report
- **WHEN** an executor's final message is 60 lines long and its only question is in the first paragraph
- **THEN** the item quotes that question, although the report shown above the block holds only the last 40 lines

### Requirement: Answered items drop out
An item SHALL leave the block once its executor runs again after an answer, or once its task leaves `review`.

#### Scenario: Answer sent
- **WHEN** the orchestrator sends T-001 the user's answer with `worker send`
- **THEN** the next `worker list` no longer lists T-001

### Requirement: Every reply to the user ends with the open items
While items are open, the orchestrator SHALL end every reply to the user with all of them, in the user's language,
numbered as in the block and headed by their task, also those it asked before. It SHALL answer from the plan and
design what it can and ask the user only the rest.

#### Scenario: Earlier question not lost
- **WHEN** the orchestrator already asked about T-005 and is now woken for T-006
- **THEN** its reply ends with both questions, 1 for T-005 and 2 for T-006

### Requirement: Answers routed to their own task
When the user answers by number (for example "1: red, 2: cat"), the orchestrator SHALL pass each answer to its own
executor with `worker send`, and to no other.

#### Scenario: Two answers in one message
- **WHEN** the user replies "1: red, 2: cat" to items 1. T-005 and 2. T-006
- **THEN** T-005 receives red, T-006 receives cat, and both run again
