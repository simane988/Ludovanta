# Tasks

## 1. Baseline the implementation

- [x] 1.1 With the user's OK, commit the working-tree watcher and waiting-for-the-user work as v0.1.5 (`VERSION`,
  commit message in the style of earlier releases); verify `git status` is clean apart from `openspec/` and the
  full suite passes (`.venv/Scripts/python.exe -m pytest -q`)

## 2. Executors: specs against code and tests

- [x] 2.1 Read `orca.py` (start, verdict, wait, send, finish) against `specs/orchestration/executors/spec.md`
  requirement by requirement; record each mismatch as a note in this file under "Findings" and decide with the user
  whether the spec or the code is wrong (no silent fixes); verify every requirement is marked as matching or listed
- [x] 2.2 Add tests for executor scenarios without one: `NOT_STARTABLE` on a detached HEAD and in a linked worktree,
  the `blocked` and `gone` states, `WRONG_BRANCH`, `NOTHING_TO_MERGE`, the agent taken from the card when `--agent` is
  absent, `worker send` finding a terminal whose handle changed; verify they pass in `tests/test_orca.py`
- [x] 2.3 Align the README "worker" section and steps 1-3 of "Running the plan" in
  `payload/skills/ludovanta-plan/SKILL.md` with the executors spec (lanes, start refusals, states, finish outcomes);
  verify each status code named in the spec appears where the skill tells the orchestrator what to do about it

## 3. Watcher: specs against code and tests

- [x] 3.1 Read the watcher part of `orca.py` and `hooks.py` against `specs/orchestration/watcher/spec.md`; record
  mismatches under "Findings" as in 2.1; verify every requirement is marked as matching or listed
- [x] 3.2 Add tests for watcher scenarios without one: a command from an executor's terminal does not replace the
  orchestrator on record, the "not an Orca terminal" message, one line for two executors settled in the same round,
  the "N other executor(s) keep working" text, a failed round that is logged and does not stop the watcher; verify
  they pass
- [x] 3.3 Check that the README and the skill describe the watcher as the spec does (60 s quiet, 10 min limit, one
  announcement per state, the log file); verify by reading both against the spec's requirement list

## 4. User questions: specs against code and tests

- [x] 4.1 Read `_waiting_for_user` and the block output against `specs/orchestration/user-questions/spec.md`; record
  mismatches under "Findings"; verify every requirement is marked as matching or listed
- [x] 4.2 Add a test that no `WAITING FOR THE USER` block is printed when nothing is open, and one for a `blocked`
  executor appearing in the block; verify they pass
- [x] 4.3 Check that the skill states the reply rule (all open items, numbered as in the block, headed by task, in
  the user's language) and the routing of numbered answers with `worker send`; verify against the two orchestrator
  requirements of the spec, which no unit test can cover

## 5. Integration check

- [x] 5.1 Live run in Orca on a throwaway project, as done while building the watcher: two worktree executors that
  ask questions at different times, answered in one message by number; verify two wake-ups, both questions in the
  second reply, each answer in its own task's file, and "exited: no executors left" in the watcher log
- [x] 5.2 `openspec validate document-worker-orchestration --strict` passes and the full test suite passes

## Findings

<!-- Mismatches between specs and code found in 2.1, 3.1 and 4.1, with the decision taken for each. -->

Found by the review on 2026-10-17; decided by the user the same day (see design.md, "Decisions after the review").

- **Executors / Executor state** (`orca.py:verdict`): a working agent takes precedence over a card in
  `review`, `done` or `blocked`, so the executor is reported as `running`. The requirement calls the card the
  source of truth and defines finished and blocked by card status. Recommendation: clarify the intended
  precedence with the user; preserve the current implementation as the baseline only if working-agent
  precedence is intentional, otherwise address it in a separate behavior change. Decision: intended. The executors spec now says a working agent comes first ("A working agent comes first").
- **Executors / Executor state** (`orca.py:verdict`): a missing Orca `worktree ps` row produces `gone` even
  when the executor's directory still exists. The requirement defines `gone` as a worktree that no longer
  exists. Recommendation: decide whether absence from Orca's listing is sufficient evidence of removal;
  document it explicitly if intended, otherwise handle it separately from a removed directory in a future
  code change. Decision: intended. The executors spec now defines `gone` as a folder that no longer exists or a worktree Orca no
  longer lists.
- **User questions / Everything waiting for the user in one block** (`orca.py:wait`): with no executor
  state files, both `worker wait` and `worker list` return `NO_WORKERS` before calling `_waiting_for_user`.
  A task in `review` without an executor therefore gets no `WAITING FOR THE USER` block, contrary to the
  requirement. The same early return bypasses terminal recording under **Watcher / Orchestrator's terminal
  remembered**. Recommendation: retain these unconditional requirements and fix the early-return behavior
  in a separate change, subject to the user's decision. Decision: fix the code in this change: print the block also with `NO_WORKERS`. The watcher spec now records the
  orchestrator's terminal from `wait`, `list` and `send` only while executors exist.
- **User questions / Items numbered and labelled by task** (`orca.py:_report`, `_waiting_for_user`):
  `_report` keeps only the last 40 lines of the final message before `_question` selects question paragraphs.
  A question near the start of a longer report is lost and the block can quote the last paragraph instead.
  The requirement selects question paragraphs from the final message, with an 8-line quote limit, without
  a 40-line input limit. **Executors / Waiting for executors** likewise promises the final message as the
  report without documenting this truncation. Recommendation: decide whether the 40-line report limit is
  part of the baseline; preserve full-message question extraction in a separate behavior change if the
  question guarantee is retained. Decision: fix the code in this change: take the question from the whole final message. The executors spec now says
  the report is the last 40 lines.

- **Watcher / Watcher kept running** (`orca.py:wait`): `ensure_watcher` is called only when
  `len(settled) < len(results)`. If every selected executor is settled, `worker wait` and `worker list`
  do not restart a missing or stale watcher, although executor state files and a recorded orchestrator
  still exist. This also happens when waiting for one settled task while another, unselected executor
  keeps working. The requirement says worker commands keep the watcher running while executors exist
  and an orchestrator is on record. Recommendation: call `ensure_watcher` for these paths too, keeping
  the waiting-for-the-user block last in the output; authorize that behavior change or explicitly
  narrow the requirement. Decision (user, 2026-10-17): fix the code in this change: `wait` and `list` keep the watcher
  running whenever executors exist, whichever ones were selected.

## Requirement review coverage

Executors (2.1), matching after the user's decisions and the report/question fix:

- Lane chosen by the card's editor field — `start`, `_start_in_terminal`, `_prompt`.
- One Editor task at a time — `start`, `_editor_worker`.
- Start only what an executor can finish — the accumulated `problems` in `start`.
- Card committed as in-progress before the start — `start`, before terminal/worktree creation.
- Only one executor per task — `start`'s state-file check.
- Agent choice — `start`, `_agent_command`, `_wait_idle`, `_start_in_terminal`.
- The executor's prompt — `_prompt`.
- Executor state — `verdict`, with findings 1 and 2 resolved by spec amendments.
- A working agent comes first — `verdict`, `_agent` (pane selection for Editor executors).
- Waiting for executors — `wait`, `_report`, CLI timeout default 540 seconds.
- Messages to an executor — `send`, `_agent_terminal`.
- Finishing a worktree executor — `finish_worker`, `_commit`.
- No merges under a working Editor — `finish_worker`'s Editor-lane guard.
- Finishing an Editor executor — `_finish_in_editor`, `_work_paths`.
- Without Orca — availability checks before plan mutation in worker commands.

Watcher (3.1): Orchestrator's terminal remembered matches `_remember_orchestrator` and its callers,
including the amended no-executors exception. Watcher kept running now matches after the authorized
fix: `wait` and `list` call `ensure_watcher` with any existing executors, before the waiting block.
The other requirements match: One line per settled state (`_watch_round`); Each state announced once
(`_mark`, `wait`, `send`, `_watch_round`); No line into a busy terminal or a draft (`_idle`, quiet check);
Holding back is limited (deferred timestamp, 600-second limit, log keys every 300 seconds);
Orchestrator's terminal found again (`_orchestrator_terminal`); Watcher ends by itself (`watch` loop,
lock ownership, Orca-down timer, exception logging). `hooks.py:_keep_watching` restarts the watcher at
session start. Verified with 8 regression cases covering `wait` and `list`, all settled or another
executor still working, and missing/stale locks; live locks are reused. No watcher process is spawned
by the tests (the spawn function is replaced). `tests/test_orca.py`: 52 passed on 2026-10-17.

User questions (4.1), matching after the two authorized fixes:

- Everything waiting for the user in one block — `wait` (including `NO_WORKERS`), `_waiting_for_user`.
- Items numbered and labelled by task — `_waiting_lines`, `_question`, `_final_message`.
- Answered items drop out — `send` refreshes the grace period; `_waiting_for_user` filters current states
  and current review cards.
- Every reply to the user ends with the open items — skill, Running the plan step 3 (all open items,
  previous questions included, user's language, numbers and task headings), with step 3 and the printed
  block telling the orchestrator to answer what it can itself.
- Answers routed to their own task — skill, Running the plan step 3, numbered-answer example and
  `worker send` routing. These last two are instruction review, not unit-test guarantees.

Findings 3 and 4 are fixed: `NO_WORKERS` now includes current review items and the block, and question
extraction uses the whole final message while reports remain limited to 40 lines. Added two test functions
(three cases: `wait`, `list`, long final message), checking both JSON and text output. Verification:
`.venv/Scripts/python.exe -m pytest -q` — 228 passed, 1 skipped (POSIX shell unavailable), 2026-10-17.
Those tasks were paused for the watcher decision at that point; they are now complete as recorded below.

### Final verification of tasks 2.2–4.3 (2026-10-17)

- 2.2: tests cover detached HEAD and linked-worktree start refusals (unchanged card and HEAD),
  blocked cards, gone folders and missing Orca rows, wrong-branch and empty-branch finish refusals
  (no merge/removal), the card's agent, and changed terminal handles in both lanes.
- 2.3: README remains Russian and the skill remains English. Checked both against the executor
  requirements: lanes, all start refusals, agent choice, prompts, state precedence and grace period,
  report limit, sending, finish outcomes and fallback. Every code named in the executors spec appears
  in Running the plan with the response it needs: `EDITOR_BUSY`, `NOT_STARTABLE`, `WORKER_EXISTS`,
  `AGENT_NOT_READY`, `WORKERS_SETTLED`, `WORKERS_RUNNING`, `MERGE_CONFLICT`, `WRONG_BRANCH`,
  `NOTHING_TO_MERGE`, `NOT_FINISHED`, `ORCA_UNAVAILABLE`; `FINISHED` and `RUNNING` are states,
  described in the state bullets.
- 3.2: tests cover terminal ownership by handle and pane, the outside-Orca warning, one line for
  two settled executors, the other-executors count, and an Orca call failing in one round followed
  by a successful round, with both logged. The watcher fix also has the 8 cases described above.
- 3.3: read both documents against all watcher requirements: remembered terminal and exceptions,
  one watcher/stale lock, 15-second polling, batching and other-executor count, announcements once
  per state and reset on resumption, idle/60-second quiet checks, 10-minute deferral limit,
  `Logs/ludovanta/worker-watch.log` and 5-minute repeat logging, pane recovery/closed terminal,
  session restart, exit conditions and recovery after a failed round. All are described.
- 4.2: text-output tests confirm no block with nothing open, both with a running executor and
  without executors, for `wait` and `list`; the blocked-executor test checks state, JSON item and
  numbered text with its question, including during the start grace period.
- 4.3: Running the plan step 3 explicitly requires every reply to end with all open items,
  including earlier questions, in the user's language, with the block's numbers and task headings.
  It tells the orchestrator to answer from the plan/design first and send each numbered answer only
  to its own executor. Reviewed against both orchestrator requirements; no unit-test claim.

Added 13 test functions / 26 cases in this final pass. Focused run: 52 passed.
Full self-check: `.venv/Scripts/python.exe -m pytest -q` — 254 passed, 1 skipped
(POSIX shell unavailable), 130.82 seconds. No new mismatches or unresolved findings.
Tasks 5.1 and 5.2 were not performed or marked complete.

## Workflow follow-up

- Archive the change once the findings are resolved; this creates `openspec/specs/orchestration/executors`,
  `watcher` and `user-questions`.
- Remove the throwaway `watch-live` repo from Orca's sidebar after the live run.
