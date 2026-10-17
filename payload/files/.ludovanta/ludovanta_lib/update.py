"""Update Ludovanta in this project to the ref pinned in ludovanta.json, or to --ref.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Fetches the platform from 'source' in ludovanta.json (git URL, or a local folder for platform development)
and runs the installer of the fetched version, so the new version decides how to migrate the project.
Self-contained on purpose (standard library only, no other ludovanta_lib imports): it must keep working even
if other .ludovanta files are broken, for example by merge conflicts.
Exit codes: 0 updated, 1 locally modified platform files (nothing written), 2 error.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def _git(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True, errors="replace",
                           creationflags=0x08000000 if os.name == "nt" else 0)   # CREATE_NO_WINDOW
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def _rmtree(path: str) -> None:
    def make_writable_and_retry(func, target, *_):
        os.chmod(target, stat.S_IWRITE)   # git pack files are read-only on Windows
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


def update(root: Path, ref: str | None, source: str | None, force: bool, dry_run: bool) -> int:
    cfg_path = root / "ludovanta.json"
    if not cfg_path.is_file():
        print(f"LUDOVANTA_ERROR: ludovanta.json not found in {root}")
        return 2
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        print(f"LUDOVANTA_ERROR: ludovanta.json is not valid JSON: {e}")
        return 2

    src = source or cfg.get("source") or ""
    pin = ref or cfg.get("ref") or ""
    if not src:
        print("LUDOVANTA_ERROR: 'source' is empty in ludovanta.json")
        return 2

    install_args = ["--project", str(root)]
    if ref:
        install_args += ["--ref", ref]
    if source:
        install_args += ["--source", source]
    if force:
        install_args.append("--force")
    if dry_run:
        install_args.append("--dry-run")

    tmp = None
    try:
        if Path(src).is_dir():
            # Local platform checkout: used while developing the platform itself.
            print(f"Ludovanta source: local folder {src} (working tree as is, ref is not checked out)")
            platform_dir = Path(src)
        else:
            if not pin:
                print("LUDOVANTA_ERROR: 'ref' is empty in ludovanta.json")
                return 2
            tmp = tempfile.mkdtemp(prefix="ludovanta-")
            platform_dir = Path(tmp) / "platform"
            print(f"Ludovanta source: {src} @ {pin}")
            code, out = _git("clone", "--quiet", "--depth", "1", "--branch", pin, "--", src, str(platform_dir))
            if code != 0:
                print(f"LUDOVANTA_ERROR: git clone failed: {out}")
                return 2

        code, commit = _git("-C", str(platform_dir), "rev-parse", "HEAD")
        if code == 0:
            install_args += ["--commit", commit]
        installer = platform_dir / "install.py"
        if not installer.is_file():
            print("LUDOVANTA_ERROR: install.py not found in the platform source")
            return 2
        return subprocess.call([sys.executable, "-B", str(installer), *install_args])
    finally:
        if tmp:
            _rmtree(tmp)
