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


def test_init_creates_design_template(game):
    cli(game, "init", "--title", "Фрирен")
    design = read(game / "plan/design.md")
    assert design.startswith("---\nfidelity:\n---\n") and "# Фрирен: design" in design
    assert "## Game feel" in design and "## Session walk-through" in design
    code, out = cli(game, "check")
    assert code == 0, out
    assert "graphics fidelity not chosen, ask the user (prototype, stylized, high, max, reference)" in out


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


# --- design ----------------------------------------------------------------------------------------

def test_missing_design_is_a_warning(planned):
    code, out = cli(planned, "check")
    assert code == 0, out
    assert "warning: no plan/design.md: do the design pass" in out
    assert "design: not done or fidelity not chosen - skill ludovanta-game-design" in cli(planned)[1]


def test_fidelity_shown_in_status(planned):
    write(planned / "plan/design.md", "---\nfidelity: Stylized\n---\n\n# Такси: дизайн\n")
    code, out = cli(planned, "status", "--json")
    assert code == 0, out
    assert json.loads(out)["fidelity"] == "stylized"
    assert "design: fidelity stylized" in cli(planned)[1]
    assert "design" not in cli(planned, "check")[1]


@pytest.mark.parametrize("text, expected, code", [
    ("---\nfidelity: ultra\n---\n", "unknown fidelity 'ultra'", 1),
    ("# Free text only\n", "no header", 0),
], ids=["unknown", "no-header"])
def test_design_problems(planned, text, expected, code):
    write(planned / "plan/design.md", text)
    got, out = cli(planned, "check")
    assert got == code, out
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


def test_set_in_progress_asks_to_record_the_agent(planned):
    _, out = cli(planned, "set", "T-004", "--status", "in-progress")
    assert "note: record who works on it ('plan set T-004 --agent claude|codex')" in out
    _, out = cli(planned, "set", "T-006", "--status", "in-progress")
    assert "record who works on it" not in out, "T-006 already names its agent"


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


# --- briefs ----------------------------------------------------------------------------------------

def test_session_brief(planned):
    write(planned / "plan/goal.md", "# Такси\n")
    write(planned / "plan/milestones/M1.md", "---\nid: M1\ntitle: Driving\n---\n\n## Done when\n\n- Car drives a block\n")
    write(planned / "plan/handoff.md", "# Handoff\n\nThe user wants a softer camera.\n")
    code, out = cli(planned, "brief")
    assert code == 0, out
    assert "plan: Такси | fidelity: not chosen | 40% done, 10% in review" in out
    assert "current milestone: M1 Driving (plan/milestones/M1.md)\n  - Car drives a block" in out
    assert "waiting for the user's review: T-002 Task T-002" in out
    assert "HANDOFF (plan/handoff.md" in out and "softer camera" in out


def test_task_brief_has_design_card_and_dependency_handoffs(planned):
    write(planned / "plan/design.md", "---\nfidelity: stylized\n---\n\n# Design\n\n## Game feel\n\n| Brake | squeal |\n")
    card = planned / "plan/tasks/T-001.md"
    write(card, read(card) + "\n## Handoff\n\nCarController.Brake() exists.\n\n## Log\n\n- old\n")
    code, out = cli(planned, "brief", "T-003")
    assert code == 0, out
    assert "TASK BRIEF T-003: Task T-003" in out and "fidelity: stylized" in out
    assert "=== DESIGN (plan/design.md) ===\n# Design" in out and "fidelity: stylized\n---" not in out
    assert "=== TASK CARD (plan/tasks/T-003.md) ===" in out
    assert "T-001 Task T-001 (done):\n  CarController.Brake() exists." in out and "- old" not in out
    assert "T-002 Task T-002 (review):\n  (no handoff)" in out
    assert "plan set T-003 --status review" in out


# --- closing a plan --------------------------------------------------------------------------------

def test_close_refuses_unfinished_tasks(planned):
    code, out = cli(planned, "close")
    assert code == 1, out
    assert out.startswith("PLAN_NOT_COMPLETE: 4 task(s)")
    assert (planned / "plan/tasks/T-003.md").is_file()


def test_close_archives_and_numbering_continues(game):
    write(game / "plan/goal.md", "# Вертикальный срез\n")
    write(game / "plan/design.md", "---\nfidelity: high\n---\n")
    write(game / "plan/handoff.md", "notes\n")
    milestone(game, "M1", "Driving")
    task(game, "T-001", status="done", attempts=2)
    task(game, "T-002", status="dropped")
    assert "PLAN_COMPLETE" in cli(game)[1]
    code, out = cli(game, "close")
    assert code == 0, out
    archive = game / "plan/archive/01-вертикальный-срез"
    assert out.startswith("PLAN_CLOSED: archived 2 task(s) to plan/archive/01-вертикальный-срез/")
    assert sorted(p.name for p in (archive / "tasks").iterdir()) == ["T-001.md", "T-002.md"]
    assert (archive / "milestones/M1.md").is_file() and (archive / "goal.md").is_file()
    assert (archive / "handoff.md").is_file() and not (game / "plan/handoff.md").exists()
    summary = read(archive / "SUMMARY.md")
    assert "1 done, 1 dropped" in summary and "failed attempts: 2" in summary and "## Retrospective" in summary
    assert (game / "plan/design.md").is_file(), "the design lives across plans"
    assert not list((game / "plan/tasks").iterdir())

    cli(game, "init", "--title", "Next")
    assert "# Next" in read(game / "plan/goal.md")
    assert "MILESTONE_ADDED: M2" in cli(game, "add-milestone", "--title", "More")[1]
    assert "TASK_ADDED: T-003" in cli(game, "add-task", "--milestone", "M2", "--title", "x")[1]
    code, out = cli(game, "check")
    assert code == 0 and "PLAN_OK: 1 milestone(s), 1 task(s)" in out, out


def test_close_carries_unfinished_tasks(planned):
    code, out = cli(planned, "close", "--carry")
    assert code == 0, out
    assert "archived 2 task(s)" in out and "carried 4 unfinished task(s)" in out
    archive = planned / "plan/archive/01-plan"
    assert sorted(p.name for p in (archive / "tasks").iterdir()) == ["T-001.md", "T-005.md"]
    left = sorted(p.name for p in (planned / "plan/tasks").iterdir())
    assert left == ["T-002.md", "T-003.md", "T-004.md", "T-006.md"]
    assert (planned / "plan/milestones/M1.md").is_file() and (archive / "milestones/M1.md").is_file()
    assert cli(planned, "check")[0] == 0, "dependencies on archived tasks count as met"
    _, out = cli(planned, "next", "--json")
    assert "T-003" in [t["id"] for t in json.loads(out)["tasks"]]
    assert "T-001 Task T-001 (archived):" in cli(planned, "brief", "T-003")[1]


# --- agent statistics ------------------------------------------------------------------------------

def test_stats_per_agent_with_closed_plans(game):
    milestone(game, "M1", "Driving")
    task(game, "T-001", status="done", agent="codex", size="S")
    task(game, "T-002", status="done", agent="codex", size="M", attempts=2)
    task(game, "T-003", status="done", agent="claude", size="M")
    task(game, "T-004", status="dropped", agent="claude", attempts=1)
    assert cli(game, "close")[0] == 0
    milestone(game, "M2", "Ride")
    task(game, "T-005", milestone="M2", status="done", agent="codex", size="S", attempts=3)
    task(game, "T-006", milestone="M2", status="review", agent="claude", attempts=1)
    task(game, "T-007", milestone="M2", status="done", agent="any")
    task(game, "T-008", milestone="M2", status="todo", agent="codex")

    code, out = cli(game, "stats")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == "AGENT_STATS: 5 task(s) accepted by the user in the current plan and 1 closed plan(s)"
    codex = next(line.split() for line in lines if line.startswith("codex "))
    assert codex[:7] == ["codex", "3", "1", "(33%)", "5", "1.7", "1"] and codex[-3:] == ["S:2", "M:1", "L:0"]
    claude = next(line.split() for line in lines if line.startswith("claude "))
    assert claude[:7] == ["claude", "1", "1", "(100%)", "1", "0.5", "0"]
    assert "1 finished task(s) still say agent 'any'" in out

    data = json.loads(cli(game, "stats", "--json")[1])
    assert [r["agent"] for r in data["agents"]] == ["codex", "claude", "any"]
    assert data["agents"][1] == {"agent": "claude", "done": 1, "review": 1, "firstTry": 1, "failedAttempts": 1,
                                 "stopped": 0, "sizes": {"S": 0, "M": 1, "L": 0}}


def test_stats_without_finished_tasks(game):
    milestone(game, "M1", "Driving")
    task(game, "T-001")
    code, out = cli(game, "stats")
    assert code == 0 and out.startswith("NO_STATS"), out
