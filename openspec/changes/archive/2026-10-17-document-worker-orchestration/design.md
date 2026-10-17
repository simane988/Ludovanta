# Design

## Context

The executor workflow is described in three places today, each for a different reader: `orca.py`'s docstring (for
whoever changes the code), the "Running the plan" section of `payload/skills/ludovanta-plan/SKILL.md` (for the
orchestrator agent, in English) and the "worker" section of `README.md` (for the user, in Russian). They mostly agree;
the specs in this change become the contract all three follow. The watcher and the waiting-for-the-user block were
shaped by live runs in Orca on a throwaway project (wake-ups after the turn ended, a second question while the first
was open, answers routed by number), and those runs found two bugs that are fixed in the working tree.

The orchestrator is a Claude Code session; executors are Claude Code or Codex. The specs describe the worker
commands, which work the same whoever runs them, but the parts that rely on the orchestrator's agent (Claude Code
hooks restarting the watcher at session start, the reply rule in the skill) are written for Claude Code. A Codex
orchestrator is out of scope until it is needed.

## Goals / Non-Goals

**Goals:**
- One place that states what the executor workflow guarantees, testable scenario by scenario.
- Record why the mechanisms are what they are, so later changes do not undo them by accident.

**Non-Goals:**
- No new command or flag. Behavior changes only where the review of code against specs found the code short of
  what the workflow promises, and the user decided to fix it here (see "Decisions after the review").
- `worktree clean` and the Claude Code handoff hooks are not specified here; they are their own capabilities later.
- The skill is not rewritten around the specs: it stays the orchestrator's working instruction.

## Decisions

**Specs as the contract, README and skill as views of it.** The specs say what must hold; the skill tells the agent
what to do, and the README explains it to the user. Alternative: make the README the contract. Rejected: it is
written for the user in Russian and leaves out details agents rely on (status codes, grace periods).

**Three capabilities under `orchestration/`.** Executors, watcher and user questions change for different reasons
(Orca and git mechanics, waking an agent, talking to the user). A single spec would mix them; one per command would
split the workflow the user sees as one.

**Rationale recorded for the watcher (in the specs' terms):**
- *A line typed into the orchestrator's terminal*, not Orca's orchestration inbox. The inbox is durable, but Orca
  itself calls its wake-up best-effort, and adopting it means rewriting `worker start` on a protocol that is still
  changing. Claude Code's `Monitor` works only for Claude, while Ludovanta keeps the same rules for Claude and Codex.
- *The card and the executor state are the truth; the line is only a doorbell.* A lost line costs a delay, not data:
  the next `worker wait` shows everything.
- *60 seconds of quiet* before typing: the user may be typing an answer in the same terminal, and the line would join
  their draft and send it half-written. *Limited to 10 minutes*: in one live run the line was held back for 30
  minutes for a reason the log did not record; a typed line that waits in Claude Code's queue is harmless.
- *A numbered block produced by Ludovanta*, not left to the model: in the conversation an earlier question sits above
  the newest reply, out of sight, so the list must be rebuilt from state on every `worker wait`.

**Decisions after the review** (2026-10-17, by the user, on the findings in tasks.md):
- A working agent keeps an executor `running` whatever its card says: intended, written into the executors spec.
- `gone` also covers a worktree Orca no longer lists: intended, written into the executors spec.
- The waiting-for-the-user block is printed also when no executors are left: a code fix in this change.
- The question quote is taken from the whole final message, not the report's last 40 lines: a code fix in this
  change; the 40-line report is written into the executors spec.
- `worker wait` and `worker list` keep the watcher running whenever executors exist, also when every executor
  they show has settled: a code fix in this change.

## Risks / Trade-offs

- [Specs drift from the code as it changes] → each scenario names observable output (status codes, messages, files),
  and the apply step adds tests for scenarios without one, so drift fails a test.
- [The specs freeze a bug as intended behavior] → the apply step reviews code against specs and reports mismatches
  instead of choosing silently.
- [The 30-minute hold-back is not explained] → the watcher now logs every reason; the next occurrence will show it.
  The specs state the limit, not the cause.
- [The question quote is a heuristic (paragraphs with "?")] → the full report is printed above the block, so a bad
  quote loses nothing.

## Migration Plan

Commit the working-tree implementation first (v0.1.5), then apply this change and archive it, which creates
`openspec/specs/orchestration/{executors,watcher,user-questions}/spec.md`. Nothing to roll back in game projects: no
platform file changes behavior.
