"""Executors in Orca: one agent per task, visible in the Orca app (skill ludovanta-plan).

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Two lanes, chosen by the card's 'editor' field:

    editor: true   (default) the task needs the Unity Editor: scenes, prefabs, visuals, Play mode, Unity MCP. Only one
                   Editor can open a project folder, and Unity MCP talks to the Editor of the main working copy, so
                   these run one at a time in the main working copy: a new agent terminal there, no worktree, no merge.
    editor: false  code, data, EditMode tests: an Orca worktree of its own, HEADLESS (batchmode), several in parallel,
                   merged back by 'worker finish'.

    worker start T-001 [--agent claude|codex]   commit the card as in-progress, start the agent in its lane
    worker wait [T-001 ...]                      wait until an executor finishes or stops, print its report
    worker list                                  every executor and where it stands, without waiting
    worker send T-001 "text"                     type an answer or a correction into the executor's agent
    worker finish T-001                          worktree: merge and remove it; editor: check the commit, close the agent

The watcher. 'worker wait' lives inside one turn of the orchestrator: when it returns and the orchestrator ends its
turn, nothing waits any more, and an agent between turns wakes only on input. So the worker commands remember the
orchestrator's Orca terminal (ORCA_TERMINAL_HANDLE) and keep 'worker watch' running in the background, outside any
turn. When an executor finishes, stops or is blocked, the watcher waits until the orchestrator's agent is idle and
its terminal has been quiet for a minute (typing shows as output: the line must not land in the user's draft), and
types one line into its terminal; after 10 minutes of waiting it types the line anyway; the orchestrator runs 'worker wait' and gets the reports. Each state is announced
once ('notified' in the executor's state); what 'worker wait' or 'list' already showed is not announced. The watcher
exits when no executors are left; the next worker command or session start starts it again.

Executors do not commit: Codex's sandbox keeps .git read-only, and a worktree's git data lives in the main working
copy's .git, outside the worktree. 'worker finish' commits their work (all of it in a worktree; in the main working
copy the files changed since the start, not the ones that were already uncommitted then).

Codex starts with Orca's own launcher, unless 'codex.sandbox' or 'codex.model' is set in ludovanta.json or
ludovanta.local.json: then Ludovanta starts 'codex --sandbox ... --model ...' in an Orca terminal itself.

Orca must be running (the 'orca' CLI talks to the app). The state of each executor lives in
Logs/ludovanta/workers/<task>.json; the task card the executor works on is the source of truth for its status.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import plan as plan_mod
from .common import (EXIT_INFRA, EXIT_OK, EXIT_PROBLEMS, LudovantaError, finish, load_config, relpath, slash,
                     spawn_detached)

AGENTS = ("claude", "codex")
FINISHED = ("review", "done")
START_GRACE_SECONDS = 90      # an agent that has not picked up its prompt yet also looks idle
REPORT_LINES = 40
READY_TIMEOUT_MS = 90_000     # a fresh agent TUI must be idle before it can take the prompt
WATCH_POLL_SECONDS = 15
WATCH_STALE_SECONDS = 300     # a watcher touches its lock every round; an older lock is a dead watcher
WATCH_ORCA_DOWN_SECONDS = 600 # Orca closed this long: the watcher exits, the next worker command starts it again
IDLE_CHECK_MS = 3000          # a busy orchestrator is not interrupted: the watcher tries again next round
QUIET_SECONDS = 60            # output this recent in the orchestrator's terminal: the user may be typing there
MAX_DEFER_SECONDS = 600       # a terminal that looks busy or typed-in this long gets the line anyway
QUESTION_LINES = 8
WATCH_LOG_BYTES = 256 * 1024


# --- The orca CLI -------------------------------------------------------------------------------

def find_orca(root: Path) -> str | None:
    explicit = os.environ.get("ORCA_PATH") or load_config(root).get("orcaPath")
    if explicit:
        return str(Path(explicit).expanduser()) if Path(explicit).expanduser().is_file() else None
    return shutil.which("orca")


def orca(exe: str, *args: str, timeout: int = 180) -> dict:
    """Runs 'orca <args> --json' and returns its 'result'; raises LudovantaError with Orca's message on failure."""
    try:
        p = subprocess.run([exe, *args, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise LudovantaError(f"orca {' '.join(args[:2])} did not answer in {timeout} s")
    except OSError as e:
        raise LudovantaError(f"orca could not be started: {e}")
    try:
        reply = json.loads(p.stdout)
    except ValueError:
        reply = None
    if not isinstance(reply, dict) or not reply.get("ok"):
        error = (reply or {}).get("error") if isinstance(reply, dict) else None
        message = (error or {}).get("message") if isinstance(error, dict) else None
        raise LudovantaError(f"orca {' '.join(args[:2])} failed: "
                             f"{message or (p.stdout + p.stderr).strip()[-500:] or f'exit code {p.returncode}'}")
    return reply.get("result") or {}


def available(root: Path) -> tuple[str | None, str]:
    """(orca executable, '') when the Orca app is running and reachable, else (None, why not)."""
    exe = find_orca(root)
    if not exe:
        return None, "the orca CLI is not found (Orca: Settings -> General -> Orca CLI, or 'orcaPath' in ludovanta.local.json)"
    try:
        runtime = orca(exe, "status", timeout=30).get("runtime") or {}
    except LudovantaError as e:
        return None, str(e)
    if not runtime.get("reachable"):
        return None, "the Orca app is not running (start it, or run 'orca open')"
    return exe, ""


# --- Git -------------------------------------------------------------------------------------------

def _git(cwd, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise LudovantaError(f"git failed: {e}")


def _git_ok(cwd, *args: str) -> str:
    p = _git(cwd, *args)
    if p.returncode != 0:
        raise LudovantaError(f"git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def _linked_worktree(root: Path) -> bool:
    git_dir = _git_ok(root, "rev-parse", "--absolute-git-dir")
    common = Path(_git_ok(root, "rev-parse", "--git-common-dir"))
    return _norm(git_dir) != _norm(common if common.is_absolute() else root / common)


def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


# --- Executor state ----------------------------------------------------------------------------------

def _state_dir(root: Path) -> Path:
    return root / "Logs" / "ludovanta" / "workers"


def _load(root: Path, task_id: str) -> dict:
    path = _state_dir(root) / f"{task_id}.json"
    if not path.is_file():
        raise LudovantaError(f"no executor for {task_id} in Orca (start one with 'worker start {task_id}')")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    """Whole file or nothing: the watcher reads these files while the worker commands write them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)   # Windows: a reader has the file open for a moment
    os.replace(tmp, path)


def _save(root: Path, state: dict) -> None:
    _write_json(_state_dir(root) / f"{state['task']}.json", state)


def _all(root: Path) -> list[dict]:
    folder = _state_dir(root)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("T-*.json"))] if folder.is_dir() else []


def forget(root: Path, worktree_path) -> None:
    """Drops the state of an executor whose worktree is gone (called by 'worktree clean')."""
    for state in _all(root):
        if _norm(state["path"]) == _norm(worktree_path):
            (_state_dir(root) / f"{state['task']}.json").unlink(missing_ok=True)


def _mark(root: Path, task_id: str, notified: str | None) -> None:
    """Records which state of the executor the orchestrator has seen (re-read: the watcher and the commands both
    write the file)."""
    try:
        state = _load(root, task_id)
    except LudovantaError:
        return   # finished meanwhile
    if state.get("notified") != notified:
        state["notified"] = notified
        _save(root, state)


# --- The watcher ---------------------------------------------------------------------------------------

def _orchestrator_file(root: Path) -> Path:
    return _state_dir(root) / "orchestrator.json"


def _load_orchestrator(root: Path) -> dict | None:
    try:
        return json.loads(_orchestrator_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _remember_orchestrator(root: Path) -> dict | None:
    """The Orca terminal this worker command runs in is the orchestrator's (an executor's own terminal is not):
    the watcher types there. Returns the orchestrator on record."""
    handle = os.environ.get("ORCA_TERMINAL_HANDLE")
    pane = os.environ.get("ORCA_PANE_KEY", "")
    states = _all(root)
    if not handle or any(s.get("terminal") == handle or (pane and s.get("pane") == pane) for s in states):
        return _load_orchestrator(root)
    worktree = os.environ.get("ORCA_WORKTREE_ID")
    selector = f"id:{worktree}" if worktree else f"path:{slash(_git_ok(root, 'rev-parse', '--show-toplevel'))}"
    info = {"terminal": handle, "pane": pane, "worktree": selector}
    if info != _load_orchestrator(root):
        _write_json(_orchestrator_file(root), info)
    return info


def _watch_lock(root: Path) -> Path:
    return root / "Logs" / "ludovanta" / "worker-watch.lock"


def ensure_watcher(root: Path) -> str:
    """Starts 'worker watch' in the background unless one runs. Returns one line for the orchestrator."""
    if not _load_orchestrator(root):
        return ("This is not an Orca terminal, so nothing can wake you when an executor finishes: keep running "
                "'worker wait' while executors work.")
    if not _all(root) or os.environ.get("LUDOVANTA_NO_WATCHER"):   # the tests run the watcher in the foreground
        return ""
    lock = _watch_lock(root)
    try:
        running = lock.is_file() and time.time() - lock.stat().st_mtime < WATCH_STALE_SECONDS
    except OSError:
        running = False
    if not running:
        spawn_detached(root, "worker", "watch")
    return ("The watcher types into this terminal when an executor finishes or stops: you may end your turn, it "
            "wakes you.")


def _take_lock(lock: Path, token: str) -> bool:
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if lock.is_file() and time.time() - lock.stat().st_mtime > WATCH_STALE_SECONDS:
            lock.unlink()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    return True


def _owns_lock(lock: Path, token: str) -> bool:
    try:
        return lock.read_text(encoding="utf-8") == token
    except OSError:
        return False


_last_log = [""]


def _log(root: Path, line: str, key: str = "") -> None:
    """key: a line that would repeat every round is written only when its key changes."""
    if key and _last_log[0] == key:
        return
    _last_log[0] = key
    log = root / "Logs" / "ludovanta" / "worker-watch.log"
    try:
        if log.is_file() and log.stat().st_size > WATCH_LOG_BYTES:
            log.unlink()
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _orchestrator_terminal(exe: str, info: dict) -> dict | None:
    """The orchestrator's terminal as Orca lists it; handles change when Orca restarts, the pane stays."""
    try:
        terminals = orca(exe, "terminal", "list", "--worktree", info["worktree"], timeout=30).get("terminals") or []
    except LudovantaError:
        return {"handle": info["terminal"]}
    for t in terminals:
        if t.get("handle") == info["terminal"]:
            return t
    for t in terminals:
        if info.get("pane") and (t.get("paneKey") or f"{t.get('tabId')}:{t.get('leafId')}") == info["pane"]:
            return t
    return None   # the orchestrator's terminal is closed: nobody to wake


def _idle(exe: str, handle: str) -> bool:
    try:
        result = orca(exe, "terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                      "--timeout-ms", str(IDLE_CHECK_MS), timeout=30)
    except LudovantaError:
        return False   # Orca reports a busy TUI as a timeout
    return bool((result.get("wait") or result).get("satisfied", True))


SETTLED_WORDS = {"finished": "finished (card in review)", "stopped": "stopped (a question or a failure)",
                 "blocked": "is blocked", "gone": "is gone (its worktree was removed)"}


def _watch_round(root: Path, exe: str) -> list[str]:
    """One look at every executor; returns the tasks announced to the orchestrator."""
    rows = _rows(exe)
    due, running = [], 0
    for s in _all(root):
        state = verdict(root, s, rows.get(_norm(s["path"])))["state"]
        if state == "running":
            running += 1
            if s.get("notified"):
                _mark(root, s["task"], None)   # working again (an answer was sent): its next stop is news
        elif s.get("notified") != state:
            due.append((s["task"], state))
    info = _load_orchestrator(root)
    if not due or not info:
        _set_deferred(root, None)
        return []
    term = _orchestrator_terminal(exe, info)
    if not term:
        _log(root, f"waiting: the orchestrator's terminal {info['terminal']} is not in Orca", key="gone")
        return []
    since = _deferred_since(root) or _set_deferred(root, time.time())
    waited = time.time() - since
    handle = term["handle"]
    quiet = time.time() - float(term.get("lastOutputAt") or 0) / 1000
    if quiet < QUIET_SECONDS:
        busy, kind = f"output in its terminal {quiet:.0f} s ago (the user typing?)", "output"
    elif not _idle(exe, handle):
        busy, kind = "its agent is not idle", "busy"
    else:
        busy, kind = "", ""
    if busy and waited < MAX_DEFER_SECONDS:
        preview = " ".join(str(term.get("preview") or "").split())[-60:]
        _log(root, f"waiting {waited / 60:.0f} min to wake the orchestrator: {busy}; its screen ends {preview!r}",
             key=f"{kind}-{int(waited // 300)}")   # again every 5 minutes
        return []   # the line would land in the user's draft, or wait behind a long job
    if busy:
        _log(root, f"waited {waited / 60:.0f} min ({busy}): typing the line anyway")
    news = "; ".join(f"{task} {SETTLED_WORDS.get(state, state)}" for task, state in due)
    orca(exe, "terminal", "send", "--terminal", handle, "--text",
         f"Ludovanta watcher: executor {news}. Run ludovanta.py worker wait and handle it by the skill "
         f"ludovanta-plan" + (f"; {running} other executor(s) keep working." if running else "."), "--enter",
         timeout=30)
    for task, state in due:
        _mark(root, task, state)
    _set_deferred(root, None)
    _log(root, f"woke the orchestrator ({handle}): {news}")
    return [task for task, _ in due]


def _deferred_file(root: Path) -> Path:
    return root / "Logs" / "ludovanta" / "worker-watch-deferred.txt"


def _deferred_since(root: Path) -> float | None:
    """Since when there is news the orchestrator has not got."""
    try:
        return float(_deferred_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _set_deferred(root: Path, since: float | None) -> float | None:
    path = _deferred_file(root)
    if since is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(str(since), encoding="utf-8")
    return since


def watch(root: Path, rounds: int, poll: float | None, as_json: bool) -> int:
    """The background watcher (started by the worker commands); 'rounds' and 'poll' are for tests."""
    poll = WATCH_POLL_SECONDS if poll is None else poll
    lock, token = _watch_lock(root), f"{os.getpid()}-{time.time()}"
    if not _take_lock(lock, token):
        return finish("WATCH_BUSY", EXIT_OK, ["WATCH_BUSY: another watcher runs for this project."], {}, as_json)
    announced, down_since, n, reason = [], None, 0, "no executors left"
    _log(root, "started")
    try:
        while True:
            try:
                if not _all(root):
                    break
                if not _owns_lock(lock, token):
                    reason = "another watcher took over"
                    break
                os.utime(lock)
                exe, why = available(root)
                if exe:
                    down_since = None
                    announced += _watch_round(root, exe)
                else:
                    down_since = down_since or time.monotonic()
                    if time.monotonic() - down_since > WATCH_ORCA_DOWN_SECONDS:
                        reason = why
                        break
            except Exception as e:  # noqa: BLE001 - nobody sees the watcher fail except through its log
                _log(root, f"round failed: {type(e).__name__}: {e}")
            n += 1
            if rounds and n >= rounds:
                reason = f"{n} round(s) done"
                break
            time.sleep(poll)
    finally:
        if _owns_lock(lock, token):
            lock.unlink(missing_ok=True)
        _log(root, f"exited: {reason}")
    return finish("WATCH_DONE", EXIT_OK, [f"WATCH_DONE: announced {', '.join(announced) or 'nothing'}."],
                  {"announced": announced}, as_json)


# --- worker start --------------------------------------------------------------------------------------

def _prompt(task_id: str, lane: str) -> str:
    # One line without quotes, % or !: on Windows the prompt can pass through cmd.exe.
    brief = (f"Run: python3 .ludovanta/ludovanta.py plan brief {task_id} (on Windows: python or py -3) and do the "
             f"task by its rules.")
    done = ("Do not commit, merge or push: Ludovanta commits your work when the orchestrator finishes the task. "
            "Your final message is the task report.")
    if lane == "editor":
        return (f"You are the executor of Ludovanta task {task_id} in this Unity project, in the main working copy "
                f"where the Unity Editor may be open: check the mode with status, in LIVE mode work through Unity "
                f"MCP. {brief} {done}")
    return (f"You are the executor of Ludovanta task {task_id} in this Unity project, working in your own git "
            f"worktree without the Unity Editor (HEADLESS, do not use Unity MCP). {brief} {done}")


def _agent_command(root: Path, agent: str) -> str | None:
    """The command line for an agent Ludovanta starts itself, or None to let Orca start it with its own settings."""
    if agent != "codex":
        return None
    from .codex import SANDBOXES
    cfg = load_config(root).get("codex") or {}
    parts = ["codex"]
    if cfg.get("sandbox"):
        if cfg["sandbox"] not in SANDBOXES:
            raise LudovantaError(f"ludovanta.json: codex.sandbox must be one of {', '.join(SANDBOXES)}")
        parts += ["--sandbox", cfg["sandbox"]]
    if cfg.get("model"):
        parts += ["--model", str(cfg["model"])]
    return " ".join(parts) if len(parts) > 1 else None


def _dirty_paths(top) -> list[str]:
    """Paths with uncommitted changes (untracked files one by one), relative to the repository."""
    out = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.split("\0")
    paths, i = [], 0
    while i < len(out):
        entry = out[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":
            i += 1   # a rename or copy is followed by its old path
    return paths


def _commit(top, paths: list[str] | None, message: str) -> str | None:
    """Commits these paths (None: everything); returns the short hash, or None when there was nothing to commit."""
    if paths == []:
        return None
    if paths is None:
        _git_ok(top, "add", "-A")
        if _git(top, "diff", "--cached", "--quiet").returncode == 0:
            return None
        _git_ok(top, "commit", "--quiet", "-m", message)
    else:
        # Paths go through stdin: a Unity task can touch hundreds of files, too many for a Windows command line.
        spec = "\0".join(paths) + "\0"
        for args in (["add", "-A"], ["commit", "--quiet", "-m", message]):
            p = subprocess.run(["git", "-C", str(top), *args, "--pathspec-from-file=-", "--pathspec-file-nul"],
                               input=spec, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if p.returncode != 0:
                raise LudovantaError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()}")
    return _git_ok(top, "rev-parse", "--short", "HEAD")


def _name(task_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{task_id.lower()}-{slug}"[:48].strip("-") if slug else task_id.lower()


def _repo_selector(exe: str, top: str) -> str:
    """Orca's repo for this project; registers the project in Orca if it is not there yet."""
    for repo in orca(exe, "repo", "list").get("repos") or []:
        if _norm(repo.get("path", "")) == _norm(top):
            return f"id:{repo['id']}"
    added = orca(exe, "repo", "add", "--path", top)
    repo_id = (added.get("repo") or added).get("id")
    if not repo_id:
        raise LudovantaError(f"orca repo add did not return a repo id: {added}")
    return f"id:{repo_id}"


def start(root: Path, task_id: str, agent: str | None, as_json: bool) -> int:
    exe, why = available(root)
    if not exe:
        return finish("ORCA_UNAVAILABLE", EXIT_INFRA, [
            f"ORCA_UNAVAILABLE: {why}.",
            "Give the task to an executor without Orca instead: a subagent, or 'codex run' (skill ludovanta-plan)."],
            {"reason": why}, as_json)
    plan = plan_mod.Plan(root)
    task = plan.by_id.get(task_id)
    if not task:
        raise LudovantaError(f"task {task_id} not found")
    agent = (agent or (task["agent"] if task["agent"] in AGENTS else "claude")).lower()
    if agent not in AGENTS:
        raise LudovantaError(f"--agent must be one of {', '.join(AGENTS)}")
    if (_state_dir(root) / f"{task_id}.json").is_file():
        return finish("WORKER_EXISTS", EXIT_PROBLEMS, [
            f"WORKER_EXISTS: {task_id} already has an executor in Orca. 'worker list' shows it; 'worker finish' "
            "ends it."], {}, as_json)
    lane = "editor" if task["editor"] else "worktree"
    busy = _editor_worker(root)
    if lane == "editor" and busy:
        return finish("EDITOR_BUSY", EXIT_PROBLEMS, [
            f"EDITOR_BUSY: {busy['task']} works in the Unity Editor now; tasks that need the Editor run one at a time. "
            f"Start tasks with 'editor: false' meanwhile, and {task_id} after 'worker finish {busy['task']}'."],
            {"busy": busy["task"]}, as_json)
    problems = []
    if not task["criteria"]:
        problems.append(f"{task_id} has no acceptance criteria: write them first")
    if task["status"] not in ("todo", "in-progress"):
        problems.append(f"{task_id} is '{task['status']}', not todo")
    unmet = [d for d in task["depends"]
             if d not in plan.archived_ids and plan.by_id.get(d, {}).get("status") not in plan_mod.DEPENDENCY_MET]
    if unmet:
        problems.append(f"dependencies not finished: {', '.join(unmet)}")
    top = _git_ok(root, "rev-parse", "--show-toplevel")
    branch = _git_ok(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        problems.append("the main working copy is on a detached HEAD: check out a branch first")
    if _linked_worktree(root):
        problems.append("run it from the main working copy, not from a worktree")
    plan_rel = relpath(Path(top), plan.dir)
    if _git(top, "status", "--porcelain", "--", plan_rel).stdout.strip():
        problems.append(f"{plan_rel}/ has uncommitted changes: commit the plan first, the executor starts from the "
                        "last commit")
    if problems:
        return finish("NOT_STARTABLE", EXIT_PROBLEMS, [f"NOT_STARTABLE: {task_id}"] + [f"  {p}" for p in problems],
                      {"problems": problems}, as_json)

    # The card says in-progress in the commit the worktree starts from: the executor's 'review' then merges cleanly.
    card = plan.card(task_id)
    card.set_field("status", "in-progress")
    card.set_field("agent", agent)
    card.save()
    card_rel = relpath(Path(top), card.path)
    _git_ok(top, "add", "--", card_rel)
    _git_ok(top, "commit", "--quiet", "-m", f"{task_id}: started by {agent} in Orca", "--", card_rel)

    _remember_orchestrator(root)
    repo = _repo_selector(exe, top)
    unity = relpath(Path(top), root) if _norm(top) != _norm(root) else ""
    state = {"task": task_id, "title": task["title"], "agent": agent, "lane": lane, "base": branch,
             "started": time.time(), "unity": unity}
    command = _agent_command(root, agent)
    if lane == "editor":
        state.update({"id": "", "path": slash(top), "branch": branch, "dirtyAtStart": _dirty_paths(top)})
        return _start_in_terminal(root, exe, state, command or agent, as_json)
    launch = [] if command else ["--agent", agent, "--prompt", _prompt(task_id, lane)]
    created = orca(exe, "worktree", "create", "--repo", repo, "--name", _name(task_id, task["title"]),
                   "--base-branch", branch, *launch, "--comment", f"{task_id} {task['title']}", timeout=600)
    wt = created.get("worktree") or {}
    state.update({"id": wt.get("id", ""), "path": slash(wt.get("path", "")),
                  "branch": re.sub(r"^refs/heads/", "", wt.get("branch", "")),
                  "terminal": created.get("agentTerminalHandle") or ""})
    if not state["path"] or not state["branch"]:
        raise LudovantaError(f"orca worktree create returned no path or branch: {created}")
    if command:
        return _start_in_terminal(root, exe, state, command, as_json)
    _save(root, state)
    return finish("WORKER_STARTED", EXIT_OK, _started_lines(root, state), state, as_json)


def _started_lines(root: Path, state: dict) -> list[str]:
    if state["lane"] == "editor":
        where = (f"in the main working copy ({state['path']}), a new Orca terminal. It needs the Unity Editor, so "
                 "other tasks that need it wait until 'worker finish'.")
        tail = ["Next: start ready tasks with 'editor: false' in parallel, then 'worker wait'."]
    else:
        where = f"in Orca worktree {state['path']} (branch {state['branch']}, HEADLESS)."
        tail = ["The first compile in a fresh worktree imports all assets and can take many minutes.",
                "Next: start other ready tasks, then 'worker wait'."]
    watcher = ensure_watcher(root)
    return [f"WORKER_STARTED: {state['task']} -> {state['agent']} {where}",
            f"card committed as in-progress on {state['base']}."] + tail + ([watcher] if watcher else [])


def _wait_idle(exe: str, handle: str) -> bool:
    for _ in range(2):
        try:
            result = orca(exe, "terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                          "--timeout-ms", str(READY_TIMEOUT_MS), timeout=READY_TIMEOUT_MS // 1000 + 60)
        except LudovantaError:
            continue   # Orca reports a timeout as an error
        if (result.get("wait") or result).get("satisfied", True):
            return True
    return False


def _start_in_terminal(root: Path, exe: str, state: dict, command: str, as_json: bool) -> int:
    """An agent terminal Ludovanta starts itself (the main working copy, or Codex with its own settings); the prompt
    goes in once its TUI is ready."""
    task_id, agent = state["task"], state["agent"]
    term = orca(exe, "terminal", "create", "--worktree", f"path:{state['path']}", "--title",
                f"{task_id} {state['title']}", "--command", command).get("terminal") or {}
    if not term.get("handle"):
        raise LudovantaError(f"orca terminal create returned no handle: {term}")
    state.update({"id": state.get("id") or term.get("worktreeId", ""), "terminal": term["handle"],
                  "pane": term.get("paneKey", ""), "command": command})
    _save(root, state)
    if not _wait_idle(exe, term["handle"]):
        return finish("AGENT_NOT_READY", EXIT_INFRA, [
            f"AGENT_NOT_READY: the {agent} terminal for {task_id} did not get ready in {READY_TIMEOUT_MS // 500} s "
            "(a login or trust prompt?). Look at it in Orca, then give it the task with "
            f"'worker send {task_id} \"<prompt>\"', or close it and 'worker finish {task_id}'."], state, as_json)
    orca(exe, "terminal", "send", "--terminal", term["handle"], "--text", _prompt(task_id, state["lane"]), "--enter")
    state["started"] = time.time()
    _save(root, state)
    return finish("WORKER_STARTED", EXIT_OK, _started_lines(root, state), state, as_json)


def _editor_worker(root: Path) -> dict | None:
    return next((s for s in _all(root) if s.get("lane") == "editor"), None)


# --- worker wait / list -----------------------------------------------------------------------------

def _card_status(state: dict) -> str:
    plan = plan_mod.Plan(Path(state["path"]) / (state.get("unity") or ""))
    return plan.by_id.get(state["task"], {}).get("status", "?")


def _rows(exe: str) -> dict:
    return {_norm(r.get("path", "")): r for r in orca(exe, "worktree", "ps").get("worktrees") or []}


def _agent(state: dict, row: dict | None) -> dict | None:
    """The executor's agent in Orca's row: by its pane in the main working copy (the orchestrator works there too),
    by its type in its own worktree."""
    agents = (row or {}).get("agents") or []
    if state.get("pane"):
        return next((a for a in agents if a.get("paneKey") == state["pane"]), None)
    return next((a for a in agents if a.get("agentType") == state["agent"]), agents[0] if agents else None)


def _report(state: dict, row: dict | None) -> list[str]:
    agent = _agent(state, row) or {}
    message = agent.get("lastAssistantMessage")
    if message and not agent.get("lastAssistantMessageIsToolOutput"):
        lines = message.strip().splitlines()
        return lines[-REPORT_LINES:] if len(lines) > REPORT_LINES else lines
    return []


def _work_paths(state: dict) -> list[str]:
    """What 'worker finish' commits: everything in a worktree; in the main working copy what changed since the start
    (files that were uncommitted already then stay out: they are someone else's work)."""
    paths = _dirty_paths(state["path"])
    if state.get("lane") == "editor":
        before = set(state.get("dirtyAtStart") or [])
        paths = [p for p in paths if p not in before]
    return paths


def verdict(root: Path, state: dict, row: dict | None) -> dict:
    """Where one executor stands: running, finished (card in review), blocked, stopped (agent idle, card not done),
    or gone (worktree removed)."""
    path = Path(state["path"])
    if row is None or not path.is_dir():
        return {"state": "gone", "card": "?", "agent": "", "dirty": False}
    card = _card_status(state)
    agent_state = (_agent(state, row) or {}).get("state") or ""
    working = agent_state == "working" or (state.get("lane") != "editor" and not row.get("agents")
                                           and row.get("status") == "working")
    young = time.time() - float(state.get("started") or 0) < START_GRACE_SECONDS
    dirty = bool(_work_paths(state))
    if working or (young and card not in FINISHED and card != "blocked"):
        verdict_ = "running"
    elif card in FINISHED:
        verdict_ = "finished"
    elif card == "blocked":
        verdict_ = "blocked"
    else:
        verdict_ = "stopped"
    return {"state": verdict_, "card": card, "agent": agent_state or "no agent", "dirty": dirty}


def _describe(state: dict, v: dict, row: dict | None) -> list[str]:
    where = "Unity Editor, main working copy" if state.get("lane") == "editor" else state["path"]
    head = f"{state['task']} [{state['agent']}] {v['state'].upper()}: card '{v['card']}', agent {v['agent']} ({where})"
    lines = [head]
    if v["state"] == "finished":
        what = "closes its agent" if state.get("lane") == "editor" else "merges it"
        lines.append(f"  next: check the report, then 'worker finish {state['task']}' commits and {what}")
    elif v["state"] in ("stopped", "blocked"):
        lines.append(f"  the executor stopped before review: a question, a failure or a STOP. Answer with "
                     f"'worker send {state['task']} \"...\"', or ask the user first.")
    elif v["state"] == "gone":
        lines.append("  its Orca worktree is gone; 'worker list' forgets it after 'worktree clean'.")
    report = _report(state, row) if v["state"] != "running" else []
    if report:
        lines += ["  report:"] + [f"    {line}" for line in report]
    return lines


def wait(root: Path, tasks: list[str], timeout: int, poll: float, as_json: bool) -> int:
    exe, why = available(root)
    if not exe:
        return finish("ORCA_UNAVAILABLE", EXIT_INFRA, [f"ORCA_UNAVAILABLE: {why}."], {"reason": why}, as_json)
    states = [_load(root, t) for t in tasks] if tasks else _all(root)
    if not states:
        return finish("NO_WORKERS", EXIT_OK, ["NO_WORKERS: no executors in Orca ('worker start T-xxx')."], {}, as_json)
    _remember_orchestrator(root)
    deadline = time.monotonic() + max(0, timeout)
    while True:
        rows = _rows(exe)
        results = [(s, verdict(root, s, rows.get(_norm(s["path"]))), rows.get(_norm(s["path"]))) for s in states]
        settled = [r for r in results if r[1]["state"] != "running"]
        if settled or time.monotonic() >= deadline:
            break
        time.sleep(poll)
    for s, v, _ in settled:
        _mark(root, s["task"], v["state"])   # shown here: the watcher does not announce it again
        if v["state"] == "finished" and s.get("lane") != "editor":   # the main working copy's column stays
            try:
                orca(exe, "worktree", "set", "--worktree", f"id:{s['id']}", "--workspace-status", "in-review",
                     "--unread")
            except LudovantaError:
                pass   # the board column is a courtesy; the card is the truth
    lines = []
    for s, v, row in results:
        lines += _describe(s, v, row)
    shown = {s["task"] for s, _, _ in results}
    everyone = results + [(s, verdict(root, s, rows.get(_norm(s["path"]))), rows.get(_norm(s["path"])))
                          for s in _all(root) if s["task"] not in shown]
    waiting = _waiting_for_user(root, everyone)
    lines += _waiting_lines(waiting)
    status = "WORKERS_SETTLED" if settled else "WORKERS_RUNNING"
    lines.insert(0, f"{status}: {len(settled)} of {len(results)} executor(s) need you"
                 + ("" if settled or timeout <= 0 else f"; nothing settled in {timeout} s, run 'worker wait' again"))
    if len(settled) < len(results):
        watcher = ensure_watcher(root)
        if watcher:
            lines.append(watcher)
    data = {"workers": [{**s, **v, "report": _report(s, row)} for s, v, row in results], "waitingForUser": waiting}
    return finish(status, EXIT_OK, lines, data, as_json)


def _question(report: list[str]) -> list[str]:
    """The paragraphs of the executor's final message that ask something; without a '?', its last paragraph."""
    paragraphs, current = [], []
    for line in report + [""]:
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append(current)
            current = []
    asking = [line for p in paragraphs if any("?" in line for line in p) for line in p]
    if asking:
        return asking[:QUESTION_LINES]
    return paragraphs[-1][-QUESTION_LINES:] if paragraphs else []


def _waiting_for_user(root: Path, results: list) -> list[dict]:
    """Everything the user has to answer or accept, including what was shown before and is still open: executors
    stopped with a question, and tasks in review that no executor holds any more."""
    items = [{"task": s["task"], "title": s.get("title", ""), "kind": "question", "text": _question(_report(s, row))}
             for s, v, row in results if v["state"] in ("stopped", "blocked")]
    held = {s["task"] for s, _, _ in results}
    items += [{"task": t["id"], "title": t["title"], "kind": "review", "text": []}
              for t in plan_mod.Plan(root).tasks if t["status"] == "review" and t["id"] not in held]
    return items


def _waiting_lines(items: list[dict]) -> list[str]:
    if not items:
        return []
    lines = ["WAITING FOR THE USER: end your reply to the user with all of these, numbered as here, each with its "
             "task, also the ones you asked before (an answered or accepted one drops out by itself). Ask what an "
             "executor asks only if you cannot answer it yourself; then pass each answer to its own task with "
             "'worker send'."]
    for n, item in enumerate(items, 1):
        if item["kind"] == "question":
            lines.append(f"  {n}. {item['task']} {item['title']}: the executor asks or reports a problem:")
            lines += [f"       {line}" for line in item["text"]] or ["       (see its report above)"]
        else:
            lines.append(f"  {n}. {item['task']} {item['title']}: done, waits for the user to check and accept it.")
    return lines


# --- worker send --------------------------------------------------------------------------------------

def _agent_terminal(exe: str, state: dict) -> str:
    """The agent's terminal handle; handles change when Orca restarts, so ask Orca first."""
    try:
        terminals = orca(exe, "terminal", "list", "--worktree", f"path:{state['path']}").get("terminals") or []
    except LudovantaError:
        terminals = []
    for t in terminals:
        if t.get("handle") == state.get("terminal"):
            return t["handle"]
    for t in terminals:
        pane = t.get("paneKey") or f"{t.get('tabId')}:{t.get('leafId')}"
        if state.get("pane") and pane == state["pane"]:
            return t["handle"]
        if not state.get("pane") and t.get("agentIdentity") == state["agent"]:
            return t["handle"]
    if state.get("terminal"):
        return state["terminal"]
    raise LudovantaError(f"no {state['agent']} terminal found in {state['path']}; open one in Orca")


def send(root: Path, task_id: str, text: str, as_json: bool) -> int:
    exe, why = available(root)
    if not exe:
        return finish("ORCA_UNAVAILABLE", EXIT_INFRA, [f"ORCA_UNAVAILABLE: {why}."], {"reason": why}, as_json)
    state = _load(root, task_id)
    handle = _agent_terminal(exe, state)
    one_line = " ".join(text.split())
    orca(exe, "terminal", "send", "--terminal", handle, "--text", one_line, "--enter")
    state["started"] = time.time()   # the agent needs a moment to pick it up before 'wait' may call it stopped
    state["notified"] = None         # its next stop is news for the watcher
    _save(root, state)
    _remember_orchestrator(root)
    watcher = ensure_watcher(root)
    return finish("WORKER_SENT", EXIT_OK, [f"WORKER_SENT: {task_id} got your message. "
                                           + (watcher or f"Next: 'worker wait {task_id}'.")],
                  {"task": task_id, "terminal": handle}, as_json)


# --- worker finish ------------------------------------------------------------------------------------

def _conflicts(top: str) -> list[str]:
    return _git(top, "diff", "--name-only", "--diff-filter=U").stdout.split()


def finish_worker(root: Path, task_id: str, as_json: bool) -> int:
    exe, why = available(root)
    if not exe:
        return finish("ORCA_UNAVAILABLE", EXIT_INFRA, [f"ORCA_UNAVAILABLE: {why}."], {"reason": why}, as_json)
    state = _load(root, task_id)
    if state.get("lane") == "editor":
        return _finish_in_editor(root, exe, state, as_json)
    path = Path(state["path"])
    top = _git_ok(root, "rev-parse", "--show-toplevel")
    data = {"task": task_id, "branch": state["branch"], "path": state["path"]}
    busy = _editor_worker(root)
    if busy:
        return finish("EDITOR_BUSY", EXIT_PROBLEMS, [
            f"EDITOR_BUSY: {busy['task']} works in the main working copy now. A merge would change files under its "
            f"Editor and its agent: finish {task_id} after 'worker finish {busy['task']}'."], data, as_json)
    if not path.is_dir():
        forget(root, path)
        return finish("WORKER_GONE", EXIT_PROBLEMS, [f"WORKER_GONE: the worktree of {task_id} no longer exists; "
                                                     "nothing to merge."], data, as_json)
    current = _git_ok(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current != state["base"]:
        return finish("WRONG_BRANCH", EXIT_PROBLEMS, [
            f"WRONG_BRANCH: the main working copy is on '{current}', the executor started from '{state['base']}'. "
            f"Check out '{state['base']}' and finish again."], data, as_json)
    _commit(path, None, f"{task_id}: {state['title']} ({state['agent']}, work)")
    ahead = _git_ok(top, "rev-list", "--count", f"{state['base']}..{state['branch']}")
    if ahead == "0":
        return finish("NOTHING_TO_MERGE", EXIT_PROBLEMS, [
            f"NOTHING_TO_MERGE: {state['branch']} has no changes. If the task is dropped, remove the worktree in "
            "Orca."], data, as_json)
    merge = _git(top, "merge", "--no-ff", "--no-edit", "-m", f"{task_id}: {state['title']} ({state['agent']})",
                 state["branch"])
    if merge.returncode != 0:
        conflicts = _conflicts(top)
        if conflicts:
            _git(top, "merge", "--abort")
            return finish("MERGE_CONFLICT", EXIT_PROBLEMS, [
                f"MERGE_CONFLICT: {state['branch']} conflicts with {state['base']} in: {', '.join(conflicts)}. "
                "Nothing was merged. Ask the executor to merge " + state["base"] + " into its branch and resolve "
                f"('worker send {task_id} \"...\"'), then finish again."], {**data, "conflicts": conflicts}, as_json)
        return finish("MERGE_FAILED", EXIT_PROBLEMS, [
            f"MERGE_FAILED: {(merge.stderr or merge.stdout).strip()}",
            "Usually uncommitted changes in the main working copy touch the same files: commit or stash them."],
            data, as_json)
    lines = [f"WORKER_FINISHED: {task_id} merged into {state['base']} "
             f"({_git_ok(top, 'rev-parse', '--short', 'HEAD')})."]
    try:
        from .worktrees import stop_fsmonitor
        stop_fsmonitor(path)
        orca(exe, "worktree", "rm", "--worktree", f"id:{state['id']}", timeout=900)
        if _git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{state['branch']}").returncode == 0:
            _git(top, "branch", "-d", state["branch"])
        forget(root, path)
        lines.append(f"worktree {state['path']} and branch {state['branch']} removed.")
    except LudovantaError as e:
        lines.append(f"worktree kept: {e}. 'worktree clean' removes it later.")
    status = plan_mod.Plan(root).by_id.get(task_id, {}).get("status", "?")
    lines.append(f"task status on {state['base']}: '{status}'. Verify the claims that matter, then report to the "
                 "user; the user reviews in the main working copy (Unity Editor).")
    return finish("WORKER_FINISHED", EXIT_OK, lines, {**data, "status": status}, as_json)


def _finish_in_editor(root: Path, exe: str, state: dict, as_json: bool) -> int:
    """Nothing to merge: commit the executor's files on the current branch, then close its agent terminal."""
    task_id = state["task"]
    status = _card_status(state)
    data = {"task": task_id, "status": status}
    if status not in FINISHED:
        return finish("NOT_FINISHED", EXIT_PROBLEMS, [
            f"NOT_FINISHED: {task_id} is '{status}', not in review. Let the executor finish ('worker send'), or set "
            f"the card yourself ('plan set' or 'plan fail') if you stop it, then finish again."], data, as_json)
    paths = _work_paths(state)
    commit = _commit(state["path"], paths, f"{task_id}: {state['title']} ({state['agent']})")
    data["committed"] = paths if commit else []
    lines = [f"WORKER_FINISHED: {task_id} committed on {state['base']} ({commit}, {len(paths)} file(s)), status "
             f"'{status}'." if commit else
             f"WORKER_FINISHED: {task_id}, status '{status}': nothing new to commit (the executor committed itself)."]
    left = [p for p in _dirty_paths(state["path"]) if p in set(state.get("dirtyAtStart") or [])]
    if left:
        lines.append(f"left uncommitted: {len(left)} file(s) that were already changed before the task started "
                     f"({', '.join(left[:5])}{', ...' if len(left) > 5 else ''}); if the executor changed them too, "
                     "commit them yourself.")
    try:
        orca(exe, "terminal", "close", "--terminal", _agent_terminal(exe, state), "--tab")
        lines.append("its agent terminal is closed (Orca keeps the session history).")
    except LudovantaError as e:
        lines.append(f"its agent terminal stays open: {e}")
    (_state_dir(root) / f"{task_id}.json").unlink(missing_ok=True)
    lines.append("The next task that needs the Editor can start. Verify the claims that matter, then report to the "
                 "user.")
    return finish("WORKER_FINISHED", EXIT_OK, lines, data, as_json)
