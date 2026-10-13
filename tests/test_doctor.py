"""ludovanta.py doctor: one line per check, one next step for the first problem."""
import json

import pytest

from helpers import read, run_py, write


def doctor(project, *args, env=None):
    return run_py(project / ".ludovanta" / "ludovanta.py", "doctor", *args, env=env)


def line(out, check):
    return next((l for l in out.splitlines() if l[6:].startswith(check + " ")), "")


@pytest.fixture
def env(fake_unity_env, fake_codex_env):
    return {**fake_unity_env, **fake_codex_env}


def test_healthy_project(installed_project, env):
    code, out = doctor(installed_project, "--offline", env=env)
    assert code == 0, out
    assert out.startswith(("DOCTOR_OK", "DOCTOR_WARN")), out
    assert line(out, "python").startswith("ok")
    assert line(out, "unity").startswith("ok") and "6000.0.0f1" in line(out, "unity")
    assert "platform files intact" in line(out, "ludovanta")
    assert line(out, "skills").startswith("ok") and ".agents/skills" in line(out, "skills")
    assert line(out, "codex").startswith("ok") and "logged in" in line(out, "codex")
    assert line(out, "screenshots").startswith("ok")
    assert line(out, "rules").startswith("info") and "no '## Preferences'" in line(out, "rules")
    assert line(out, "orca").startswith("info")
    assert line(out, "unity mcp").startswith("warn")


def test_unity_missing_is_the_next_step(installed_project, env):
    code, out = doctor(installed_project, "--offline", env={**env, "UNITY_EDITOR_PATH": ""})
    assert code == 2, out
    assert out.startswith("DOCTOR_FAIL: 1 problem(s)")
    assert "Next: install Unity 6000.0.0f1 in Unity Hub" in out.splitlines()[0]
    assert line(out, "unity").startswith("FAIL")


def test_changed_platform_file_and_missing_package(installed_project, env):
    p = installed_project
    write(p / ".ludovanta/ludovanta_lib/plan.py", read(p / ".ludovanta/ludovanta_lib/plan.py") + "# hack\n")
    (p / "Packages/com.ludovanta.editor/package.json").unlink()
    code, out = doctor(p, "--offline", "--json", env=env)
    data = json.loads(out)
    assert code == 2 and data["status"] == "DOCTOR_FAIL"
    by_check = {c["check"]: c for c in data["checks"]}
    assert by_check["ludovanta"]["level"] == "warn"
    assert ".ludovanta/ludovanta_lib/plan.py" in by_check["ludovanta"]["detail"]
    assert "Packages/com.ludovanta.editor/package.json (missing)" in by_check["ludovanta"]["detail"]
    assert by_check["screenshots"]["level"] == "FAIL"
    assert data["next"]["check"] == "screenshots", "a FAIL comes before a warning"


def test_codex_not_logged_in_and_skills_hidden(installed_project, env):
    p = installed_project
    _, out = doctor(p, "--offline", env={**env, "FAKE_CODEX_MODE": "fail"})
    assert line(out, "codex").startswith("warn") and "not logged in" in line(out, "codex")
    cfg = json.loads(read(p / "ludovanta.json"))
    write(p / "ludovanta.json", json.dumps({**cfg, "skillTargets": [".claude/skills"]}))
    _, out = doctor(p, "--offline", env=env)
    assert "does not see the ludovanta-* skills" in line(out, "codex")


def test_preferences_found(installed_project, env):
    write(installed_project / "AGENTS.md", read(installed_project / "AGENTS.md") + "\n## Preferences\n\n- Russian\n")
    _, out = doctor(installed_project, "--offline", env=env)
    assert line(out, "rules").startswith("ok")


def test_newer_version_available(installed_project, env, origin):
    _, url = origin
    cfg = json.loads(read(installed_project / "ludovanta.json"))
    write(installed_project / "ludovanta.json", json.dumps({**cfg, "source": url}))
    _, out = doctor(installed_project, env=env)
    assert line(out, "updates").startswith("warn") and "v1.1.0 is available" in line(out, "updates")
    assert "update --ref v1.1.0" in out
