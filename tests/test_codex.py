"""ludovanta.py codex: tasks and reference images through the Codex CLI (tests/fake_codex.py stands in for it)."""
import json

import pytest

from helpers import PLATFORM_DIR, read, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"


def cli(project, *args, env=None):
    return run_py(CLI, "--project", str(project), *args, env=env)


@pytest.fixture
def game(make_project):
    p = make_project(with_git=False)
    write(p / "plan/milestones/M1.md", "---\nid: M1\ntitle: Driving\n---\n")
    write(p / "plan/tasks/T-001.md", "---\nid: T-001\ntitle: Fare meter\nmilestone: M1\nstatus: todo\nagent: codex\n"
                                     "size: S\n---\n\n- [ ] Fare grows with distance\n")
    write(p / "plan/tasks/T-002.md", "---\nid: T-002\ntitle: Empty\nmilestone: M1\nstatus: todo\n---\n")
    return p


def test_not_installed(game):
    code, out = cli(game, "codex", "run", "T-001", env={"CODEX_PATH": str(game / "nope")})
    assert code == 2, out
    assert out.startswith("CODEX_NOT_FOUND")
    _, out = cli(game, "status", env={"CODEX_PATH": str(game / "nope")})
    assert "codex cli: not found" in out
    assert "codex skills" not in out


def test_status_warns_when_codex_cannot_see_the_skills(game, fake_codex_env):
    _, out = cli(game, "status", env=fake_codex_env)
    assert "codex cli: " in out and "codex skills" not in out, "default skill targets include .agents/skills"
    write(game / "ludovanta.json", json.dumps({"skillTargets": [".claude/skills"]}))
    _, out = cli(game, "status", env=fake_codex_env)
    assert "codex skills: Codex does not see the ludovanta-* skills" in out


def test_run_task(game, fake_codex_env):
    code, out = cli(game, "codex", "run", "T-001", env=fake_codex_env)
    assert code == 0, out
    assert out.startswith("CODEX_DONE: T-001") and "task status now 'review'" in out
    assert "T-001 done by fake codex" in out and "agent rule seen: True" in out
    assert "Now verify it yourself" in out
    [prompt] = (game / "Logs/ludovanta/codex").glob("T-001-*-prompt.md")
    assert "TASK BRIEF T-001: Fare meter" in read(prompt) and "EXECUTOR RULES" in read(prompt)
    [log] = (game / "Logs/ludovanta/codex").glob("T-001-*-run.log")
    assert "exec | --cd | " in read(log) and "--sandbox | workspace-write" in read(log)


def test_run_task_settings_from_config(game, fake_codex_env):
    write(game / "ludovanta.json", json.dumps({"codex": {"model": "gpt-5.5-codex", "sandbox": "danger-full-access"}}))
    code, out = cli(game, "codex", "run", "T-001", "--json", env=fake_codex_env)
    assert code == 0, out
    log = read(game / json.loads(out)["log"])
    assert "--model | gpt-5.5-codex" in log and "--sandbox | danger-full-access" in log


def test_task_without_criteria_is_refused(game, fake_codex_env):
    code, out = cli(game, "codex", "run", "T-002", env=fake_codex_env)
    assert code == 1 and out.startswith("NO_CRITERIA"), out


def test_codex_failure(game, fake_codex_env):
    code, out = cli(game, "codex", "run", "T-001", env={**fake_codex_env, "FAKE_CODEX_MODE": "fail"})
    assert code == 2, out
    assert out.startswith("CODEX_FAILED: exit code 1") and "not logged in" in out


def test_image(game, fake_codex_env):
    code, out = cli(game, "codex", "image", "Frieren in a meadow, anime watercolor", "--out",
                    "Art/References/meadow.png", env={**fake_codex_env, "FAKE_CODEX_MODE": "image"})
    assert code == 0, out
    assert out.startswith("IMAGE_CREATED: Art/References/meadow.png")
    assert (game / "Art/References/meadow.png").read_bytes().startswith(b"\x89PNG")
    [prompt] = (game / "Logs/ludovanta/codex").glob("image-*-prompt.md")
    assert "$imagegen" in read(prompt) and "anime watercolor" in read(prompt)


def test_image_not_created(game, fake_codex_env):
    code, out = cli(game, "codex", "image", "x", "--out", "Art/x.png", env={**fake_codex_env, "FAKE_CODEX_MODE": "silent"})
    assert code == 1, out
    assert out.startswith("IMAGE_NOT_CREATED: Art/x.png")


def test_image_outside_project_is_refused(game, fake_codex_env):
    code, out = cli(game, "codex", "image", "x", "--out", "../x.png", env=fake_codex_env)
    assert code == 2 and "inside the project" in out, out
