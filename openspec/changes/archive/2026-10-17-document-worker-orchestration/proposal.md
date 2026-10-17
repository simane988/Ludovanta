# Proposal

## Why

The way Ludovanta runs a plan with child executors (an orchestrator session that starts one agent per task in Orca,
waits for them, relays their questions to the user and merges their work) exists only as code, a long section of the
`ludovanta-plan` skill and part of the README. It has just grown a background watcher and a "waiting for the user"
block, both found and fixed through live runs in Orca. Before changing it further, the behavior needs one written
contract that agents and the user can check the code against. There are no OpenSpec specs in the project yet, so this
is the first baseline.

## What Changes

- Record the current executor workflow as baseline specs. Two small code fixes decided during the review (the
  waiting-for-the-user block without executors, questions found in long reports), see design.md. The specs describe
  v0.1.5, which added the watcher and the waiting-for-the-user block.
- Executor lifecycle: two lanes (Editor tasks one at a time in the main working copy, other tasks in parallel Orca
  worktrees), `worker start | wait | list | send | finish`, how an executor's state is judged (running, finished,
  stopped, blocked, gone), and who commits and merges.
- Waking the orchestrator: the background `worker watch` process, when it types into the orchestrator's terminal and
  when it holds back (busy agent, recent output, at most 10 minutes), one announcement per state.
- Questions and acceptance: the `WAITING FOR THE USER` block, the rule that every reply to the user ends with all open
  items numbered by task, and how answers go back to their own executors.
- Align the README section and the skill text with the specs where they differ, and add tests for scenarios that no
  test covers yet. No new commands, flags or messages.

## Capabilities

### New Capabilities
- `orchestration/executors`: running plan tasks as executor agents in Orca: lanes, starting, judging their state,
  sending them messages, finishing (commit, merge, cleanup), and the fallback without Orca.
- `orchestration/watcher`: the background process that wakes an idle orchestrator when an executor settles, without
  typing into the user's draft and without announcing the same state twice.
- `orchestration/user-questions`: how executors' questions and finished tasks reach the user as one numbered list by
  task, and how the user's answers are routed back.

### Modified Capabilities
None: no specs exist yet.

## Impact

- New files under `openspec/specs/orchestration/` after archiving; nothing changes for the user of a game project.
- Possible small edits to `README.md` (the "worker" section) and `payload/skills/ludovanta-plan/SKILL.md` (steps 1-5
  of "Running the plan") where they disagree with the specs.
- Possible new tests in `tests/test_orca.py` for scenarios without coverage.
- Prerequisite: the watcher and waiting-for-the-user code in the working tree (`orca.py`, `hooks.py`, `common.py`,
  `worktrees.py`, `ludovanta.py`, tests) is committed first, so the specs describe committed behavior.
