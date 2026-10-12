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
