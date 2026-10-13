"""Test gate: a task goes to review only when the last full test run is green and newer than the code.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

'test' records every full run (no --filter, no --category) per platform in Logs/ludovanta/test-state.json, which is
per working copy like the rest of Logs/. 'plan set --status review' asks problems() whether each platform that has
test assemblies had a full run that started after the latest code change and ended without real failures (flaky and
quarantined tests do not count). Projects without test assemblies pass.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .common import read_text, relpath

STATE_REL = "Logs/ludovanta/test-state.json"
CODE_SUFFIXES = (".cs", ".asmdef", ".asmref")
GREEN = ("TESTS_PASSED", "TESTS_FLAKY", "NO_TESTS")
TEST_REFERENCES = ("UnityEngine.TestRunner", "UnityEditor.TestRunner")


def _load(root: Path) -> dict:
    try:
        data = json.loads(read_text(root / STATE_REL))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(root: Path, platform: str, started: float, status: str, failures: list[str]) -> None:
    """Called by 'test' after a full run."""
    path = root / STATE_REL
    data = _load(root)
    data[platform] = {"started": started, "status": status, "failures": failures}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _test_platform(asmdef: Path) -> str | None:
    try:
        data = json.loads(read_text(asmdef))
    except (OSError, ValueError):
        return None
    refs = [str(r) for r in data.get("references") or []]
    is_test = (any(r in TEST_REFERENCES for r in refs)
               or "TestAssemblies" in (data.get("optionalUnityReferences") or [])
               or "nunit.framework.dll" in (data.get("precompiledReferences") or []))
    if not is_test:
        return None
    return "EditMode" if data.get("includePlatforms") == ["Editor"] else "PlayMode"


def scan(root: Path) -> tuple[set[str], tuple[float, str] | None]:
    """Test platforms present (by test .asmdef files) and the newest code change (mtime, path)."""
    platforms: set[str] = set()
    newest: tuple[float, str] | None = None
    candidates = [root / "Packages" / "manifest.json"]
    for dirpath, dirnames, filenames in os.walk(root / "Assets"):
        dirnames[:] = [d for d in dirnames if not (d.startswith(".") or d.endswith("~"))]
        for name in filenames:
            if name.endswith(CODE_SUFFIXES):
                candidates.append(Path(dirpath) / name)
                if name.endswith(".asmdef"):
                    platform = _test_platform(Path(dirpath) / name)
                    if platform:
                        platforms.add(platform)
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest[0]:
            newest = (mtime, relpath(root, path))
    return platforms, newest


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def problems(root: Path) -> list[str]:
    platforms, newest = scan(root)
    state = _load(root)
    out = []
    for platform in sorted(platforms):
        cmd = "test" if platform == "EditMode" else "test --platform PlayMode"
        run = state.get(platform)
        if not isinstance(run, dict) or "started" not in run:
            out.append(f"{platform}: no full test run in this working copy yet: run '{cmd}'")
        elif newest and newest[0] > float(run["started"]):
            out.append(f"{platform}: the last full run ({_when(run['started'])}) is older than the latest code change "
                       f"({newest[1]}, {_when(newest[0])}): run '{cmd}'")
        elif run.get("status") not in GREEN:
            failures = run.get("failures") or []
            if failures:
                out.append(f"{platform}: {len(failures)} real failure(s) in the last full run: "
                           + ", ".join(failures[:5]) + (" ..." if len(failures) > 5 else ""))
            else:
                out.append(f"{platform}: the last full run ended with {run.get('status')}: fix it and run '{cmd}'")
    return out
