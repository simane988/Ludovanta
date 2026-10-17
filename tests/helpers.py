"""Plain helpers shared by the tests (fixtures live in conftest.py)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
FIXTURES = TESTS / "fixtures"
PLATFORM_DIR = REPO / "payload" / "files" / ".ludovanta"
INSTALL = REPO / "install.py"
IS_WINDOWS = os.name == "nt"
# CREATE_NO_WINDOW: pytest started without a console of its own would flash a window for every child process.
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

GIT_CONFIG = ["-c", "user.name=ludovanta-test", "-c", "user.email=ludovanta@test.local", "-c", "init.defaultBranch=main",
              "-c", "commit.gpgsign=false", "-c", "core.fsmonitor=false"]
if IS_WINDOWS:
    GIT_CONFIG += ["-c", "core.autocrlf=true"]   # the Git for Windows default


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *GIT_CONFIG, *args], cwd=cwd, capture_output=True, text=True, errors="replace",
                       creationflags=NO_WINDOW)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{p.stdout}{p.stderr}")
    return p


def run_py(script: Path, *args: str, env: dict | None = None) -> tuple[int, str]:
    """Runs a script in a separate interpreter: real exit codes, no state shared with the test process."""
    p = subprocess.run([sys.executable, "-B", str(script), *args], capture_output=True, text=True, errors="replace",
                       env={**os.environ, **(env or {})}, creationflags=NO_WINDOW)
    return p.returncode, p.stdout + p.stderr


def write(path: Path, text: str) -> None:
    """Writes text byte-exact (no newline translation)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def read(path: Path) -> str:
    """Reads text byte-exact (no newline translation)."""
    return path.read_bytes().decode("utf-8")


def lock(project: Path) -> dict:
    return json.loads(read(project / ".ludovanta" / "lock.json"))


def git_status(project: Path) -> str:
    return git(project, "status", "--porcelain").stdout.strip()
