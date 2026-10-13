"""ludovanta.py worker: executors in Orca worktrees, from start to merge (with tests/fake_orca.py as the Orca app)."""
import json
import os
import re
import time

import pytest

from helpers import PLATFORM_DIR, git, read, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"


def cli(project, *args):
    code, out = run_py(CLI, "--project", str(project), *args, "--json")
    try:
        return code, json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(out)


def card(project, tid, status="todo", depends="", agent="any", criteria="- [ ] The fare is shown", editor="false"):
    write(project / f"plan/tasks/{tid}.md",
          f"---\nid: {tid}\ntitle: Fare meter {tid}\nmilestone: M1\nstatus: {status}\nagent: {agent}\nsize: S\n"
          f"editor: {editor}\ndepends: [{depends}]\nattempts: 0\n---\n\n## Goal\nFare.\n\n"
          f"## Acceptance criteria\n{criteria}\n")


@pytest.fixture
def game(project, fake_orca_env):
    write(project / "plan/goal.md", "# Такси\n")
    write(project / "plan/milestones/M1.md", "---\nid: M1\ntitle: Поездка\n---\n")
    card(project, "T-001")
    card(project, "T-002", depends="T-001")
    card(project, "T-003", editor="true")   # needs the Unity Editor: main working copy, one at a time
    card(project, "T-004", editor="true")
    git(project, "add", "-A")
    git(project, "commit", "--quiet", "-m", "plan")
    return project


def orca_state(fake_orca_env):
    return json.loads(read(fake_orca_env))


def set_agent(fake_orca_env, handle=None, **fields):
    """Plays an agent in Orca: the one with this terminal handle, or the newest one."""
    state = orca_state(fake_orca_env)
    agent = next(a for a in state["agents"] if a["handle"] == handle) if handle else state["agents"][-1]
    agent.update(fields)
    fake_orca_env.write_text(json.dumps(state), encoding="utf-8")


def agents(fake_orca_env):
    return orca_state(fake_orca_env)["agents"]


def execute(path, tid="T-001", commit=True):
    """What an executor does in its worktree: code and the card in review. Executors leave it uncommitted
    ('worker finish' commits); a commit here stands for one made by hand, after the worktree was created."""
    admin = git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    then = time.time() - 3600
    os.utime(os.path.join(admin, "commondir"), (then, then))
    write(path / "Assets/Fare.cs", "class Fare {}\n")
    text = read(path / f"plan/tasks/{tid}.md")
    write(path / f"plan/tasks/{tid}.md", re.sub(r"status: \S+", "status: review", text, count=1) +
          "\n## Handoff\nFare.cs counts the fare.\n")
    if commit:
        git(path, "add", "-A")
        git(path, "commit", "--quiet", "-m", f"{tid}: fare")


def worker_state(project, tid="T-001"):
    return json.loads(read(project / f"Logs/ludovanta/workers/{tid}.json"))


def test_start_creates_an_orca_worktree_with_the_agent(game, fake_orca_env):
    code, out = cli(game, "worker", "start", "T-001", "--agent", "codex")
    assert code == 0 and out["status"] == "WORKER_STARTED", out
    agent = agents(fake_orca_env)[0]
    assert agent["agentType"] == "codex" and "plan brief T-001" in agent["prompt"] and "HEADLESS" in agent["prompt"]
    assert "Do not commit" in agent["prompt"], "Codex's sandbox keeps .git read-only: Ludovanta commits"
    assert orca_state(fake_orca_env)["worktrees"][0]["comment"] == "T-001 Fare meter T-001"
    create = next(c for c in orca_state(fake_orca_env)["calls"] if c[:2] == ["worktree", "create"])
    assert create[create.index("--base-branch") + 1] == "main"
    # The card is committed as in-progress before the worktree is made, so both sides start from it.
    assert "status: in-progress" in read(game / "plan/tasks/T-001.md") and "agent: codex" in read(game / "plan/tasks/T-001.md")
    assert git(game, "status", "--porcelain").stdout.strip() == ""
    assert "status: in-progress" in read(game.parent / "orca/workspaces" / os.path.basename(out["path"]) / "plan/tasks/T-001.md")
    assert worker_state(game)["branch"] == out["branch"]
    code, again = cli(game, "worker", "start", "T-001")
    assert code == 1 and again["status"] == "WORKER_EXISTS"


@pytest.mark.parametrize("case", ["uncommitted plan", "no criteria", "dependency"])
def test_start_refuses_what_an_executor_cannot_do(game, case):
    tid = "T-001"
    if case == "uncommitted plan":
        write(game / "plan/design.md", "# changed\n")
    elif case == "no criteria":
        card(game, "T-001", criteria="")
        git(game, "commit", "--quiet", "-am", "no criteria")
    else:
        tid = "T-002"
    code, out = cli(game, "worker", "start", tid)
    assert code == 1 and out["status"] == "NOT_STARTABLE", out


def test_without_orca_it_says_so(game, fake_orca_env, monkeypatch):
    monkeypatch.setenv("FAKE_ORCA_MODE", "down")
    code, out = cli(game, "worker", "start", "T-001")
    assert code == 2 and out["status"] == "ORCA_UNAVAILABLE"
    assert "status: todo" in read(game / "plan/tasks/T-001.md"), "nothing changes without Orca"


def test_wait_reports_the_finished_executor_and_finish_merges_it(game, fake_orca_env):
    _, started = cli(game, "worker", "start", "T-001")
    path = game.parent / "orca/workspaces" / os.path.basename(started["path"])
    code, out = cli(game, "worker", "wait", "--timeout", "0")
    assert code == 0 and out["status"] == "WORKERS_RUNNING" and out["workers"][0]["state"] == "running"

    execute(path, commit=False)
    set_agent(fake_orca_env, state="done", lastAssistantMessage="What changed: the fare meter\nHow to check: drive")
    code, out = cli(game, "worker", "wait", "--timeout", "5", "--poll", "0.1")
    assert out["status"] == "WORKERS_SETTLED", out
    w = out["workers"][0]
    assert w["state"] == "finished" and w["card"] == "review" and w["report"][0] == "What changed: the fare meter"
    assert orca_state(fake_orca_env)["worktrees"][0]["workspaceStatus"] == "in-review"

    code, out = cli(game, "worker", "finish", "T-001")
    assert code == 0 and out["status"] == "WORKER_FINISHED", out
    assert out["status"] and (game / "Assets/Fare.cs").is_file()
    assert "status: review" in read(game / "plan/tasks/T-001.md")
    assert not path.exists() and not orca_state(fake_orca_env)["worktrees"]
    assert started["branch"] not in git(game, "branch").stdout
    assert not (game / "Logs/ludovanta/workers/T-001.json").exists()
    assert git(game, "log", "-1", "--format=%s").stdout.strip() == "T-001: Fare meter T-001 (claude)"
    assert git(game, "status", "--porcelain").stdout.strip() == ""


def test_stopped_executor_gets_an_answer(game, fake_orca_env):
    cli(game, "worker", "start", "T-001")
    state = worker_state(game)
    state["started"] = 0   # past the start-up grace period
    write(game / "Logs/ludovanta/workers/T-001.json", json.dumps(state))
    set_agent(fake_orca_env, state="waiting", lastAssistantMessage="Which car model should the meter use?")
    code, out = cli(game, "worker", "list")
    assert out["status"] == "WORKERS_SETTLED" and out["workers"][0]["state"] == "stopped"
    assert out["workers"][0]["report"] == ["Which car model should the meter use?"]

    code, out = cli(game, "worker", "send", "T-001", "The yellow sedan.\nKeep it simple.")
    assert code == 0 and out["status"] == "WORKER_SENT"
    assert agents(fake_orca_env)[0]["sent"] == ["The yellow sedan. Keep it simple."]
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "running"


def test_finish_refuses_conflicting_work(game, fake_orca_env):
    _, started = cli(game, "worker", "start", "T-001")
    path = game.parent / "orca/workspaces" / os.path.basename(started["path"])
    execute(path, commit=False)
    write(game / "Assets/Fare.cs", "class Fare { int other; }\n")
    git(game, "add", "-A")
    git(game, "commit", "--quiet", "-m", "someone else's fare")
    code, out = cli(game, "worker", "finish", "T-001")
    assert code == 1 and out["status"] == "MERGE_CONFLICT" and out["conflicts"] == ["Assets/Fare.cs"]
    assert git(game, "status", "--porcelain").stdout.strip() == "", "the merge is aborted"
    assert path.is_dir() and worker_state(game)


def test_worktree_clean_removes_merged_orca_worktrees_through_orca(game, fake_orca_env):
    _, started = cli(game, "worker", "start", "T-001")
    path = game.parent / "orca/workspaces" / os.path.basename(started["path"])
    execute(path)
    git(game, "merge", "--quiet", "--no-edit", started["branch"])
    set_agent(fake_orca_env, state="done")
    code, out = cli(game, "worktree", "clean")
    assert out["status"] == "WORKTREES_REMOVED", out
    assert any(c[:2] == ["worktree", "rm"] for c in orca_state(fake_orca_env)["calls"])
    assert not path.exists() and not (game / "Logs/ludovanta/workers/T-001.json").exists()


def test_worktree_clean_keeps_a_worktree_with_a_working_agent(game, fake_orca_env):
    _, started = cli(game, "worker", "start", "T-001")
    path = game.parent / "orca/workspaces" / os.path.basename(started["path"])
    execute(path)
    git(game, "merge", "--quiet", "--no-edit", started["branch"])
    _, out = cli(game, "worktree", "clean")
    assert out["kept"][0]["reason"] == "an agent is working in it (Orca)" and path.is_dir()


# --- Tasks that need the Unity Editor: the main working copy, one at a time --------------------------------------

def editor_finished(game, tid="T-003", commit=True):
    """What an executor in the main working copy does: its files and the card in review, committed."""
    write(game / "Assets/Scene.unity", "scene\n")
    text = read(game / f"plan/tasks/{tid}.md")
    write(game / f"plan/tasks/{tid}.md", re.sub(r"status: \S+", "status: review", text, count=1))
    if commit:
        git(game, "add", "--", "Assets/Scene.unity", f"plan/tasks/{tid}.md")
        git(game, "commit", "--quiet", "-m", f"{tid}: scene")


@pytest.fixture
def orchestrator(game, fake_orca_env):
    """The orchestrator's own Claude works in the main working copy too, and keeps working."""
    state = orca_state(fake_orca_env) if fake_orca_env.is_file() else {"repos": [], "worktrees": [], "calls": []}
    state["agents"] = [{"handle": "term_me", "path": str(game).replace("\\", "/"), "agentType": "claude",
                        "paneKey": "me:me", "state": "working", "lastAssistantMessage": "I am the orchestrator",
                        "sent": []}]
    fake_orca_env.write_text(json.dumps(state), encoding="utf-8")
    return game


def test_editor_task_runs_in_the_main_working_copy_one_at_a_time(orchestrator, fake_orca_env):
    game = orchestrator
    code, out = cli(game, "worker", "start", "T-003")
    assert code == 0 and out["status"] == "WORKER_STARTED" and out["lane"] == "editor", out
    executor = agents(fake_orca_env)[-1]
    assert executor["agentType"] == "claude" and executor["title"] == "T-003 Fare meter T-003"
    assert os.path.normcase(executor["path"]) == os.path.normcase(str(game).replace("\\", "/"))
    assert "Unity MCP" in executor["sent"][0] and "plan brief T-003" in executor["sent"][0]
    assert not orca_state(fake_orca_env)["worktrees"], "no worktree for a task that needs the Editor"
    assert "status: in-progress" in read(game / "plan/tasks/T-003.md")

    code, out = cli(game, "worker", "start", "T-004")
    assert code == 1 and out["status"] == "EDITOR_BUSY" and out["busy"] == "T-003"
    code, out = cli(game, "worker", "start", "T-001")
    assert code == 0 and out["lane"] == "worktree", "tasks without the Editor still run in parallel"


def test_editor_task_is_followed_by_its_own_agent_and_finished_without_a_merge(orchestrator, fake_orca_env):
    game = orchestrator
    write(game / "Assets/Mine.cs", "// the user's work in progress\n")
    _, started = cli(game, "worker", "start", "T-003")
    editor_finished(game, commit=False)
    set_agent(fake_orca_env, handle=started["terminal"], state="done", lastAssistantMessage="What changed: the scene")
    _, out = cli(game, "worker", "list")
    w = out["workers"][0]
    assert w["state"] == "finished" and w["report"] == ["What changed: the scene"], "not the orchestrator's message"
    code, out = cli(game, "worker", "finish", "T-003")
    assert code == 0 and out["status"] == "WORKER_FINISHED", out
    assert sorted(out["committed"]) == ["Assets/Scene.unity", "plan/tasks/T-003.md"]
    assert git(game, "log", "-1", "--format=%s").stdout.strip() == "T-003: Fare meter T-003 (claude)"
    assert git(game, "status", "--porcelain").stdout.strip() == "?? Assets/Mine.cs", "the user's own file stays"
    assert [a["handle"] for a in agents(fake_orca_env)] == ["term_me"], "only the executor's terminal is closed"
    assert not (game / "Logs/ludovanta/workers/T-003.json").exists()
    assert cli(game, "worker", "start", "T-004")[1]["status"] == "WORKER_STARTED"


def test_running_editor_task_is_not_confused_with_the_working_orchestrator(orchestrator, fake_orca_env):
    game = orchestrator
    _, started = cli(game, "worker", "start", "T-003")
    state = worker_state(game, "T-003")
    state["started"] = 0
    write(game / "Logs/ludovanta/workers/T-003.json", json.dumps(state))
    set_agent(fake_orca_env, handle=started["terminal"], state="waiting", lastAssistantMessage="Which scene?")
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "stopped" and out["workers"][0]["report"] == ["Which scene?"]
    code, out = cli(game, "worker", "finish", "T-003")
    assert code == 1 and out["status"] == "NOT_FINISHED"


def test_no_merge_while_an_editor_task_works(orchestrator, fake_orca_env):
    game = orchestrator
    _, started = cli(game, "worker", "start", "T-001")
    execute(game.parent / "orca/workspaces" / os.path.basename(started["path"]))
    cli(game, "worker", "start", "T-003")
    code, out = cli(game, "worker", "finish", "T-001")
    assert code == 1 and out["status"] == "EDITOR_BUSY"


def test_agent_that_never_gets_ready_is_reported(orchestrator, fake_orca_env, monkeypatch):
    monkeypatch.setenv("FAKE_ORCA_TUI", "never")
    code, out = cli(orchestrator, "worker", "start", "T-003")
    assert code == 2 and out["status"] == "AGENT_NOT_READY"
    assert not agents(fake_orca_env)[-1]["sent"], "a prompt typed into a TUI that is not ready is lost"


def test_codex_starts_with_the_sandbox_from_ludovanta_settings(game, fake_orca_env):
    write(game / "ludovanta.local.json", '{"codex": {"sandbox": "danger-full-access", "model": "gpt-x"}}')
    code, out = cli(game, "worker", "start", "T-001", "--agent", "codex")
    assert code == 0 and out["status"] == "WORKER_STARTED", out
    create = next(c for c in orca_state(fake_orca_env)["calls"] if c[:2] == ["worktree", "create"])
    assert "--agent" not in create, "Orca's launcher cannot take Codex flags"
    agent = agents(fake_orca_env)[-1]
    assert agent["command"] == "codex --sandbox danger-full-access --model gpt-x"
    assert os.path.normcase(agent["path"]) == os.path.normcase(out["path"])
    assert "plan brief T-001" in agent["sent"][0] and "HEADLESS" in agent["sent"][0]
