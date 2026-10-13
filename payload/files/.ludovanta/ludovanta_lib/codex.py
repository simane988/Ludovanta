"""Codex CLI as an executor: run one plan task, or generate a reference image with its built-in $imagegen skill.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Prompts go through files in Logs/ludovanta/codex/, never through the command line: on Windows 'codex' is a .cmd shim
and cmd.exe mangles multi-line or quoted arguments.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from . import plan as plan_mod
from .common import (EXIT_INFRA, EXIT_OK, EXIT_PROBLEMS, EXIT_TIMEOUT, IS_WINDOWS, LudovantaError, finish, load_config,
                     relpath)

SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF")
RESULT_LINES = 40


def find_codex(root: Path) -> str | None:
    explicit = os.environ.get("CODEX_PATH") or load_config(root).get("codexPath")
    if explicit:
        return str(Path(explicit).expanduser()) if Path(explicit).expanduser().is_file() else None
    return shutil.which("codex")


def _settings(root: Path) -> dict:
    cfg = load_config(root).get("codex") or {}
    sandbox = cfg.get("sandbox") or "workspace-write"
    if sandbox not in SANDBOXES:
        raise LudovantaError(f"ludovanta.json: codex.sandbox must be one of {', '.join(SANDBOXES)}")
    return {"sandbox": sandbox, "model": cfg.get("model")}


def _work_files(root: Path, kind: str) -> tuple[Path, Path, Path]:
    folder = root / "Logs" / "ludovanta" / "codex"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stem = f"{kind}-{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}"
    return folder / f"{stem}-prompt.md", folder / f"{stem}-result.md", folder / f"{stem}-run.log"


def _run(root: Path, exe: str, prompt_file: Path, result: Path, log: Path, timeout: int, model: str | None,
         sandbox: str) -> dict:
    instruction = (f"Read the file {relpath(root, prompt_file)} in this project and do exactly what it says. "
                   "It is your whole task.")
    args = [exe, "exec", "--cd", str(root), "--sandbox", sandbox, "--output-last-message", str(result)]
    if model:
        args += ["--model", model]
    args.append(instruction)
    start = time.monotonic()
    with open(log, "wb") as out:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=0x08000000 if IS_WINDOWS else 0)
        try:
            code, timed_out = proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)
            code, timed_out = -1, True
    return {"exitCode": code, "timedOut": timed_out, "seconds": round(time.monotonic() - start, 1),
            "log": relpath(root, log), "result": relpath(root, result)}


def _tail(path: Path, count: int = 15) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()[-count:]


def _changed_files(root: Path) -> list[str]:
    try:
        p = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True,
                           errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in p.stdout.splitlines() if line.strip()] if p.returncode == 0 else []


def _require(root: Path, as_json: bool) -> str | int:
    exe = find_codex(root)
    if exe:
        return exe
    return finish("CODEX_NOT_FOUND", EXIT_INFRA, [
        "CODEX_NOT_FOUND: the Codex CLI is not installed or not on PATH (npm install -g @openai/codex, then "
        "'codex login'), or set 'codexPath' in ludovanta.local.json / CODEX_PATH.",
        "Do the task yourself or leave it for a machine with Codex; do not change the task's agent silently."],
        {}, as_json)


def run_task(root: Path, task_id: str, timeout: int, model: str | None, as_json: bool) -> int:
    exe = _require(root, as_json)
    if isinstance(exe, int):
        return exe
    settings = _settings(root)
    plan = plan_mod.Plan(root)
    task = plan.by_id.get(task_id)
    if not task:
        raise LudovantaError(f"task {task_id} not found")
    if not task["criteria"]:
        return finish("NO_CRITERIA", EXIT_PROBLEMS, [f"NO_CRITERIA: {task_id} has no acceptance criteria; "
                                                     "write them before giving the task to Codex."], {}, as_json)
    prompt, result, log = _work_files(root, task_id)
    brief = plan_mod.task_brief(root, task_id)
    prompt.write_text("\n".join(brief).replace("<claude|codex>", "codex") + "\n", encoding="utf-8", newline="\n")
    run = _run(root, exe, prompt, result, log, timeout, model or settings["model"], settings["sandbox"])
    data = {"task": task_id, **run, "changed": _changed_files(root)}
    if run["timedOut"]:
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: Codex did not finish {task_id} in {timeout} s "
                                                f"(log: {run['log']}). Check the working tree before retrying."],
                      data, as_json)
    report = _tail(result, RESULT_LINES)
    if run["exitCode"] != 0 and not report:
        return finish("CODEX_FAILED", EXIT_INFRA, [f"CODEX_FAILED: exit code {run['exitCode']} (log: {run['log']})"]
                      + [f"log: {line}" for line in _tail(log)], data, as_json)
    status = plan_mod.Plan(root).by_id.get(task_id, {}).get("status", "?")
    lines = [f"CODEX_DONE: {task_id} in {run['seconds']} s, task status now '{status}' (report: {run['result']})"]
    lines += ["report:"] + [f"  {line}" for line in report]
    if data["changed"]:
        lines += [f"working tree ({len(data['changed'])} changed):"] + [f"  {c}" for c in data["changed"][:30]]
    lines.append("Now verify it yourself before reporting to the user: review the diff, compile and run the tests "
                 "(Unity MCP in live mode), look at the result in Play mode if it is visible.")
    return finish("CODEX_DONE", EXIT_OK, lines, data, as_json)


def generate_image(root: Path, description: str, out: str, timeout: int, as_json: bool) -> int:
    exe = _require(root, as_json)
    if isinstance(exe, int):
        return exe
    settings = _settings(root)
    target = (root / out).resolve()
    if root.resolve() not in target.parents:
        raise LudovantaError("--out must be a path inside the project (for example Art/References/hero.png)")
    rel = relpath(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat().st_mtime if target.is_file() else None
    prompt, result, log = _work_files(root, "image")
    prompt.write_text(
        "Generate one image with your built-in image generation ($imagegen).\n\n"
        f"Save it into this project at exactly this path: `{rel}` (create the folders if needed, overwrite the file "
        "if it exists). Do not change any other file.\n\n"
        f"Image description:\n\n{description.strip()}\n", encoding="utf-8", newline="\n")
    run = _run(root, exe, prompt, result, log, timeout, settings["model"], "workspace-write")
    data = {"image": rel, **run}
    if run["timedOut"]:
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: no image after {timeout} s (log: {run['log']})."],
                      data, as_json)
    fresh = target.is_file() and (before is None or target.stat().st_mtime > before)
    if not fresh or not target.read_bytes()[:8].startswith(IMAGE_SIGNATURES):
        return finish("IMAGE_NOT_CREATED", EXIT_PROBLEMS, [f"IMAGE_NOT_CREATED: {rel} was not written "
                                                           f"(Codex exit code {run['exitCode']}, log: {run['log']})"]
                      + [f"log: {line}" for line in _tail(log)], data, as_json)
    lines = [f"IMAGE_CREATED: {rel} ({target.stat().st_size // 1024} KB, {run['seconds']} s)"]
    if rel.startswith("Assets/"):
        lines.append("note: it is under Assets/, so Unity imports it as a texture; references belong outside "
                     "Assets/ (for example Art/References/).")
    return finish("IMAGE_CREATED", EXIT_OK, lines, data, as_json)
