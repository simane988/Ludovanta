"""worktree clean: remove the git worktrees of finished tasks once their work is in the main branch.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Parallel executors work in their own worktrees (made by 'worker start' through Orca, by Orca, Claude Code or by hand), each with its own Unity
Library of several GB. A linked worktree is removed, together with its branch, only when nothing can be lost:

    merged     its HEAD is already in the branch of the main working copy
    worked on  that HEAD was committed after the worktree was created (a fresh worktree is an agent about to start)
    clean      no uncommitted or untracked files (ignored ones such as Library/ do not count)
    free       not locked, not open in Unity, no agent working in it; worktrees Orca knows are removed through Orca
               (it closes their terminals), others only when on Windows no program holds the folder

The main working copy and the worktree the command runs in are never removed. The hooks run it in the background
from the main working copy ('worktrees': {'autoClean': false} in ludovanta.json turns that off).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .common import EXIT_OK, IS_WINDOWS, LudovantaError, editor_open, finish, load_config, slash, spawn_detached

LOG_NAME = "worktree-clean.log"
LOCK_NAME = "worktree-clean.lock"
LOCK_STALE_SECONDS = 30 * 60


def _git(cwd, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise LudovantaError(f"git failed: {e}")


def _same(a, b) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _inside(path, folder) -> bool:
    p, f = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def list_worktrees(root: Path) -> list[dict]:
    """'git worktree list --porcelain' as dicts; the first one is the main working copy."""
    p = _git(root, "worktree", "list", "--porcelain")
    if p.returncode != 0:
        raise LudovantaError(f"not a git repository or git is too old: {(p.stderr or p.stdout).strip()}")
    items: list[dict] = []
    for line in p.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key == "worktree":
            items.append({"path": value})
        elif items and key == "branch":
            items[-1]["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif items and key in ("HEAD", "locked", "prunable", "bare", "detached"):
            items[-1][key.lower()] = value or True
    return items


def _admin_dir(worktree: Path) -> Path | None:
    """.git/worktrees/<name> of a linked worktree (its '.git' file points there)."""
    p = _git(worktree, "rev-parse", "--absolute-git-dir")
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def _created(worktree: Path) -> float | None:
    """When the worktree was created: 'commondir' in its admin folder is written once, by 'git worktree add'."""
    admin = _admin_dir(worktree)
    try:
        return (admin / "commondir").stat().st_mtime if admin else None
    except OSError:
        return None


def stop_fsmonitor(path) -> None:
    """Stops git's file-watching daemon of a worktree (core.fsmonitor, on by default in some Git for Windows installs).

    It runs as long as its folder exists (one per worktree) and holds the folder open, so the in-use probe would see
    it; stopping it first also lets the folder go at once. Harmless when none runs; git starts it again when needed.
    """
    try:
        subprocess.run(["git", "-C", str(path), "fsmonitor--daemon", "stop"], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def _in_use(path: Path) -> bool:
    """Windows: a folder that a process works in (or holds a file in) cannot be renamed."""
    if not IS_WINDOWS:
        return False
    stop_fsmonitor(path)
    probe = path.with_name(path.name + ".ludovanta-probe")
    try:
        os.rename(path, probe)
    except OSError:
        return True
    try:
        os.rename(probe, path)
    except OSError as e:
        raise LudovantaError(f"could not rename '{probe}' back to '{path}': {e}")
    return False


def _orca_rows(root: Path) -> tuple[str | None, dict]:
    """Orca's view of its worktrees by path, when the Orca app is running: they are removed through Orca."""
    from . import orca
    exe, _ = orca.available(root)
    if not exe:
        return None, {}
    try:
        return exe, orca._rows(exe)
    except LudovantaError:
        return None, {}


def review(root: Path) -> tuple[dict, list[dict]]:
    """The main working copy and every linked worktree with a verdict: action 'remove' or 'keep' and the reason."""
    items = list_worktrees(root)
    exe, rows = _orca_rows(root) if len(items) > 1 else (None, {})
    main, linked = items[0], items[1:]
    base = main.get("head")
    top = _git(root, "rev-parse", "--show-toplevel").stdout.strip()
    unity_rel = os.path.relpath(root, top) if top else "."   # the Unity project can sit in a subfolder of the repo
    for wt in linked:
        path = Path(wt["path"])
        wt["action"], wt["reason"] = "keep", ""
        row = rows.get(os.path.normcase(os.path.normpath(wt["path"])))
        if row:
            wt["orca"], wt["orcaExe"] = row.get("worktreeId"), exe
        if wt.get("bare"):
            wt["reason"] = "bare repository"
        elif wt.get("prunable") or not path.is_dir():
            wt["action"], wt["reason"] = "prune", "folder is gone"
        elif _inside(root, path):
            wt["reason"] = "this command runs in it"
        elif wt.get("locked"):
            wt["reason"] = "locked" + (f" ({wt['locked']})" if isinstance(wt["locked"], str) else "")
        elif not base or _git(root, "merge-base", "--is-ancestor", wt["head"], base).returncode != 0:
            wt["reason"] = f"not merged into {main.get('branch') or 'the main working copy'}"
        elif not _worked_on(path, wt["head"]):
            wt["reason"] = "nothing committed in it yet (an agent may be about to start)"
        elif _git(path, "status", "--porcelain").stdout.strip():
            wt["reason"] = "uncommitted changes"
        elif editor_open(path / unity_rel):
            wt["reason"] = "open in Unity"
        elif row and any(a.get("state") == "working" for a in row.get("agents") or []):
            wt["reason"] = "an agent is working in it (Orca)"
        elif not row and _in_use(path):   # Orca closes its own terminals when it removes a worktree
            wt["reason"] = "in use by another program (agent terminal, IDE)"
        else:
            wt["action"] = "remove"
    return main, linked


def _worked_on(path: Path, head: str) -> bool:
    created = _created(path)
    p = _git(path, "log", "-1", "--format=%ct", head)
    try:
        committed = int(p.stdout.strip())
    except ValueError:
        return False
    return created is not None and committed > int(created)


def _remove(main: dict, wt: dict) -> str | None:
    """Removes the worktree (through Orca when Orca manages it) and its merged branch; returns an error or None."""
    from . import orca
    stop_fsmonitor(wt["path"])
    if wt.get("orca"):
        try:
            orca.orca(wt["orcaExe"], "worktree", "rm", "--worktree", f"id:{wt['orca']}", timeout=1800)
        except LudovantaError as e:
            return str(e)
    else:
        p = _git(main["path"], "worktree", "remove", wt["path"], timeout=1800)
        if p.returncode != 0:
            return (p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else "git failed"
    branch = wt.get("branch")
    if branch and branch != main.get("branch"):
        # -d, not -D: git itself refuses a branch that is not merged.
        _git(main["path"], "branch", "-d", branch)
    return None


def _forget_workers(root: Path, path) -> None:
    from . import orca
    orca.forget(root, path)


def clean(root: Path, dry_run: bool, as_json: bool) -> int:
    main, linked = review(root)
    removed, kept, failed = [], [], []
    for wt in linked:
        name = slash(wt["path"])
        if wt["action"] == "remove" and not dry_run:
            error = _remove(main, wt)
            if not error:
                _forget_workers(root, wt["path"])
            (failed if error else removed).append({"path": name, "branch": wt.get("branch"), "reason": error or ""})
        elif wt["action"] == "remove":
            removed.append({"path": name, "branch": wt.get("branch"), "reason": ""})
        elif wt["action"] == "keep":
            kept.append({"path": name, "branch": wt.get("branch"), "reason": wt["reason"]})
    pruned = sum(1 for wt in linked if wt["action"] == "prune")
    if pruned and not dry_run:
        _git(main["path"], "worktree", "prune")
        for wt in linked:
            if wt["action"] == "prune":
                _forget_workers(root, wt["path"])

    verb = "would remove" if dry_run else "removed"
    lines = []
    for w in removed:
        lines.append(f"{verb}: {w['path']}" + (f" (branch {w['branch']})" if w["branch"] else ""))
    for w in failed:
        lines.append(f"failed: {w['path']}: {w['reason']}")
    for w in kept:
        lines.append(f"kept: {w['path']}" + (f" [{w['branch']}]" if w["branch"] else "") + f": {w['reason']}")
    if pruned:
        lines.append(f"{'would prune' if dry_run else 'pruned'}: {pruned} worktree record(s) whose folder is gone")
    status = "WORKTREES_DRY_RUN" if dry_run else ("WORKTREES_REMOVED" if removed else "WORKTREES_CLEAN")
    lines.insert(0, f"{status}: {len(removed)} {verb}, {len(kept)} kept, {len(failed)} failed")
    data = {"removed": removed, "kept": kept, "failed": failed, "pruned": pruned, "dryRun": dry_run}
    return finish(status, EXIT_OK, lines, data, as_json)


# --- Automatic cleanup from the hooks -----------------------------------------------------------

def _has_linked_worktrees(root: Path) -> bool:
    """Cheap check without starting git: the main working copy's .git/worktrees has entries."""
    for d in [root, *root.parents]:
        git = d / ".git"
        if git.is_dir():
            admin = git / "worktrees"
            return admin.is_dir() and any(admin.iterdir())
        if git.exists():
            return False   # a '.git' file: this is a linked worktree, cleanup runs from the main working copy
    return False


def auto_clean(root: Path) -> bool:
    """Starts 'worktree clean' in the background (removing a Unity Library takes a while); True if started."""
    if (load_config(root).get("worktrees") or {}).get("autoClean") is False or not _has_linked_worktrees(root):
        return False
    (root / "Logs" / "ludovanta").mkdir(parents=True, exist_ok=True)
    spawn_detached(root, "worktree", "clean", "--background")
    return True


def background_clean(root: Path) -> int:
    """One cleanup at a time; the result goes to Logs/ludovanta/worktree-clean.log."""
    log_dir = root / "Logs" / "ludovanta"
    log_dir.mkdir(parents=True, exist_ok=True)
    lock = log_dir / LOCK_NAME
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
            lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return EXIT_OK   # another cleanup is running
    try:
        os.close(fd)
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        try:
            with redirect_stdout(out):
                clean(root, dry_run=False, as_json=False)
        except Exception as e:  # noqa: BLE001 - nobody sees a background failure except through the log
            out.write(f"LUDOVANTA_ERROR: {e}\n")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        (log_dir / LOG_NAME).write_text(f"{stamp}\n{out.getvalue()}", encoding="utf-8")
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return EXIT_OK

