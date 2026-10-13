"""ludovanta.py worktree clean: worktrees of finished tasks go away once their work is merged; nothing else does."""
import json
import os
import subprocess
import sys
import time

import pytest

from helpers import IS_WINDOWS, PLATFORM_DIR, git, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"


def clean(project, *args):
    code, out = run_py(CLI, "--project", str(project), "worktree", "clean", "--json", *args)
    assert code == 0, out
    return json.loads(out)


def add_worktree(project, name, created_ago=3600):
    """A linked worktree next to the project, made (as far as git can tell) 'created_ago' seconds ago."""
    path = project.parent / name
    git(project, "worktree", "add", "--quiet", "-b", name, str(path))
    admin = project / ".git" / "worktrees" / name / "commondir"
    then = time.time() - created_ago
    os.utime(admin, (then, then))
    return path


def commit(path, file, text="x\n"):
    write(path / file, text)
    git(path, "add", "-A")
    git(path, "commit", "--quiet", "-m", f"add {file}")


def merge(project, branch):
    git(project, "merge", "--quiet", "--no-edit", branch)


def paths(items):
    return [os.path.basename(i["path"]) for i in items]


def branches(project):
    return git(project, "branch", "--format=%(refname:short)").stdout.split()


def test_merged_worktree_is_removed_with_its_branch_and_library(project):
    wt = add_worktree(project, "task-1")
    commit(wt, "Assets/Fare.cs")
    write(wt / "Library/ArtifactDB", "gigabytes")   # ignored files do not keep a worktree alive
    merge(project, "task-1")
    result = clean(project)
    assert result["status"] == "WORKTREES_REMOVED"
    assert paths(result["removed"]) == ["task-1"] and not result["kept"]
    assert not wt.exists()
    assert "task-1" not in branches(project)
    assert (project / "Assets/Fare.cs").is_file(), "the work stays in the main branch"


@pytest.mark.parametrize("case, reason", [
    ("unmerged", "not merged into main"),
    ("fresh", "nothing committed in it yet"),
    ("dirty", "uncommitted changes"),
    ("untracked", "uncommitted changes"),
    ("locked", "locked"),
])
def test_worktrees_with_something_to_lose_are_kept(project, case, reason):
    wt = add_worktree(project, "task-2", created_ago=0 if case == "fresh" else 3600)
    if case != "fresh":
        commit(wt, "Assets/Meter.cs")
    if case != "unmerged":
        merge(project, "task-2")
    if case == "dirty":
        write(wt / "Assets/Meter.cs", "changed\n")
    if case == "untracked":
        write(wt / "Assets/New.cs", "new\n")
    if case == "locked":
        git(project, "worktree", "lock", str(wt))
    result = clean(project)
    assert result["status"] == "WORKTREES_CLEAN" and not result["removed"]
    assert paths(result["kept"]) == ["task-2"] and result["kept"][0]["reason"].startswith(reason)
    assert wt.is_dir() and "task-2" in branches(project)


def test_dry_run_changes_nothing(project):
    wt = add_worktree(project, "task-3")
    commit(wt, "Assets/A.cs")
    merge(project, "task-3")
    result = clean(project, "--dry-run")
    assert result["status"] == "WORKTREES_DRY_RUN" and paths(result["removed"]) == ["task-3"]
    assert wt.is_dir() and "task-3" in branches(project)


def test_never_removes_the_worktree_it_runs_in(project):
    wt = add_worktree(project, "task-4")
    commit(wt, "Assets/B.cs")
    merge(project, "task-4")
    result = clean(wt)
    assert paths(result["kept"]) == ["task-4"] and result["kept"][0]["reason"] == "this command runs in it"
    assert wt.is_dir()


def test_deleted_folder_is_pruned(project):
    wt = add_worktree(project, "task-5")
    commit(wt, "Assets/C.cs")
    import shutil
    shutil.rmtree(wt)
    result = clean(project)
    assert result["pruned"] == 1
    assert "task-5" not in git(project, "worktree", "list").stdout


@pytest.mark.skipif(not IS_WINDOWS, reason="only Windows refuses to delete a folder another process works in")
def test_worktree_in_use_is_kept(project):
    wt = add_worktree(project, "task-6")
    commit(wt, "Assets/D.cs")
    merge(project, "task-6")
    terminal = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], cwd=wt, stdin=subprocess.PIPE)
    try:
        result = clean(project)
    finally:
        terminal.stdin.close()
        terminal.wait(10)
    assert result["kept"][0]["reason"].startswith("in use") and wt.is_dir()


# --- Hooks ---------------------------------------------------------------------------------------

def hook(project, event, payload):
    p = subprocess.run([sys.executable, "-B", str(CLI), "--project", str(project), "hook", event],
                       input=json.dumps(payload), capture_output=True, encoding="utf-8")
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def wait_gone(path, seconds=60):
    deadline = time.time() + seconds
    while path.exists() and time.time() < deadline:
        time.sleep(0.2)
    return not path.exists()


def card(project, status):
    write(project / "plan/tasks/T-001.md", f"---\nid: T-001\ntitle: Fare\nmilestone: M1\nstatus: {status}\nsize: S\n"
                                           "---\n\n- [ ] Works\n")


@pytest.fixture
def planned(project):
    write(project / "plan/goal.md", "# Такси\n")
    write(project / "plan/milestones/M1.md", "---\nid: M1\ntitle: Поездка\n---\n")
    card(project, "in-progress")
    git(project, "add", "-A")
    git(project, "commit", "--quiet", "-m", "plan")
    return project


def test_merging_a_finished_task_removes_its_worktree_after_the_reply(planned):
    hook(planned, "stop", {"session_id": "s1"})   # baseline
    wt = add_worktree(planned, "task-7")
    commit(wt, "Assets/E.cs")
    card(wt, "review")
    git(wt, "commit", "--quiet", "-am", "T-001 to review")
    merge(planned, "task-7")
    hook(planned, "stop", {"session_id": "s1"})
    assert wait_gone(wt), (planned / "Logs/ludovanta/worktree-clean.log").read_text(encoding="utf-8")
    assert "task-7" not in branches(planned)


def test_session_start_cleans_up_and_auto_clean_can_be_turned_off(planned):
    wt = add_worktree(planned, "task-8")
    commit(wt, "Assets/F.cs")
    merge(planned, "task-8")
    write(planned / "ludovanta.local.json", '{"worktrees": {"autoClean": false}}')
    hook(planned, "session-start", {"source": "startup"})
    time.sleep(3)
    assert wt.is_dir()
    os.remove(planned / "ludovanta.local.json")
    out = hook(planned, "session-start", {"source": "startup"})
    assert "LUDOVANTA PLAN BRIEF" in out
    assert wait_gone(wt), (planned / "Logs/ludovanta/worktree-clean.log").read_text(encoding="utf-8")
