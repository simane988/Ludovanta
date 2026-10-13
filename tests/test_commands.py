"""ludovanta.py commands end to end, with tests/fake_unity.py instead of a real Unity."""
import json

import pytest

from helpers import PLATFORM_DIR, run_py, write
from ludovanta_lib import common

CLI = PLATFORM_DIR / "ludovanta.py"
GUID = "0123456789abcdef0123456789abcdef"


def cli(project, *args, env=None):
    return run_py(CLI, "--project", str(project), *args, env=env)


# --- validate-assets --------------------------------------------------------------------

@pytest.fixture
def broken_assets(make_project):
    p = make_project(with_git=False)
    write(p / "Assets/A.cs", "class A {}")
    write(p / "Assets/A.cs.meta", f"fileFormatVersion: 2\nguid: {GUID}\n")
    write(p / "Assets/B.cs", "class B {}")
    write(p / "Assets/Old.cs.meta", "fileFormatVersion: 2\nguid: fedcba9876543210fedcba9876543210\n")
    write(p / "Assets/C.prefab", "prefab")
    write(p / "Assets/C.prefab.meta", f"fileFormatVersion: 2\nguid: {GUID}\n")
    write(p / "Assets/NoGuid.asset", "x")
    write(p / "Assets/NoGuid.asset.meta", "fileFormatVersion: 2\n")
    write(p / "Assets/Samples~/x.txt", "ignored")
    write(p / "Assets/.hidden", "ignored")
    write(p / "Assets/temp.tmp", "ignored")
    (p / "Assets/Folder").mkdir()
    return p


@pytest.mark.parametrize("expected", [
    "missing meta: Assets/B.cs",
    "missing meta: Assets/Folder/",
    "orphan meta: Assets/Old.cs.meta",
    "meta without guid: Assets/NoGuid.asset.meta",
    f"duplicate guid {GUID}: Assets/A.cs.meta, Assets/C.prefab.meta",
])
def test_validate_assets_reports(broken_assets, expected):
    code, out = cli(broken_assets, "validate-assets")
    assert code == 1, out
    assert expected in out


@pytest.mark.parametrize("ignored", ["Samples~", ".hidden", "temp.tmp"])
def test_validate_assets_skips_unity_ignored_names(broken_assets, ignored):
    _, out = cli(broken_assets, "validate-assets")
    assert ignored not in out


def test_validate_assets_ok(make_project):
    p = make_project(with_git=False)
    write(p / "Assets/A.cs", "class A {}")
    write(p / "Assets/A.cs.meta", f"fileFormatVersion: 2\nguid: {GUID}\n")
    code, out = cli(p, "validate-assets", "--json")
    assert code == 0, out
    assert json.loads(out)["status"] == "ASSETS_OK"


# --- compile / test / status with a fake Unity ----------------------------------------------

@pytest.mark.parametrize("mode, args, exit_code, expected", [
    ("ok", ["compile"], 0, "COMPILE_OK: 0 errors"),
    ("compile_error", ["compile"], 1, "COMPILE_FAILED: 2 error(s), 1 warning(s)"),
    ("compile_error", ["compile"], 1, "Assets/Scripts/Player.cs:12:17 CS0103"),
    ("license", ["compile"], 2, "reason: Unity license problem"),
    ("ok", ["test"], 0, "TESTS_PASSED (EditMode): 0 failed, 2 passed"),
    ("tests_fail", ["test", "--platform", "editmode"], 1, "TESTS_FAILED (EditMode): 1 failed, 1 passed"),
    ("tests_fail", ["test"], 1, "- Game.Tests.MathTests.Subtracts\n    Expected: 1\n    But was:  2"),
    ("compile_error", ["test"], 1, "COMPILE_FAILED: tests did not run"),
    ("license", ["test"], 2, "UNITY_FAILED: no test results produced"),
], ids=["compile-ok", "compile-errors-summary", "compile-errors-location", "compile-license",
        "test-passed", "test-failed-summary", "test-failed-details", "test-compile-errors", "test-license"])
def test_unity_commands(project, fake_unity_env, mode, args, exit_code, expected):
    code, out = cli(project, *args, env={**fake_unity_env, "FAKE_UNITY_MODE": mode})
    assert code == exit_code, out
    assert expected in out


def test_test_command_passes_filter_and_platform(project, fake_unity_env):
    code, out = cli(project, "test", "--platform", "playmode", "--filter", "Game.Tests", "--json",
                    env={**fake_unity_env, "FAKE_UNITY_MODE": "ok"})
    assert code == 0, out
    data = json.loads(out)
    log = (project / data["log"]).read_text(encoding="utf-8")
    assert data["platform"] == "PlayMode"
    assert "-testPlatform PlayMode" in log and "-testFilter Game.Tests" in log
    assert "-nographics" not in log, "PlayMode needs graphics"


# --- flaky tests: rerun, quarantine, repeat ------------------------------------------------------

def _test_runs(project):
    return sorted((project / "Logs/ludovanta").glob("test-editmode-*.log"))


@pytest.fixture
def flaky_env(fake_unity_env, tmp_path):
    return {**fake_unity_env, "FAKE_UNITY_MODE": "tests_flaky", "FAKE_UNITY_COUNTER": str(tmp_path / "runs.txt")}


def test_real_failure_fails_again_on_rerun(project, fake_unity_env):
    code, out = cli(project, "test", env={**fake_unity_env, "FAKE_UNITY_MODE": "tests_fail"})
    assert code == 1, out
    assert out.startswith("TESTS_FAILED (EditMode)") and "1 of the failure(s) above failed again on a rerun: they are real" in out
    runs = _test_runs(project)
    assert len(runs) == 2
    assert r"-testFilter Game\.Tests\.MathTests\.Subtracts$" in runs[1].read_text(encoding="utf-8")


def test_flaky_failure_passes_on_rerun(project, flaky_env):
    code, out = cli(project, "test", "--json", env=flaky_env)
    assert code == 0, out
    data = json.loads(out)
    assert data["status"] == "TESTS_FLAKY" and data["flaky"] == ["Game.Tests.MathTests.Subtracts"]
    assert data["failures"] == []
    code, out = cli(project, "test", env=flaky_env)   # run 3 fails, run 4 (the rerun) passes
    assert code == 0 and out.startswith("TESTS_FLAKY (EditMode)"), out
    assert 'Quarantine each with [Category("Flaky")]' in out and "  Game.Tests.MathTests.Subtracts" in out


def test_no_rerun(project, flaky_env):
    code, out = cli(project, "test", "--no-rerun", env=flaky_env)
    assert code == 1 and out.startswith("TESTS_FAILED"), out
    assert len(_test_runs(project)) == 1


def test_quarantined_failures_do_not_fail_the_run(project, fake_unity_env):
    code, out = cli(project, "test", env={**fake_unity_env, "FAKE_UNITY_MODE": "tests_quarantine"})
    assert code == 0, out
    assert out.startswith("TESTS_PASSED (EditMode): 1 failed, 2 passed")
    assert "quarantine: 2 test(s) in category 'Flaky', 1 failed this run" in out
    assert "Game.Tests.MathTests.Subtracts - failed" in out and "  Game.Tests.TimerTests.Ticks\n" in out + "\n"
    assert len(_test_runs(project)) == 1, "quarantined failures are not rerun"


@pytest.mark.parametrize("mode, repeat, exit_code, expected", [
    ("tests_flaky", "4", 1, ["TESTS_FLAKY (EditMode): 2 test(s) run 4 times", "1 flaky, 0 always failing",
                             "- Game.Tests.MathTests.Subtracts: failed 2 of 4"]),
    ("tests_fail", "2", 1, ["TESTS_FAILED (EditMode)", "always failing (a real failure",
                            "- Game.Tests.MathTests.Subtracts: failed 2 of 2"]),
    ("tests_quarantine", "3", 0, ["TESTS_STABLE (EditMode): 3 test(s) run 3 times", "failed 3 of 3 (quarantined)",
                                  "quarantined but passed all 3 runs", "  Game.Tests.TimerTests.Ticks"]),
    ("ok", "2", 0, ["TESTS_STABLE (EditMode): 2 test(s) run 2 times in", "0 flaky, 0 always failing"]),
    ("compile_error", "3", 1, ["COMPILE_FAILED: tests did not run"]),
])
def test_repeat(project, flaky_env, mode, repeat, exit_code, expected):
    code, out = cli(project, "test", "--repeat", repeat, env={**flaky_env, "FAKE_UNITY_MODE": mode})
    assert code == exit_code, out
    for line in expected:
        assert line in out
    assert len(_test_runs(project)) == (1 if mode == "compile_error" else int(repeat))


def test_status_headless(project, fake_unity_env):
    code, out = cli(project, "status", env=fake_unity_env)
    assert code == 0, out
    assert "MODE: HEADLESS" in out
    assert f"unity editor: {fake_unity_env['UNITY_EDITOR_PATH']}" in out


def test_unity_not_found(project):
    code, out = cli(project, "compile", env={"UNITY_EDITOR_PATH": ""})
    assert code == 2, out
    assert "LUDOVANTA_ERROR: Unity 6000.0.0f1 not found" in out


def test_unity_path_from_local_config(project, fake_unity_env):
    write(project / "ludovanta.local.json", json.dumps({"unityEditorPath": fake_unity_env["UNITY_EDITOR_PATH"]}))
    code, out = cli(project, "compile", env={"UNITY_EDITOR_PATH": "", "FAKE_UNITY_MODE": "ok"})
    assert code == 0, out


# --- live mode detection --------------------------------------------------------------------

def test_editor_open(project, fake_unity_env, held_lockfile):
    assert common.editor_open(project)
    code, out = cli(project, "compile", env=fake_unity_env)
    assert code == 3, out
    assert "EDITOR_OPEN" in out
    _, out = cli(project, "status", env=fake_unity_env)
    assert "MODE: LIVE" in out


def test_stale_lockfile_is_not_open(project):
    write(project / "Temp/UnityLockfile", "")
    assert not common.editor_open(project)


def test_no_lockfile_is_not_open(project):
    assert not common.editor_open(project)


# --- project lookup ---------------------------------------------------------------------------

def test_project_root_from_nested_folder(project):
    nested = project / "Assets" / "Deep"
    nested.mkdir()
    assert common.find_project_root(nested) == project


def test_project_root_missing(tmp_path):
    with pytest.raises(common.LudovantaError, match="Unity project root not found"):
        common.find_project_root(tmp_path)
