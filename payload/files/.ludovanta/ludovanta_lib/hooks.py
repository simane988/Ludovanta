"""Claude Code hooks: keep the orchestrator's context small over a long plan.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+. Installed into .claude/settings.json by the installer, run via .ludovanta/hook.sh.

    session-start   startup, /clear, compaction: print the plan brief and plan/handoff.md (stdout goes into context)
    stop            after each reply: when a milestone (or, later, any task) was just finished and the context is
                    large, ask the agent to write plan/handoff.md and to suggest /clear to the user

Both also start 'worktree clean' in the background (at session start, and after a reply that finished a task, for
example by merging an executor's branch): worktrees whose work is merged are removed (see worktrees.py). Session start
also restarts the executors' watcher if executors are left and it is not running (see orca.py).

A hook must never break the session: every failure is swallowed and the exit code is always 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import plan as plan_mod
from . import worktrees
from .common import load_config

DEFAULT_MILESTONE_TOKENS = 100_000
DEFAULT_TASK_TOKENS = 300_000
TAIL_BYTES = 4 * 1024 * 1024
FINISHED = ("review", "done", "dropped")


def context_tokens(transcript: Path) -> int:
    """Context size of the last model call: input + cache read + cache write tokens of the last assistant entry."""
    with open(transcript, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        tail = f.read().decode("utf-8", errors="replace")
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = (entry.get("message") or {}).get("usage") or {}
        total = sum(int(usage.get(k) or 0) for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if total:
            return total
    return 0


def _state_path(root: Path, session: str) -> Path:
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:80] or "session"
    return root / "Logs" / "ludovanta" / "hooks" / f"{safe}.json"


def _milestones_finished(plan: plan_mod.Plan) -> set[str]:
    done = set()
    for m in plan.milestones:
        tasks = [t for t in plan.tasks if t["milestone"] == m["id"] and t["status"] != "dropped"]
        if tasks and all(t["status"] in FINISHED for t in tasks):
            done.add(m["id"])
    return done


def finished_since_last_stop(root: Path, payload: dict) -> tuple[list[str], list[str]]:
    """Milestones and tasks finished since this session's previous reply: (milestones, tasks)."""
    plan = plan_mod.Plan(root)
    if not plan.exists:
        return [], []
    statuses = {t["id"]: t["status"] for t in plan.tasks}
    milestones = _milestones_finished(plan)

    state_file = _state_path(root, str(payload.get("session_id") or ""))
    first_run = not state_file.is_file()
    state = {} if first_run else json.loads(state_file.read_text(encoding="utf-8"))
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"statuses": statuses, "milestones": sorted(milestones)}), encoding="utf-8")
    if first_run:
        return [], []   # baseline: things finished before this session do not count

    new_milestones = sorted(milestones - set(state.get("milestones") or []))
    old = state.get("statuses") or {}
    new_tasks = sorted(t for t, s in statuses.items() if s in FINISHED and old.get(t) not in FINISHED)
    return new_milestones, new_tasks


def handoff_advice(root: Path, payload: dict, new_milestones: list[str], new_tasks: list[str]) -> str | None:
    if not new_milestones and not new_tasks:
        return None
    transcript = payload.get("transcript_path")
    tokens = context_tokens(Path(transcript)) if transcript and Path(transcript).is_file() else 0
    cfg = (load_config(root).get("handoff") or {})
    milestone_limit = int(cfg.get("milestoneTokens") or DEFAULT_MILESTONE_TOKENS)
    task_limit = int(cfg.get("taskTokens") or DEFAULT_TASK_TOKENS)
    if new_milestones and tokens >= milestone_limit:
        what = f"milestone {', '.join(new_milestones)} is finished"
    elif new_tasks and tokens >= task_limit:
        what = f"task {', '.join(new_tasks)} is finished"
    else:
        return None
    return (f"Ludovanta: {what} and this session's context is about {tokens // 1000}k tokens. Time for a handoff "
            "instead of carrying the whole history into the next work:\n"
            "1. Put durable decisions where they belong: design.md (game feel, art, the user's preferences) and the "
            "task cards ('## Handoff').\n"
            "2. Write plan/handoff.md (skill ludovanta-plan, 'Context and handoff'): where we are, what the user said "
            "that is not recorded elsewhere, what is next, open questions.\n"
            "3. End your reply with one short line in the user's language asking them to type /clear and then "
            "'continue' (for example: «Набери /clear, затем «продолжай»: новая сессия сама подхватит план и handoff»).\n"
            "Do not start the next task in this session.")


def _clean_worktrees(root: Path) -> None:
    try:
        worktrees.auto_clean(root)
    except Exception as e:  # noqa: BLE001 - cleanup is a side job, the brief and the advice matter more
        print(f"ludovanta hook: worktree cleanup not started: {e}", file=sys.stderr)


def _keep_watching(root: Path) -> None:
    """Executors may still work after a restart: their watcher wakes the orchestrator (see orca.py)."""
    try:
        from . import orca
        orca.ensure_watcher(root)
    except Exception as e:  # noqa: BLE001 - the watcher is a side job
        print(f"ludovanta hook: worker watcher not started: {e}", file=sys.stderr)


def run(root: Path, event: str) -> int:
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        payload = {}
    try:
        if event == "session-start":
            if payload.get("source", "startup") in ("startup", "clear", "compact"):
                lines = plan_mod.session_brief(root)
                if lines:
                    print("\n".join(lines))
                _clean_worktrees(root)
                _keep_watching(root)
        elif event == "stop" and not payload.get("stop_hook_active"):
            new_milestones, new_tasks = finished_since_last_stop(root, payload)
            if new_milestones or new_tasks:
                _clean_worktrees(root)
            advice = handoff_advice(root, payload, new_milestones, new_tasks)
            if advice:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": advice}},
                                 ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 - a hook must never break the session
        print(f"ludovanta hook {event} failed: {e}", file=sys.stderr)
    return 0
