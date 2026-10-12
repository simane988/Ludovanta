"""ludovanta.py plan: task cards, progress, next tasks, the task contract and the failed-attempts stop."""
import json
import os
import subprocess
import sys

import pytest

from helpers import PLATFORM_DIR, read, write

CLI = PLATFORM_DIR / "ludovanta.py"


def cli(project, *args):
    """Decodes output as UTF-8 explicitly: plan titles are often not ASCII."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    p = subprocess.run([sys.executable, "-B", str(CLI), "--project", str(project), "plan", *args],
                       capture_output=True, encoding="utf-8", errors="strict", env=env)
    return p.returncode, p.stdout + p.stderr


def milestone(project, mid, title):
    write(project / f"plan/milestones/{mid}.md", f"---\nid: {mid}\ntitle: {title}\n---\n")


def task(project, tid, milestone="M1", status="todo", size="M", agent="any", depends="", criteria=("Works",),
         attempts=0, title=None):
    body = "".join(f"- [ ] {c}\n" for c in criteria)
    write(project / f"plan/tasks/{tid}.md",
          f"---\nid: {tid}\ntitle: {title or 'Task ' + tid}\nmilestone: {milestone}\nstatus: {status}\n"
          f"agent: {agent}\nsize: {size}\ndepends: [{depends}]\nattempts: {attempts}\n---\n\n## Criteria\n{body}")


def header(project, tid):
    text = read(project / f"plan/tasks/{tid}.md").replace("\r\n", "\n")
    head = text.split("---\n")[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines())


@pytest.fixture
def game(make_project):
    return make_project(with_git=False)


@pytest.fixture
def planned(game):
    milestone(game, "M1", "Driving")
    milestone(game, "M2", "Ride")
    task(game, "T-001", status="done", size="L")
    task(game, "T-002", status="review", size="S")
    task(game, "T-003", status="todo", size="S", depends="T-001, T-002", agent="codex")
    task(game, "T-004", status="todo", milestone="M2", depends="T-003")
    task(game, "T-005", status="dropped", milestone="M2", size="L")
    task(game, "T-006", status="todo", milestone="M2", agent="claude")
    return game


# --- creating the plan ---------------------------------------------------------------------------

def test_no_plan(game):
    code, out = cli(game)
    assert code == 0, out
    assert out.startswith("NO_PLAN")


def test_init_and_add(game):
    code, out = cli(game, "init", "--title", "Вертикальный срез")
    assert code == 0, out
    assert "# Вертикальный срез" in read(game / "plan/goal.md")
    assert cli(game, "add-milestone", "--title", "Ядро вождения")[1].startswith("MILESTONE_ADDED: M1")
    assert "T-001" in cli(game, "add-task", "--milestone", "M1", "--title", "Машина едет")[1]
    code, out = cli(game, "add-task", "--milestone", "M1", "--title", "Камера", "--depends", "T-001",
                    "--agent", "Codex", "--size", "s")
    assert code == 0 and "T-002" in out, out
    assert header(game, "T-002") == {"id": "T-002", "title": "Камера", "milestone": "M1", "status": "todo",
                                     "agent": "codex", "size": "S", "depends": "[T-001]", "attempts": "0"}


def test_init_keeps_existing_files(game):
    write(game / "plan/goal.md", "# Mine\n")
    cli(game, "init", "--title", "Other")
    assert read(game / "plan/goal.md") == "# Mine\n"


@pytest.mark.parametrize("args, expected", [
    (["--milestone", "M9", "--title", "x"], "unknown milestone 'M9'"),
    (["--milestone", "M1", "--title", "x", "--depends", "T-404"], "unknown dependencies: T-404"),
    (["--milestone", "M1", "--title", "x", "--size", "XL"], "size must be S, M or L"),
])
def test_add_task_rejects(game, args, expected):
    milestone(game, "M1", "Driving")
    code, out = cli(game, "add-task", *args)
    assert code == 2, out
    assert expected in out


# --- progress ------------------------------------------------------------------------------------

def test_progress_weighted_by_size(planned):
    code, out = cli(planned, "status", "--json")
    assert code == 0, out
    data = json.loads(out)
    # live weights: T-001 L=4 done, T-002 S=1 review, T-003 S=1, T-004 M=2, T-006 M=2; T-005 dropped
    assert data["overall"]["done"] == 40 and data["overall"]["review"] == 10
    m1, m2 = data["milestones"]
    assert (m1["done"], m1["review"], m1["tasks"]) == (67, 17, 3)
    assert (m2["done"], m2["tasks"]) == (0, 2)


def test_status_text(planned):
    code, out = cli(planned)
    assert code == 0, out
    assert "overall [########++..........] 40% done (+10% in review)" in out
    assert "waiting for the user's review:\n  T-002 [any, S] Task T-002 (M1)" in out
    assert "next (ready to start):\n  T-003 [codex, S]" in out


def test_status_prints_non_ascii(game):
    write(game / "plan/goal.md", "# Такси\n")
    milestone(game, "M1", "Ядро вождения")
    task(game, "T-001", title="Машина едет")
    code, out = cli(game)
    assert code == 0, out
    assert "PLAN: Такси" in out and "Ядро вождения" in out and "Машина едет" in out


# --- next ------------------------------------------------------------------------------------------

def test_next_respects_dependencies_and_order(planned):
    code, out = cli(planned, "next", "--json")
    assert code == 0, out
    # T-003: dependencies done/in review; T-004 waits for T-003; T-006 is free but in M2.
    assert [t["id"] for t in json.loads(out)["tasks"]] == ["T-003", "T-006"]


@pytest.mark.parametrize("agent, expected", [("codex", ["T-003"]), ("claude", ["T-006"]), ("gemini", [])])
def test_next_for_agent(planned, agent, expected):
    _, out = cli(planned, "next", "--agent", agent, "--json")
    assert [t["id"] for t in json.loads(out)["tasks"]] == expected


def test_next_skips_tasks_without_criteria(game):
    milestone(game, "M1", "Driving")
    task(game, "T-001", criteria=())
    code, out = cli(game, "next")
    assert code == 0, out
    assert out.startswith("NO_READY_TASKS")


# --- check -----------------------------------------------------------------------------------------

def test_check_ok_with_warnings(planned):
    task(planned, "T-007", criteria=())
    code, out = cli(planned, "check")
    assert code == 0, out
    assert "PLAN_OK: 2 milestone(s), 7 task(s)" in out
    assert "warning: T-007: no acceptance criteria yet" in out


@pytest.mark.parametrize("setup, expected", [
    (lambda p: task(p, "T-001", milestone="M9"), "unknown milestone 'M9'"),
    (lambda p: task(p, "T-001", depends="T-404"), "depends on unknown task 'T-404'"),
    (lambda p: task(p, "T-001", status="doing"), "unknown status 'doing'"),
    (lambda p: task(p, "T-001", size="XL"), "unknown size 'XL'"),
    (lambda p: task(p, "T-001", status="in-progress", criteria=()), "status 'in-progress' but no acceptance criteria"),
    (lambda p: (task(p, "T-001", depends="T-002"), task(p, "T-002", depends="T-001")), "dependency cycle: T-001 -> T-002 -> T-001"),
    (lambda p: write(p / "plan/tasks/T-001.md", "---\nid: T-002\ntitle: x\n---\n"), "does not match the file name"),
    (lambda p: write(p / "plan/tasks/T-001.md", "id: T-001\n"), "no header"),
    (lambda p: write(p / "plan/tasks/notes.md", "x"), "unexpected file name"),
], ids=["milestone", "dependency", "status", "size", "started-without-criteria", "cycle", "id-mismatch",
        "no-header", "file-name"])
def test_check_problems(game, setup, expected):
    milestone(game, "M1", "Driving")
    setup(game)
    code, out = cli(game, "check")
    assert code == 1, out
    assert out.startswith("PLAN_INVALID")
    assert expected in out


# --- task contract -----------------------------------------------------------------------------------

def test_cannot_start_without_criteria(game):
    milestone(game, "M1", "Driving")
    task(game, "T-001", criteria=())
    before = read(game / "plan/tasks/T-001.md")
    code, out = cli(game, "set", "T-001", "--status", "in-progress")
    assert code == 1, out
    assert out.startswith("NO_CRITERIA")
    assert read(game / "plan/tasks/T-001.md") == before


def test_set_status_and_agent(planned):
    code, out = cli(planned, "set", "T-003", "--status", "in-progress", "--agent", "claude")
    assert code == 0, out
    assert header(planned, "T-003")["status"] == "in-progress"
    assert header(planned, "T-003")["agent"] == "claude"


def test_set_review_notes_unticked_criteria(planned):
    _, out = cli(planned, "set", "T-003", "--status", "review")
    assert "1 acceptance criteria are not ticked" in out


def test_set_unknown_task(planned):
    code, out = cli(planned, "set", "T-404", "--status", "done")
    assert code == 2, out
    assert "task T-404 not found" in out


def test_set_preserves_bom_crlf_and_body(game):
    milestone(game, "M1", "Driving")
    path = game / "plan/tasks/T-001.md"
    text = "﻿---\r\nid: T-001\r\ntitle: Машина\r\nmilestone: M1\r\nstatus: todo\r\n---\r\n\r\n- [x] Едет\r\n"
    write(path, text)
    code, out = cli(game, "set", "T-001", "--status", "in-progress", "--agent", "codex")
    assert code == 0, out
    assert read(path) == text.replace("status: todo", "status: in-progress").replace(
        "\r\n---\r\n\r\n", "\r\nagent: codex\r\n---\r\n\r\n")


# --- failed attempts -------------------------------------------------------------------------------

def test_fail_stops_after_three_attempts(planned):
    for attempt in (1, 2):
        code, out = cli(planned, "fail", "T-002", f"reason {attempt}")
        assert code == 0, out
        assert f"attempt {attempt} failed, {3 - attempt} attempt(s) left" in out
    assert header(planned, "T-002")["status"] == "in-progress", "a rejected review goes back to work"
    code, out = cli(planned, "fail", "T-002", "user: машина не тормозит")
    assert code == 1, out
    assert out.startswith("STOP: T-002 failed 3 attempts")
    card = read(planned / "plan/tasks/T-002.md")
    assert header(planned, "T-002")["attempts"] == "3"
    assert "## Log" in card and "attempt 3 failed: user: машина не тормозит" in card
    _, out = cli(planned)
    assert "stopped after 3 failed attempts, need the user's decision:\n  T-002" in out
    assert cli(planned, "fail", "T-002", "after the user's answer")[0] == 0, "next round of attempts"


def test_max_attempts_from_config(planned):
    write(planned / "ludovanta.json", json.dumps({"maxAttempts": 1}))
    code, out = cli(planned, "fail", "T-003", "nope")
    assert code == 1 and out.startswith("STOP"), out


def test_plan_dir_from_config(game):
    write(game / "ludovanta.json", json.dumps({"planDir": "Docs/Plan"}))
    cli(game, "init")
    assert (game / "Docs/Plan/tasks").is_dir()
