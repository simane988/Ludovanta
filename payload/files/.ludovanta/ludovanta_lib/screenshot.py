"""screenshot: what the player sees, as PNG files an agent can look at and attach to its report.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

The rendering is done inside Unity by the Ludovanta editor package (Packages/com.ludovanta.editor, Capture.cs), which
renders a camera into a texture and points the overlay canvases (the HUD) at that camera for the shot:
  HEADLESS  Unity in batchmode (with graphics) runs Ludovanta.Editor.Capture.Batch on a request file;
  LIVE      the open Editor picks the request file up from Temp/ludovanta/capture/, no Unity MCP needed.
The answer is a result file next to the request.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import parsers
from .common import (EXIT_INFRA, EXIT_OK, EXIT_PROBLEMS, EXIT_TIMEOUT, LudovantaError, editor_open, finish, new_log_path,
                     relpath, resolve_unity, run_unity, write_lf)

PACKAGE_REL = "Packages/com.ludovanta.editor/package.json"
SIZE_RX = re.compile(r"^(\d{2,5})x(\d{2,5})$")
LIVE_PICKUP_SECONDS = 20


def _output(root: Path, out: str | None, label: str | None, scene: str | None) -> Path:
    if out:
        path = (root / out).resolve()
        if root.resolve() not in path.parents:
            raise LudovantaError("--out must be a path inside the project")
        return path if path.suffix.lower() == ".png" else path.with_suffix(".png")
    stem = label or f"{Path(scene).stem if scene else 'shot'}-{datetime.now():%Y%m%d-%H%M%S}"
    stem = re.sub(r"[^\w.-]+", "-", stem).strip("-") or "shot"
    return root / "Logs" / "ludovanta" / "screenshots" / f"{stem}.png"


def _request(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write_lf(tmp, json.dumps(data, indent=2))
    os.replace(tmp, path)   # the Editor never sees a half-written request


def _read_result(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _report(root: Path, result: dict, how: str, seconds: float, as_json: bool) -> int:
    files = [relpath(root, f) for f in result.get("files") or []]
    data = {"files": files, "absolute": [str(Path(f).resolve()) for f in result.get("files") or []],
            "scene": result.get("scene"), "camera": result.get("camera"), "playMode": result.get("playMode"),
            "uniform": result.get("uniform"), "mode": how, "seconds": seconds}
    if not result.get("ok"):
        return finish("SCREENSHOT_FAILED", EXIT_PROBLEMS, [f"SCREENSHOT_FAILED ({how}): {result.get('error')}"],
                      data, as_json)
    size = f"{result.get('width')}x{result.get('height')}"
    lines = [f"SCREENSHOT ({how}): {len(files)} image(s), {size}, camera '{result.get('camera')}', scene "
             f"{result.get('scene') or '-'}{', Play mode' if result.get('playMode') else ', edit mode'}, {seconds}s"]
    lines += [f"  {rel}  ({absolute})" for rel, absolute in zip(files, data["absolute"])]
    if result.get("uniform"):
        lines.append("warning: an image is one flat colour: the camera sees nothing yet (try --play, another --camera) "
                     "or rendering does not work in batchmode for this render pipeline (try in LIVE mode).")
    lines.append("Look at the images yourself before you describe them (open the files).")
    return finish("SCREENSHOT", EXIT_OK, lines, data, as_json)


def _live(root: Path, request: dict, timeout: int, as_json: bool) -> int:
    folder = root / "Temp" / "ludovanta" / "capture"
    folder.mkdir(parents=True, exist_ok=True)
    req_path = folder / f"{request['id']}.request.json"
    result_path = folder / f"{request['id']}.result.json"
    _request(req_path, request)
    start = time.monotonic()
    while True:
        waited = time.monotonic() - start
        result = _read_result(result_path) if result_path.is_file() else None
        if result is not None:
            return _report(root, result, "LIVE, open Editor", round(waited, 1), as_json)
        if req_path.is_file() and waited > min(LIVE_PICKUP_SECONDS, timeout):
            req_path.unlink()
            return finish("EDITOR_NOT_ANSWERING", EXIT_INFRA, [
                f"EDITOR_NOT_ANSWERING: the open Unity Editor did not pick up the request in {round(waited)} s.",
                f"Is {PACKAGE_REL} in the project ('update' installs it) and compiled? Is the Editor busy (compiling, "
                "importing, a modal dialog)? Try again, or capture through a Unity MCP tool."], {}, as_json)
        if waited > timeout:
            break
        time.sleep(0.25)
    return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: the Editor took the request but gave no picture in {timeout} s "
                                            "(see the Editor console)."], {}, as_json)


def _batch(root: Path, request: dict, timeout: int, as_json: bool) -> int:
    unity = resolve_unity(root)
    folder = root / "Logs" / "ludovanta" / "capture"
    folder.mkdir(parents=True, exist_ok=True)
    req_path = folder / f"{request['id']}.request.json"
    result_path = folder / f"{request['id']}.result.json"
    _request(req_path, request)
    log = new_log_path(root, "screenshot")
    rel_log = relpath(root, log)
    # No -nographics (the camera must render) and no -quit (Capture.Batch exits when the picture is written).
    run = run_unity(unity, ["-batchmode", "-projectPath", str(root), "-executeMethod", "Ludovanta.Editor.Capture.Batch",
                            "-ludovantaRequest", str(req_path), "-logFile", str(log)], timeout)
    result = _read_result(result_path) if result_path.is_file() else None
    if result is not None:
        return _report(root, result, "HEADLESS, batchmode", run["seconds"], as_json)
    data = {"log": rel_log, "seconds": run["seconds"]}
    if run["timed_out"]:
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: no picture after {timeout} s (log: {rel_log})."], data, as_json)
    errors = [m for m in parsers.compiler_messages(log, root) if m["severity"] == "error"]
    if errors:
        lines = [f"COMPILE_FAILED: the project does not compile, no screenshot (log: {rel_log})"]
        return finish("COMPILE_FAILED", EXIT_PROBLEMS, lines + [parsers.format_compiler_message(e) for e in errors[:10]],
                      data, as_json)
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if "Ludovanta.Editor.Capture" in text and re.search(r"(?i)could not be found|executeMethod.*(fail|not found)", text):
        return finish("PACKAGE_MISSING", EXIT_INFRA, [f"PACKAGE_MISSING: Unity does not know Ludovanta.Editor.Capture: "
                                                      f"{PACKAGE_REL} is missing or not compiled; run 'update' "
                                                      f"(log: {rel_log})."], data, as_json)
    reasons = parsers.known_problems(log)
    return finish("UNITY_FAILED", EXIT_INFRA, [f"UNITY_FAILED: Unity exited with code {run['exit_code']} without a "
                                               f"picture (log: {rel_log})"]
                  + [f"reason: {r}" for r in reasons] + [f"log: {t}" for t in ([] if reasons else parsers.log_tail(log))],
                  data, as_json)


def screenshot(root: Path, scene: str | None, camera: str | None, play: float, frames: int, every: float, size: str,
               out: str | None, label: str | None, timeout: int | None, as_json: bool) -> int:
    m = SIZE_RX.match(size.lower())
    if not m:
        raise LudovantaError("--size must look like 1280x720")
    if frames < 1 or frames > 60:
        raise LudovantaError("--frames must be between 1 and 60")
    if scene and not (root / scene).is_file():
        raise LudovantaError(f"scene not found: {scene} (a path like Assets/Scenes/City.unity)")
    if not (root / PACKAGE_REL).is_file():
        return finish("PACKAGE_MISSING", EXIT_INFRA, [f"PACKAGE_MISSING: {PACKAGE_REL} is not in the project: run "
                                                      "'python3 .ludovanta/ludovanta.py update'."], {}, as_json)
    path = _output(root, out, label, scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    request = {"id": f"{now:%Y%m%d-%H%M%S}-{now.microsecond:06d}", "scene": (scene or "").replace("\\", "/"),
               "camera": camera or "", "output": str(path), "width": int(m.group(1)), "height": int(m.group(2)),
               "play": max(0.0, play), "frames": frames, "every": max(0.02, every)}
    busy = play + frames * every
    if editor_open(root):
        return _live(root, request, timeout or int(60 + busy), as_json)
    return _batch(root, request, timeout or int(900 + busy), as_json)
