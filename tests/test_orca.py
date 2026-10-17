"""ludovanta.py worker: executors in Orca worktrees, from start to merge (with tests/fake_orca.py as the Orca app)."""
import json
import os
import re
import time
from pathlib import Path

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


def assignment_config(game, **values):
    write(game / "ludovanta.local.json", json.dumps(values))


@pytest.mark.parametrize("pinned, override, expected, weighted", [
    ("any", None, "codex", True), ("claude", None, "claude", False),
    ("codex", "claude", "claude", False), ("any", "claude", "claude", False)])
def test_weighted_start_precedence_and_committed_cards(game, fake_orca_env, pinned, override, expected, weighted):
    assignment_config(game, agentWeights={"claude": 0, "codex": 1})
    card(game, "T-001", agent=pinned)
    if pinned != "any":
        git(game, "commit", "--quiet", "-am", "pin")
    code, out = cli(game, "worker", "start", "T-001", *(["--agent", override] if override else []))
    assert code == 0 and out["agent"] == expected, out
    for root in (game, Path(out["path"])):
        contents = read(root / "plan/tasks/T-001.md")
        assert f"agent: {expected}" in contents and "status: in-progress" in contents
        assert ("assigned: weights" in contents) == weighted
        committed = git(root, "show", "HEAD:plan/tasks/T-001.md").stdout
        assert ("assigned: weights" in committed) == weighted
    if weighted:
        assert out["shares"]["codex"] == {"work": 0, "weight": 1, "after": 1}
        assert "picked codex" in " ".join(out["notes"])
    else:
        assert out["shares"] == {}


def test_no_weights_preserves_default(game):
    code, out = cli(game, "worker", "start", "T-001")
    assert code == 0 and out["agent"] == "claude"
    assert "assigned:" not in read(game / "plan/tasks/T-001.md")


def test_successive_starts_count_the_plan_cards(game, fake_orca_env):
    assignment_config(game, agentWeights={"claude": 1, "codex": 1})
    for tid in ("T-005", "T-006"):
        card(game, tid)
    git(game, "add", "--", "plan")
    git(game, "commit", "--quiet", "-m", "more tasks")
    chosen = []
    for tid in ("T-001", "T-005", "T-006"):
        code, out = cli(game, "worker", "start", tid)
        assert code == 0, out
        chosen.append(out["agent"])
    assert chosen == ["claude", "codex", "claude"]
    assert out["shares"]["claude"]["work"] == out["shares"]["codex"]["work"] == 1


def test_invalid_weights_start_nothing(game, fake_orca_env):
    assignment_config(game, agentWeights={"claude": 1, "gemini": 1})
    before = (game / "plan/tasks/T-001.md").read_bytes()
    code, text = run_py(CLI, "--project", str(game), "worker", "start", "T-001")
    assert code == 2 and "agentWeights" in text and "gemini" in text
    assert (game / "plan/tasks/T-001.md").read_bytes() == before
    assert not orca_state(fake_orca_env)["agents"] and not orca_state(fake_orca_env)["worktrees"]
    assert not any(c[:2] in (["terminal", "create"], ["worktree", "create"])
                   for c in orca_state(fake_orca_env)["calls"])


def test_weighted_start_prints_the_pick_and_both_shares(game):
    assignment_config(game, agentWeights={"claude": 1, "codex": 1})
    code, text = run_py(CLI, "--project", str(game), "worker", "start", "T-001")
    assert code == 0, text
    assert "agentWeights picked claude" in text
    assert "claude: (0 + 1) / 1" in text and "codex: (0 + 1) / 1" in text


@pytest.mark.parametrize("pinned, missing, zero", [(False, False, False), (False, False, True),
    (False, True, True), (True, True, False), (True, False, False)])
def test_unavailable_agents(game, fake_orca_env, monkeypatch, pinned, missing, zero):
    assignment_config(game, agentWeights={"claude": 0 if zero else 1, "codex": 10})
    if pinned:
        card(game, "T-001", agent="codex")
        git(game, "commit", "--quiet", "-am", "pin")
    if missing:
        monkeypatch.setenv("CODEX_PATH", str(game / "absent"))
    monkeypatch.setenv("FAKE_CODEX_MODE", "fail")
    before = (game / "plan/tasks/T-001.md").read_bytes()
    head = git(game, "rev-parse", "HEAD").stdout
    code, out = cli(game, "worker", "start", "T-001")
    if pinned or zero:
        assert code == 2 and out["status"] == "AGENT_UNAVAILABLE", out
        assert (game / "plan/tasks/T-001.md").read_bytes() == before
        assert git(game, "rev-parse", "HEAD").stdout == head
        assert not any(c[:2] in (["terminal", "create"], ["worktree", "create"])
                       for c in orca_state(fake_orca_env)["calls"])
        if zero:
            assert "weight zero" in " ".join(out["notes"]) and "--agent claude" in " ".join(out["notes"])
    else:
        assert code == 0 and out["agent"] == "claude", out
        assert "codex login" in " ".join(out["notes"])


@pytest.mark.parametrize("unity, weights, pinned, override, expected, note", [
    ({"claude": True, "codex": False}, {"claude": 1, "codex": 2}, "any", None, "claude", "left out"),
    ({"claude": True, "codex": True}, {"claude": 1, "codex": 2}, "any", None, "codex", "picked"),
    ({"claude": False, "codex": False}, {"claude": 1, "codex": 2}, "any", None, "codex", "HEADLESS"),
    ({"claude": True, "codex": False}, {"claude": 0, "codex": 1}, "any", None, "codex", "HEADLESS"),
    ({"claude": True, "codex": False}, {"claude": 1, "codex": 1}, "codex", None, "codex", "HEADLESS"),
    ({"claude": True, "codex": False}, {"claude": 1, "codex": 1}, "any", "codex", "codex", "HEADLESS")])
def test_editor_assignment(game, unity, weights, pinned, override, expected, note):
    assignment_config(game, agentWeights=weights, unityMcp=unity)
    if pinned != "any":
        card(game, "T-003", agent=pinned, editor="true")
        git(game, "commit", "--quiet", "-am", "pin editor")
    code, out = cli(game, "worker", "start", "T-003", *(["--agent", override] if override else []))
    assert code == 0 and out["agent"] == expected, out
    assert note in " ".join(out["notes"])
    assert ("assigned: weights" in read(game / "plan/tasks/T-003.md")) == (pinned == "any" and not override)
    if note == "HEADLESS":
        assert "Editor closed" in " ".join(out["notes"])


def test_unusable_agents_unity_mcp_does_not_restrict_the_pick(game, monkeypatch):
    assignment_config(game, agentWeights={"claude": 1, "codex": 1}, unityMcp={"claude": False, "codex": True})
    monkeypatch.setenv("FAKE_CODEX_MODE", "fail")
    code, out = cli(game, "worker", "start", "T-003")
    assert code == 0 and out["agent"] == "claude", out
    assert "HEADLESS" in " ".join(out["notes"])


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


@pytest.fixture
def in_orca(orchestrator, monkeypatch):
    """The worker commands run in the orchestrator's Orca terminal (term_me)."""
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_me")
    monkeypatch.setenv("ORCA_PANE_KEY", "me:me")
    monkeypatch.setenv("ORCA_WORKTREE_ID", "repo1::" + str(orchestrator).replace("\\", "/"))
    return orchestrator


def watch(game):
    code, out = cli(game, "worker", "watch", "--rounds", "1", "--poll", "0")
    assert code == 0 and out["status"] == "WATCH_DONE", out
    return out["announced"]


def me(fake_orca_env):
    return next(a for a in agents(fake_orca_env) if a["handle"] == "term_me")


def stop_grace(game, tid):
    state = worker_state(game, tid)
    state["started"] = 0
    write(game / f"Logs/ludovanta/workers/{tid}.json", json.dumps(state))


def test_watcher_wakes_the_orchestrator_once_per_executor(in_orca, fake_orca_env):
    """'worker wait' ends with the orchestrator's turn; the executors that settle later must still reach it."""
    game = in_orca
    _, started = cli(game, "worker", "start", "T-001")
    cli(game, "worker", "start", "T-003")
    assert json.loads(read(game / "Logs/ludovanta/workers/orchestrator.json"))["terminal"] == "term_me"
    execute(game.parent / "orca/workspaces" / os.path.basename(started["path"]), commit=False)
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="done", lastAssistantMessage="Done")

    assert watch(game) == [] and not me(fake_orca_env)["sent"], "a working orchestrator is not interrupted"
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == ["T-001"]
    assert "T-001 finished" in me(fake_orca_env)["sent"][0] and "worker wait" in me(fake_orca_env)["sent"][0]
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == [], "announced once"

    stop_grace(game, "T-003")
    t003 = worker_state(game, "T-003")["terminal"]
    set_agent(fake_orca_env, handle=t003, state="waiting", lastAssistantMessage="Which scene?")
    assert watch(game) == ["T-003"] and "T-003 stopped" in me(fake_orca_env)["sent"][1]
    assert "T-001" not in me(fake_orca_env)["sent"][1]


def test_watcher_skips_what_the_orchestrator_saw_and_announces_the_next_stop(in_orca, fake_orca_env):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="Which car?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "stopped"
    assert watch(game) == [], "'worker list' already showed it"

    cli(game, "worker", "send", "T-001", "The yellow one")
    assert watch(game) == [], "it works on the answer"
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="And now?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == ["T-001"]


def test_watcher_finds_the_orchestrator_after_orca_restarts(in_orca, fake_orca_env, monkeypatch):
    game = in_orca
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_before_restart")   # same pane, new handle
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == ["T-001"] and me(fake_orca_env)["sent"]


def test_watcher_runs_once_per_project_and_exits_without_executors(in_orca, fake_orca_env):
    game = in_orca
    code, out = cli(game, "worker", "watch", "--poll", "0")
    assert code == 0 and out["status"] == "WATCH_DONE", "no executors: nothing to watch"
    cli(game, "worker", "start", "T-001")
    write(game / "Logs/ludovanta/worker-watch.lock", "another watcher")
    code, out = cli(game, "worker", "watch", "--rounds", "1", "--poll", "0")
    assert out["status"] == "WATCH_BUSY"
    assert read(game / "Logs/ludovanta/worker-watch.lock") == "another watcher"


def test_watcher_does_not_type_into_a_terminal_where_the_user_may_be_typing(in_orca, fake_orca_env):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="Which car?")
    set_agent(fake_orca_env, handle="term_me", state="idle", lastOutputAt=time.time() * 1000 - 5000)
    assert watch(game) == [] and not me(fake_orca_env)["sent"], "the line would land in the user's draft"
    set_agent(fake_orca_env, handle="term_me", lastOutputAt=time.time() * 1000 - 120_000)
    assert watch(game) == ["T-001"]


def test_wait_lists_everything_waiting_for_the_user(in_orca, fake_orca_env):
    """The first executor's question is still open when the second one asks: the user must see both, by task."""
    game = in_orca
    card(game, "T-004", status="review")   # finished earlier, waits for the user's check
    git(game, "commit", "--quiet", "-am", "T-004 in review")
    cli(game, "worker", "start", "T-001")
    cli(game, "worker", "start", "T-003")
    for tid in ("T-001", "T-003"):
        stop_grace(game, tid)
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting",
              lastAssistantMessage="I made the meter.\n\nShould the fare include tips?")
    _, out = cli(game, "worker", "wait", "T-001", "--timeout", "0")
    assert [(w["task"], w["kind"]) for w in out["waitingForUser"]] == [("T-001", "question"), ("T-004", "review")]
    assert out["waitingForUser"][0]["text"] == ["Should the fare include tips?"]

    set_agent(fake_orca_env, handle=worker_state(game, "T-003")["terminal"], state="waiting",
              lastAssistantMessage="Which scene should the taxi start in?\n\n- What changed: nothing yet")
    code, text = run_py(CLI, "--project", str(game), "worker", "wait", "--timeout", "0")
    block = text[text.index("WAITING FOR THE USER"):]
    assert "1. T-001 Fare meter T-001" in block and "Should the fare include tips?" in block
    assert "2. T-003 Fare meter T-003" in block and "Which scene should the taxi start in?" in block
    assert "What changed" not in block, "the question, not the rest of the report"
    assert "3. T-004 Fare meter T-004" in block and "accept" in block

    cli(game, "worker", "send", "T-001", "No tips")
    _, out = cli(game, "worker", "list")
    assert [w["task"] for w in out["waitingForUser"]] == ["T-003", "T-004"], "an answered question drops out"


def test_watcher_types_anyway_after_waiting_too_long(in_orca, fake_orca_env):
    """An orchestrator terminal that never looks free must not swallow the news."""
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="Which car?")
    assert watch(game) == [], "term_me is working"
    assert "its agent is not idle" in read(game / "Logs/ludovanta/worker-watch.log")
    write(game / "Logs/ludovanta/worker-watch-deferred.txt", str(time.time() - 700))
    assert watch(game) == ["T-001"] and me(fake_orca_env)["sent"]
    assert not (game / "Logs/ludovanta/worker-watch-deferred.txt").exists()


@pytest.mark.parametrize("command", ["wait", "list"])
def test_no_workers_still_lists_tasks_waiting_for_acceptance(game, command):
    card(game, "T-004", status="review")
    code, out = cli(game, "worker", command)
    assert code == 0 and out["status"] == "NO_WORKERS" and out["workers"] == []
    assert [(i["task"], i["kind"]) for i in out["waitingForUser"]] == [("T-004", "review")]
    code, text = run_py(CLI, "--project", str(game), "worker", command)
    assert code == 0 and "NO_WORKERS" in text
    assert "1. T-004 Fare meter T-004" in text[text.index("WAITING FOR THE USER"):]
    card(game, "T-004", status="done")
    _, out = cli(game, "worker", command)
    assert out["waitingForUser"] == [], "an accepted task drops out"


def test_question_comes_from_the_whole_final_message(game, fake_orca_env):
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    message = ["Should the fare include tips?", ""] + [f"Report line {n}" for n in range(58)]
    set_agent(fake_orca_env, state="waiting", lastAssistantMessage="\n".join(message))
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["report"] == message[-40:]
    assert out["waitingForUser"][0]["text"] == [message[0]]
    code, text = run_py(CLI, "--project", str(game), "worker", "list")
    report, block = text.split("WAITING FOR THE USER", 1)
    assert code == 0 and message[0] not in report and message[0] in block


@pytest.fixture
def orca_module(monkeypatch):
    monkeypatch.syspath_prepend(str(PLATFORM_DIR))
    from ludovanta_lib import orca
    return orca


@pytest.mark.parametrize("command", ["wait", "list"])
@pytest.mark.parametrize("subset", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_settled_workers_keep_the_watcher_running(in_orca, fake_orca_env, orca_module, monkeypatch,
                                                 capsys, command, subset, stale):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    if subset:
        cli(game, "worker", "start", "T-003")   # unselected executor still working
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting",
              lastAssistantMessage="Which car?")
    lock = game / "Logs/ludovanta/worker-watch.lock"
    if stale:
        write(lock, "dead watcher")
        os.utime(lock, (time.time() - 400, time.time() - 400))
    spawned = []
    monkeypatch.delenv("LUDOVANTA_NO_WATCHER")
    monkeypatch.setattr(orca_module, "spawn_detached", lambda *args: spawned.append(args))
    tasks = ["T-001"] if command == "wait" else []
    assert orca_module.wait(game, tasks, 0, 0, False) == 0
    text = capsys.readouterr().out
    assert spawned == [(game, "worker", "watch")]
    before, block = text.split("WAITING FOR THE USER", 1)
    assert "The watcher types" in before and "The watcher types" not in block
    assert text.rstrip().endswith("Which car?")
    # A live watcher is reused rather than spawned a second time.
    write(lock, "live watcher")
    spawned.clear()
    assert orca_module.wait(game, tasks, 0, 0, False) == 0
    assert spawned == []


@pytest.mark.parametrize("case", ["detached HEAD", "linked worktree"])
def test_start_requires_the_main_working_copy_on_a_branch(game, fake_orca_env, case):
    root = game
    if case == "detached HEAD":
        git(game, "checkout", "--quiet", "--detach")
        reason = "detached HEAD"
    else:
        root = game.parent / "linked"
        git(game, "worktree", "add", "--quiet", "-b", "linked", str(root))
        reason = "main working copy"
    head = git(root, "rev-parse", "HEAD").stdout
    code, out = cli(root, "worker", "start", "T-001")
    assert code == 1 and out["status"] == "NOT_STARTABLE"
    assert any(reason in p for p in out["problems"])
    assert "status: todo" in read(root / "plan/tasks/T-001.md")
    assert git(root, "rev-parse", "HEAD").stdout == head
    assert not orca_state(fake_orca_env)["worktrees"]


@pytest.mark.parametrize("case", ["folder removed", "not listed"])
def test_gone_executor(game, fake_orca_env, case):
    _, started = cli(game, "worker", "start", "T-001")
    state = orca_state(fake_orca_env)
    if case == "folder removed":
        git(game, "worktree", "remove", "--force", started["path"])
    else:
        state["worktrees"] = []
        state["agents"] = []
        fake_orca_env.write_text(json.dumps(state), encoding="utf-8")
        assert os.path.isdir(started["path"])
    _, out = cli(game, "worker", "list")
    assert out["status"] == "WORKERS_SETTLED" and out["workers"][0]["state"] == "gone"


@pytest.mark.parametrize("case", ["wrong branch", "nothing to merge"])
def test_finish_refuses_the_wrong_branch_or_an_empty_executor(game, fake_orca_env, case):
    _, started = cli(game, "worker", "start", "T-001")
    if case == "wrong branch":
        git(game, "checkout", "--quiet", "-b", "other")
    head = git(game, "rev-parse", "HEAD").stdout
    code, out = cli(game, "worker", "finish", "T-001")
    assert code == 1 and out["status"] == ("WRONG_BRANCH" if case == "wrong branch" else "NOTHING_TO_MERGE")
    assert git(game, "rev-parse", "HEAD").stdout == head
    assert os.path.isdir(started["path"]) and worker_state(game)
    assert not any(c[:2] == ["worktree", "rm"] for c in orca_state(fake_orca_env)["calls"])


def test_start_uses_the_agent_on_the_card(game, fake_orca_env):
    card(game, "T-001", agent="codex")
    git(game, "commit", "--quiet", "-am", "choose codex")
    code, out = cli(game, "worker", "start", "T-001")
    assert code == 0 and out["agent"] == "codex"
    assert agents(fake_orca_env)[0]["agentType"] == "codex"


@pytest.mark.parametrize("tid", ["T-001", "T-003"])
def test_send_finds_a_terminal_with_a_new_handle(game, fake_orca_env, tid):
    _, started = cli(game, "worker", "start", tid)
    stop_grace(game, tid)
    set_agent(fake_orca_env, state="waiting", handle=started["terminal"])
    state = orca_state(fake_orca_env)
    state["agents"][0]["handle"] = "new_handle"
    fake_orca_env.write_text(json.dumps(state), encoding="utf-8")
    code, out = cli(game, "worker", "send", tid, "The yellow car")
    assert code == 0 and out["terminal"] == "new_handle"
    assert agents(fake_orca_env)[0]["sent"][-1] == "The yellow car"
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "running"


@pytest.mark.parametrize("by_pane", [False, True])
def test_executor_commands_do_not_replace_the_orchestrator(in_orca, fake_orca_env, monkeypatch, by_pane):
    game = in_orca
    _, started = cli(game, "worker", "start", "T-003")
    path = game / "Logs/ludovanta/workers/orchestrator.json"
    before = read(path)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "new_handle" if by_pane else started["terminal"])
    monkeypatch.setenv("ORCA_PANE_KEY", started["pane"] if by_pane else "")
    cli(game, "worker", "list")
    assert read(path) == before


def test_outside_orca_says_nothing_will_wake_the_orchestrator(game):
    code, out = run_py(CLI, "--project", str(game), "worker", "start", "T-001")
    assert code == 0 and "This is not an Orca terminal" in out and "keep running 'worker wait'" in out
    assert not (game / "Logs/ludovanta/workers/orchestrator.json").exists()


def test_watcher_announces_two_executors_in_one_line(in_orca, fake_orca_env):
    game = in_orca
    for tid in ("T-001", "T-003"):
        _, started = cli(game, "worker", "start", tid)
        stop_grace(game, tid)
        set_agent(fake_orca_env, handle=started["terminal"], state="waiting", lastAssistantMessage="Which car?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == ["T-001", "T-003"]
    sent = me(fake_orca_env)["sent"]
    assert len(sent) == 1 and "T-001 stopped" in sent[0] and "T-003 stopped" in sent[0]
    assert "\n" not in sent[0]


def test_watcher_counts_other_executors_still_working(in_orca, fake_orca_env):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    cli(game, "worker", "start", "T-003")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="Which car?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    assert watch(game) == ["T-001"]
    assert "1 other executor(s) keep working." in me(fake_orca_env)["sent"][0]


def test_failed_watcher_round_is_logged_and_the_next_round_runs(in_orca, fake_orca_env, orca_module, monkeypatch):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, handle="term_t-001-fare-meter-t-001", state="waiting", lastAssistantMessage="Which car?")
    set_agent(fake_orca_env, handle="term_me", state="idle")
    original = orca_module.orca
    attempts = []

    def fail_once(exe, *args, **kwargs):
        if args[:2] == ("worktree", "ps"):
            attempts.append(args)
            if len(attempts) == 1:
                raise orca_module.LudovantaError("test Orca round failure")
        return original(exe, *args, **kwargs)

    monkeypatch.setattr(orca_module, "orca", fail_once)
    assert orca_module.watch(game, 2, 0, False) == 0
    assert len(attempts) == 2 and len(me(fake_orca_env)["sent"]) == 1
    log = read(game / "Logs/ludovanta/worker-watch.log")
    assert "round failed: LudovantaError: test Orca round failure" in log
    assert "woke the orchestrator" in log and "exited: 2 round(s) done" in log


@pytest.mark.parametrize("with_executor", [False, True])
def test_nothing_open_has_no_waiting_block(game, with_executor):
    if with_executor:
        cli(game, "worker", "start", "T-001")
    for command in ("wait", "list"):
        args = ["--timeout", "0"] if command == "wait" else []
        code, text = run_py(CLI, "--project", str(game), "worker", command, *args)
        assert code == 0 and "WAITING FOR THE USER" not in text


def test_blocked_executor_is_in_the_waiting_block(game, fake_orca_env):
    _, started = cli(game, "worker", "start", "T-001")
    path = game.parent / "orca/workspaces" / os.path.basename(started["path"])
    card(path, "T-001", status="blocked")
    set_agent(fake_orca_env, state="waiting", lastAssistantMessage="Which car should I use?")
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "blocked", "blocked bypasses the start grace period"
    assert out["waitingForUser"][0]["task"] == "T-001" and out["waitingForUser"][0]["kind"] == "question"
    code, text = run_py(CLI, "--project", str(game), "worker", "list")
    assert code == 0 and "BLOCKED" in text
    block = text[text.index("WAITING FOR THE USER"):]
    assert "1. T-001 Fare meter T-001" in block and "Which car should I use?" in block


@pytest.mark.parametrize("approval", ["untrusted", "on-failure", "on-request", "never"])
@pytest.mark.parametrize("extra", [{}, {"sandbox": "danger-full-access", "model": "gpt-x"}])
def test_codex_approval(game, fake_orca_env, approval, extra):
    assignment_config(game, codex={"approval": approval, **extra})
    code, out = cli(game, "worker", "start", "T-001", "--agent", "codex")
    assert code == 0, out
    agent = agents(fake_orca_env)[-1]
    assert agent["command"].endswith(f"--ask-for-approval {approval}")
    assert "plan brief T-001" in agent["sent"][0]


@pytest.mark.parametrize("approval", ["always", "", None, False, []])
def test_invalid_approval_does_not_commit_or_start(game, fake_orca_env, approval):
    assignment_config(game, codex={"approval": approval})
    head = git(game, "rev-parse", "HEAD").stdout
    before = read(game / "plan/tasks/T-001.md")
    code, text = run_py(CLI, "--project", str(game), "worker", "start", "T-001", "--agent", "codex")
    assert code == 2 and "codex.approval" in text
    assert all(value in text for value in ("untrusted", "on-failure", "on-request", "never"))
    assert git(game, "rev-parse", "HEAD").stdout == head
    assert read(game / "plan/tasks/T-001.md") == before
    assert not agents(fake_orca_env) and not orca_state(fake_orca_env)["worktrees"]


@pytest.mark.parametrize("tid", ["T-001", "T-003"])
@pytest.mark.parametrize("screen, expected", [("Trust this folder?", "Trust this folder?"),
    ("Set up the Windows sandbox", "set up its sandbox"), ("Loading", "did not get ready")])
def test_not_ready_screen_and_resend(game, fake_orca_env, monkeypatch, orca_module, tid, screen, expected):
    assignment_config(game, codex={"approval": "never"})
    monkeypatch.setenv("FAKE_ORCA_TUI", "never")
    monkeypatch.setenv("FAKE_ORCA_SCREEN", screen)
    code, text = run_py(CLI, "--project", str(game), "worker", "start", tid, "--agent", "codex")
    assert code == 2 and "AGENT_NOT_READY" in text and expected in text
    assert "user" in text and "in Orca" in text and f"worker send {tid}" in text
    assert not agents(fake_orca_env)[-1]["sent"]
    monkeypatch.delenv("FAKE_ORCA_TUI")
    code, out = cli(game, "worker", "send", tid)
    assert code == 0, out
    lane = "editor" if tid == "T-003" else "worktree"
    assert agents(fake_orca_env)[-1]["sent"] == [orca_module._prompt(tid, lane)]
    _, out = cli(game, "worker", "list")
    assert out["workers"][0]["state"] == "running"


@pytest.mark.parametrize("submitted", [True, False])
def test_watcher_submission_receipt(in_orca, fake_orca_env, submitted):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, state="waiting")
    set_agent(fake_orca_env, handle="term_me", state="idle", submitted=submitted)
    assert watch(game) == ["T-001"]
    call = [c for c in orca_state(fake_orca_env)["calls"] if c[:2] == ["terminal", "send"]][-1]
    assert "--wait-submit" in call
    log = read(game / "Logs/ludovanta/worker-watch.log")
    assert ("woke the orchestrator" in log) == submitted
    assert ("typed but not confirmed as submitted" in log) == (not submitted)
    assert watch(game) == [], "accepted input must not be typed twice"


def test_watcher_dialog_waits_for_thirty_minutes(in_orca, fake_orca_env, orca_module, monkeypatch):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    stop_grace(game, "T-001")
    set_agent(fake_orca_env, state="waiting")
    set_agent(fake_orca_env, handle="term_me", state="idle", dialog=True)
    exe = orca_module.find_orca(game)
    now = time.time()
    for seconds in range(0, 1801, 15):
        monkeypatch.setattr(orca_module.time, "time", lambda: now + seconds)
        assert orca_module._watch_round(game, exe) == []
    assert not me(fake_orca_env)["sent"]
    assert not worker_state(game).get("notified")
    log = read(game / "Logs/ludovanta/worker-watch.log")
    assert log.count("open dialog") == 7 and "round failed" not in log
    assert "typing the line anyway" not in log
    set_agent(fake_orca_env, handle="term_me", dialog=False)
    assert orca_module._watch_round(game, exe) == ["T-001"]


def test_watcher_same_failure_twelve_minutes(in_orca, orca_module, monkeypatch):
    game = in_orca
    cli(game, "worker", "start", "T-001")
    now = time.time()
    ticks = [now]
    attempts = []
    def fail_round(*args):
        attempts.append(1)
        raise orca_module.LudovantaError("repeated failure")
    monkeypatch.setattr(orca_module, "_watch_round", fail_round)
    monkeypatch.setattr(orca_module.time, "time", lambda: ticks[0])
    monkeypatch.setattr(orca_module.time, "sleep", lambda seconds: ticks.__setitem__(0, ticks[0] + 15))
    assert orca_module.watch(game, 49, 0, False) == 0
    assert len(attempts) == 49
    assert read(game / "Logs/ludovanta/worker-watch.log").count("round failed: LudovantaError: repeated failure") == 3
