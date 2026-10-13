"""The test gate: 'plan set --status review' needs a green full test run newer than the code."""
import os
import time

import pytest

from helpers import PLATFORM_DIR, read, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"
EDIT_ASMDEF = ('{"name": "Game.Tests.EditMode", "references": ["UnityEngine.TestRunner", "UnityEditor.TestRunner"], '
               '"includePlatforms": ["Editor"]}')
PLAY_ASMDEF = '{"name": "Game.Tests.PlayMode", "references": ["UnityEngine.TestRunner"], "includePlatforms": []}'


def cli(project, *args, env=None):
    return run_py(CLI, "--project", str(project), *args, env=env)


ENV = {}


@pytest.fixture
def game(make_project, fake_unity_env, tmp_path):
    p = make_project(with_git=False)
    write(p / "Assets/Tests/EditMode/Game.Tests.EditMode.asmdef", EDIT_ASMDEF)
    write(p / "Assets/Scripts/Fare.cs", "public class Fare { }")
    write(p / "plan/milestones/M1.md", "---\nid: M1\ntitle: Driving\n---\n")
    write(p / "plan/tasks/T-001.md", "---\nid: T-001\ntitle: Fare\nmilestone: M1\nstatus: in-progress\nagent: claude\n"
                                     "---\n\n- [x] The fare grows\n")
    ENV.clear()
    ENV.update(fake_unity_env, FAKE_UNITY_COUNTER=str(tmp_path / "runs.txt"))
    return p


def run_tests(game, mode, *args):
    return cli(game, "test", *args, env={**ENV, "FAKE_UNITY_MODE": mode})


def to_review(game, *args):
    return cli(game, "plan", "set", "T-001", "--status", "review", *args)


def status(game):
    return "status: review" in read(game / "plan/tasks/T-001.md")


def test_no_test_run_blocks_review(game):
    code, out = to_review(game)
    assert code == 1, out
    assert out.startswith("TESTS_NOT_GREEN: T-001 cannot go to review, its status stays 'in-progress':")
    assert "EditMode: no full test run in this working copy yet: run 'test'" in out
    assert not status(game)


def test_green_run_allows_review(game):
    assert run_tests(game, "ok")[0] == 0
    code, out = to_review(game)
    assert code == 0 and "TASK_UPDATED: T-001 status in-progress -> review" in out, out
    assert status(game)


def test_code_changed_after_the_run(game):
    run_tests(game, "ok")
    later = time.time() + 60
    os.utime(game / "Assets/Scripts/Fare.cs", (later, later))
    code, out = to_review(game)
    assert code == 1, out
    assert "EditMode: the last full run (" in out and "is older than the latest code change (Assets/Scripts/Fare.cs" in out


def test_real_failures_block(game):
    run_tests(game, "tests_fail")
    code, out = to_review(game)
    assert code == 1, out
    assert "EditMode: 1 real failure(s) in the last full run: Game.Tests.MathTests.Subtracts" in out


@pytest.mark.parametrize("mode", ["tests_flaky", "tests_quarantine"])
def test_flaky_and_quarantined_do_not_block(game, mode):
    assert run_tests(game, mode)[0] == 0
    code, out = to_review(game)
    assert code == 0, out


def test_filtered_run_does_not_count(game):
    run_tests(game, "tests_fail")
    run_tests(game, "ok", "--filter", "Game.Tests.MathTests.Subtracts")
    code, out = to_review(game)
    assert code == 1 and "1 real failure(s) in the last full run" in out, out
    run_tests(game, "ok")
    assert to_review(game)[0] == 0


def test_compile_failure_blocks(game):
    run_tests(game, "compile_error")
    code, out = to_review(game)
    assert code == 1 and "EditMode: the last full run ended with COMPILE_FAILED" in out, out


def test_playmode_tests_need_their_own_run(game):
    write(game / "Assets/Tests/PlayMode/Game.Tests.PlayMode.asmdef", PLAY_ASMDEF)
    run_tests(game, "ok")
    code, out = to_review(game)
    assert code == 1, out
    assert "PlayMode: no full test run in this working copy yet: run 'test --platform PlayMode'" in out
    assert "EditMode" not in out.split("\n", 1)[1]
    run_tests(game, "ok", "--platform", "PlayMode")
    assert to_review(game)[0] == 0


def test_unverified_is_recorded(game):
    code, out = to_review(game, "--unverified", "Editor open; ran EditMode tests through Unity MCP: 12 passed")
    assert code == 0, out
    assert "note: tests not verified by Ludovanta" in out
    card = read(game / "plan/tasks/T-001.md")
    assert "status: review" in card
    assert "review without a green test run: Editor open; ran EditMode tests through Unity MCP: 12 passed" in card


def test_review_to_done_is_not_gated_again(game):
    to_review(game, "--unverified", "sandbox")
    code, out = cli(game, "plan", "set", "T-001", "--status", "done")
    assert code == 0, out


def test_done_straight_from_in_progress_is_gated(game):
    code, out = cli(game, "plan", "set", "T-001", "--status", "done")
    assert code == 1 and "cannot go to done" in out, out


def test_projects_without_test_assemblies_pass(game):
    (game / "Assets/Tests/EditMode/Game.Tests.EditMode.asmdef").unlink()
    assert to_review(game)[0] == 0
