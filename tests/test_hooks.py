"""ludovanta.py hook: plan brief at session start, handoff advice after a finished milestone in a large context."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from helpers import IS_WINDOWS, NO_WINDOW, PLATFORM_DIR, write

CLI = PLATFORM_DIR / "ludovanta.py"


def hook(project, event, payload):
    p = subprocess.run([sys.executable, "-B", str(CLI), "--project", str(project), "hook", event],
                       input=json.dumps(payload), capture_output=True, encoding="utf-8", creationflags=NO_WINDOW)
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def transcript(path, tokens):
    """A Claude Code transcript whose last model call had this context size."""
    entries = [{"type": "user", "message": {"content": "go"}},
               {"type": "assistant", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 110,
                                                           "cache_creation_input_tokens": 100, "output_tokens": 5}}},
               {"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 1}}}]
    write(path, "\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


def card(project, tid, status, milestone="M1"):
    write(project / f"plan/tasks/{tid}.md", f"---\nid: {tid}\ntitle: Task {tid}\nmilestone: {milestone}\n"
                                            f"status: {status}\nsize: S\n---\n\n- [ ] Works\n")


@pytest.fixture
def game(make_project):
    p = make_project(with_git=False)
    write(p / "plan/goal.md", "# Фрирен\n")
    write(p / "plan/milestones/M1.md", "---\nid: M1\ntitle: Луг\n---\n")
    write(p / "plan/milestones/M2.md", "---\nid: M2\ntitle: Бой\n---\n")
    card(p, "T-001", "done")
    card(p, "T-002", "in-progress")
    card(p, "T-003", "todo", milestone="M2")
    return p


@pytest.mark.parametrize("source, shown", [("startup", True), ("clear", True), ("compact", True), ("resume", False)])
def test_session_start_prints_brief(game, source, shown):
    out = hook(game, "session-start", {"source": source})
    assert ("LUDOVANTA PLAN BRIEF" in out and "plan: Фрирен" in out) == shown


def test_session_start_without_plan_is_silent(make_project):
    assert hook(make_project(with_git=False), "session-start", {"source": "startup"}) == ""


def stop(game, tmp_path, tokens, **extra):
    return hook(game, "stop", {"session_id": "s1", "transcript_path": transcript(tmp_path / "t.jsonl", tokens), **extra})


def test_milestone_finished_in_large_context_asks_for_handoff(game, tmp_path):
    assert stop(game, tmp_path, 150_000) == "", "the first call only records a baseline"
    card(game, "T-002", "review")
    out = json.loads(stop(game, tmp_path, 150_000))["hookSpecificOutput"]
    assert out["hookEventName"] == "Stop"
    assert "milestone M1 is finished" in out["additionalContext"] and "about 150k tokens" in out["additionalContext"]
    assert "plan/handoff.md" in out["additionalContext"] and "/clear" in out["additionalContext"]
    assert stop(game, tmp_path, 150_000) == "", "advice is given once per milestone"


def test_small_context_or_active_stop_hook_gives_no_advice(game, tmp_path):
    stop(game, tmp_path, 50_000)
    card(game, "T-002", "review")
    assert stop(game, tmp_path, 50_000) == ""
    card(game, "T-003", "review", milestone="M2")
    assert stop(game, tmp_path, 900_000, stop_hook_active=True) == ""


def test_task_finished_in_huge_context(game, tmp_path):
    write(game / "ludovanta.json", json.dumps({"handoff": {"taskTokens": 200_000}}))
    stop(game, tmp_path, 250_000)
    card(game, "T-003", "review", milestone="M2")
    card(game, "T-004", "todo", milestone="M2")
    assert "task T-003 is finished" in stop(game, tmp_path, 250_000)


def test_broken_input_never_fails(game):
    p = subprocess.run([sys.executable, "-B", str(CLI), "--project", str(game), "hook", "stop"],
                       input="not json", capture_output=True, encoding="utf-8", creationflags=NO_WINDOW)
    assert p.returncode == 0 and p.stdout == ""


@pytest.mark.skipif(not shutil.which("sh"), reason="needs a POSIX sh (Git Bash on Windows)")
def test_hook_launcher_finds_python(game):
    shutil.copytree(PLATFORM_DIR, game / ".ludovanta", ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ)
    if IS_WINDOWS:   # make sure the test interpreter is the first 'python' the launcher tries
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    p = subprocess.run(["sh", str(game / ".ludovanta/hook.sh"), "session-start"], input='{"source": "clear"}',
                       capture_output=True, encoding="utf-8", env=env, creationflags=NO_WINDOW)
    assert p.returncode == 0
    assert "LUDOVANTA PLAN BRIEF" in p.stdout, p.stdout + p.stderr
