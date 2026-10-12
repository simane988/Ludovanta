from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # importing ludovanta_lib must not leave __pycache__ inside payload/

import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import INSTALL, IS_WINDOWS, REPO, TESTS, git, run_py, write


@pytest.fixture
def make_project(tmp_path):
    """Factory for a minimal Unity project (optionally a git repo with one commit)."""
    def make(name: str = "game", unity_version: str = "6000.0.0f1", with_git: bool = True) -> Path:
        p = tmp_path / name
        write(p / "ProjectSettings/ProjectVersion.txt",
              f"m_EditorVersion: {unity_version}\nm_EditorVersionWithRevision: {unity_version} (abc)\n")
        write(p / "Packages/manifest.json", '{\n  "dependencies": {}\n}\n')
        (p / "Assets").mkdir()
        write(p / ".gitignore", "/[Ll]ibrary/\r\n/[Tt]emp/\r\n/[Ll]ogs/\r\n")
        write(p / "AGENTS.md", "# My game\n\nUser rules for agents.\n")
        write(p / ".claude/skills/my-skill/SKILL.md", "---\nname: my-skill\ndescription: user skill\n---\nmine\n")
        if with_git:
            git(p, "init", "--quiet")
            git(p, "add", "-A")
            git(p, "commit", "--quiet", "-m", "initial")
        return p
    return make


@pytest.fixture
def project(make_project) -> Path:
    return make_project()


@pytest.fixture
def installed_project(make_project) -> Path:
    """Project with Ludovanta installed from this repo and committed."""
    p = make_project()
    code, out = run_py(INSTALL, "--project", str(p), "--source", "https://example.com/ludovanta.git", "--ref", "v0.1.0")
    assert code == 0, out
    git(p, "add", "-A")
    git(p, "commit", "--quiet", "-m", "install ludovanta")
    return p


@pytest.fixture
def copy_platform(tmp_path):
    """Factory for a copy of this platform repo that a test can modify (a 'new version')."""
    def copy(name: str) -> Path:
        dst = tmp_path / name
        dst.mkdir()
        for item in ("install.py", "VERSION", ".gitattributes"):
            shutil.copy2(REPO / item, dst / item)
        shutil.copytree(REPO / "payload", dst / "payload", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return dst
    return copy


@pytest.fixture
def origin(copy_platform) -> tuple[Path, str]:
    """Platform git repo with tags v1.0.0 and v1.1.0 (1.1.0 adds .ludovanta/NEW.md). Returns (path, file:// URL)."""
    repo = copy_platform("platform-origin")
    write(repo / "VERSION", "1.0.0\n")
    git(repo, "init", "--quiet")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "v1.0.0")
    git(repo, "tag", "v1.0.0")
    write(repo / "VERSION", "1.1.0\n")
    write(repo / "payload/files/.ludovanta/NEW.md", "added in 1.1.0\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "v1.1.0")
    git(repo, "tag", "v1.1.0")
    return repo, repo.as_uri()


@pytest.fixture
def fake_unity_env(tmp_path) -> dict:
    """Env that points Ludovanta at tests/fake_unity.py instead of a real Unity (mode via FAKE_UNITY_MODE)."""
    script = TESTS / "fake_unity.py"
    if IS_WINDOWS:
        launcher = tmp_path / "fake_unity.cmd"
        write(launcher, f'@"{sys.executable}" -B "{script}" %*\r\n')
    else:
        launcher = tmp_path / "fake_unity.sh"
        write(launcher, f'#!/bin/sh\nexec "{sys.executable}" -B "{script}" "$@"\n')
        launcher.chmod(0o755)
    return {"UNITY_EDITOR_PATH": str(launcher)}


_HOLDER = r"""
import os, sys
f = open(sys.argv[1], "a")
if os.name != "nt":
    import fcntl
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)   # what Unity does on macOS/Linux
print("ready", flush=True)                   # on Windows any open handle blocks an exclusive open
sys.stdin.read()
f.close()
"""


@pytest.fixture
def held_lockfile(project):
    """Another process holds Temp/UnityLockfile, like a running Unity Editor."""
    lockfile = project / "Temp" / "UnityLockfile"
    write(lockfile, "")
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(lockfile)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    yield lockfile
    proc.stdin.close()
    proc.wait(10)
    proc.stdout.close()
