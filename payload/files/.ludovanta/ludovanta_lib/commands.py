"""Ludovanta commands that inspect, compile, test and validate the Unity project.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import parsers
from .common import (EXIT_EDITOR_OPEN, EXIT_INFRA, EXIT_OK, EXIT_PROBLEMS, EXIT_TIMEOUT, IS_WINDOWS, LudovantaError,
                     editor_open, finish, new_log_path, read_text, relpath, resolve_unity, run_unity, unity_version)

EDITOR_OPEN_LINE = "EDITOR_OPEN: Unity (Editor or another batchmode run) has this project open, batchmode cannot run."


# --- status ------------------------------------------------------------------------

def status(root: Path, as_json: bool) -> int:
    platform_version = "unknown"
    lock = root / ".ludovanta" / "lock.json"
    if lock.is_file():
        try:
            platform_version = json.loads(read_text(lock)).get("version", "unknown")
        except ValueError:
            platform_version = "unreadable lock.json"

    try:
        unity, unity_note = str(resolve_unity(root)), ""
    except LudovantaError as e:
        unity, unity_note = None, str(e)
    is_open = editor_open(root)
    mode = "LIVE" if is_open else "HEADLESS"
    manifest = root / "Packages" / "manifest.json"
    has_mcp = manifest.is_file() and '"com.unity.ai.assistant"' in read_text(manifest)

    lines = [f"MODE: {mode}", f"project: {root}", f"ludovanta: {platform_version}", f"unity: {unity_version(root)}"]
    lines.append(f"unity editor: {unity}" if unity else f"unity editor: NOT FOUND - {unity_note}")
    if is_open:
        lines.append("editor: open on this project -> use Unity MCP tools; ludovanta commands that start Unity return EDITOR_OPEN.")
    else:
        lines.append("editor: not open -> use ludovanta commands (batchmode).")
    lines.append("unity mcp package (com.unity.ai.assistant): " +
                 ("installed" if has_mcp else "not installed - live mode via MCP is unavailable"))
    from .codex import find_codex
    codex = find_codex(root)
    lines.append(f"codex cli: {codex}" if codex else "codex cli: not found - tasks for agent 'codex' cannot be delegated here")
    data = {"project": str(root), "platformVersion": platform_version, "unityVersion": unity_version(root),
            "unityEditor": unity, "editorOpen": is_open, "mode": mode, "mcpPackage": has_mcp, "codex": codex}
    return finish(mode, EXIT_OK, lines, data, as_json)


# --- compile ------------------------------------------------------------------------

def _unity_failed(status_name: str, headline: str, log: Path, data: dict, as_json: bool) -> int:
    problems = parsers.known_problems(log)
    data["problems"] = problems
    lines = [headline]
    lines += [f"reason: {p}" for p in problems] or [f"log: {t}" for t in parsers.log_tail(log)]
    return finish(status_name, EXIT_INFRA, lines, data, as_json)


def compile_project(root: Path, timeout: int, max_items: int, warnings: bool, as_json: bool) -> int:
    if editor_open(root):
        return finish("EDITOR_OPEN", EXIT_EDITOR_OPEN, [
            EDITOR_OPEN_LINE,
            "Live mode: check compilation through the Unity MCP tools (Editor console), or ask the user to close the Editor."],
            {}, as_json)

    unity = resolve_unity(root)
    log = new_log_path(root, "compile")
    rel_log = relpath(root, log)
    run = run_unity(unity, ["-batchmode", "-nographics", "-quit", "-projectPath", str(root), "-logFile", str(log)],
                    timeout)
    messages = parsers.compiler_messages(log, root)
    errors = [m for m in messages if m["severity"] == "error"]
    warns = [m for m in messages if m["severity"] == "warning"]
    data = {"seconds": run["seconds"], "log": rel_log, "errors": errors, "warnings": warns if warnings else []}

    if run["timed_out"]:
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: Unity did not finish in {timeout} s (log: {rel_log})."],
                      data, as_json)
    if errors:
        lines = [f"COMPILE_FAILED: {len(errors)} error(s), {len(warns)} warning(s) in {run['seconds']}s (log: {rel_log})"]
        lines += [parsers.format_compiler_message(e) for e in errors[:max_items]]
        if len(errors) > max_items:
            lines.append(f"... {len(errors) - max_items} more error(s) in the log")
        return finish("COMPILE_FAILED", EXIT_PROBLEMS, lines, data, as_json)
    if run["exit_code"] != 0:
        return _unity_failed("UNITY_FAILED", f"UNITY_FAILED: Unity exited with code {run['exit_code']} after "
                             f"{run['seconds']}s without compiler errors (log: {rel_log})", log, data, as_json)

    lines = [f"COMPILE_OK: 0 errors, {len(warns)} warning(s) in {run['seconds']}s"]
    if warnings:
        lines += [parsers.format_compiler_message(w) for w in warns[:max_items]]
    return finish("COMPILE_OK", EXIT_OK, lines, data, as_json)


# --- test ---------------------------------------------------------------------------

def run_tests(root: Path, platform: str, test_filter: str | None, category: str | None, timeout: int,
              max_items: int, as_json: bool) -> int:
    if editor_open(root):
        return finish("EDITOR_OPEN", EXIT_EDITOR_OPEN, [
            EDITOR_OPEN_LINE,
            "Live mode: run tests through a Unity MCP tool if one is available, otherwise ask the user to run them "
            "in the Test Runner window or to close the Editor."], {}, as_json)

    unity = resolve_unity(root)
    log = new_log_path(root, f"test-{platform.lower()}")
    xml_path = log.with_suffix(".xml")
    rel_log = relpath(root, log)
    args = ["-batchmode", "-projectPath", str(root), "-runTests", "-testPlatform", platform,
            "-testResults", str(xml_path), "-logFile", str(log)]
    if platform == "EditMode":
        args.append("-nographics")
    if test_filter:
        args += ["-testFilter", test_filter]
    if category:
        args += ["-testCategory", category]

    run = run_unity(unity, args, timeout)
    data: dict = {"platform": platform, "seconds": run["seconds"], "log": rel_log}

    if run["timed_out"]:
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: tests did not finish in {timeout} s (log: {rel_log})."],
                      data, as_json)
    if not xml_path.is_file():
        errors = [m for m in parsers.compiler_messages(log, root) if m["severity"] == "error"]
        if errors:
            data["errors"] = errors
            lines = [f"COMPILE_FAILED: tests did not run, {len(errors)} compiler error(s) (log: {rel_log})"]
            lines += [parsers.format_compiler_message(e) for e in errors[:max_items]]
            return finish("COMPILE_FAILED", EXIT_PROBLEMS, lines, data, as_json)
        return _unity_failed("UNITY_FAILED", f"UNITY_FAILED: no test results produced, Unity exit code "
                             f"{run['exit_code']} after {run['seconds']}s (log: {rel_log})", log, data, as_json)

    r = parsers.test_results(xml_path, root)
    data.update({"total": r["total"], "passed": r["passed"], "failed": r["failed"], "skipped": r["skipped"],
                 "failures": r["failures"], "results": relpath(root, xml_path)})
    counts = f"{r['failed']} failed, {r['passed']} passed, {r['skipped']} skipped, total {r['total']}"

    if r["failed"]:
        lines = [f"TESTS_FAILED ({platform}): {counts} in {run['seconds']}s (log: {rel_log})"]
        for f in r["failures"][:max_items]:
            lines.append(f"- {f['name']}")
            message_lines = [m.strip() for m in f["message"].splitlines() if m.strip()]
            lines += [f"    {m}" for m in message_lines[:6]]
            lines += [f"    at {loc}" for loc in f["locations"]]
        if len(r["failures"]) > max_items:
            lines.append(f"... {len(r['failures']) - max_items} more failure(s), see {data['results']}")
        return finish("TESTS_FAILED", EXIT_PROBLEMS, lines, data, as_json)
    if r["total"] == 0:
        what = "no tests matched the filter" if (test_filter or category) else "no tests found"
        return finish("NO_TESTS", EXIT_OK, [f"NO_TESTS ({platform}): {what} in {run['seconds']}s. "
                                            "Check the test assembly (.asmdef) setup or the filter."], data, as_json)
    return finish("TESTS_PASSED", EXIT_OK, [f"TESTS_PASSED ({platform}): {counts} in {run['seconds']}s"], data, as_json)


# --- validate-assets -----------------------------------------------------------------

_GUID_RX = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$")


def _unity_ignored(name: str) -> bool:
    """Unity does not import (and does not create .meta for) these names."""
    return name.startswith(".") or name.endswith("~") or name.lower() == "cvs" or name.lower().endswith(".tmp")


def _meta_guid(path: Path) -> str | None:
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            m = _GUID_RX.match(line.strip())
            if m:
                return m.group(1).lower()
            if i >= 10:
                break
    return None


def validate_assets(root: Path, roots: list[str], max_items: int, as_json: bool) -> int:
    fold = (lambda s: s.casefold()) if IS_WINDOWS else (lambda s: s)
    missing, orphans, no_guid = [], [], []
    guids: dict[str, list[str]] = {}

    for top in roots:
        start = root / top
        if not start.is_dir():
            print(f"warning: root '{top}' not found, skipped")
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            names = {fold(n) for n in dirnames + filenames}
            for d in list(dirnames):
                if _unity_ignored(d):
                    dirnames.remove(d)       # do not descend into ignored folders
                elif fold(d + ".meta") not in names:
                    missing.append(relpath(root, os.path.join(dirpath, d)) + "/")
            for f in filenames:
                if _unity_ignored(f):
                    continue
                full = os.path.join(dirpath, f)
                if f.lower().endswith(".meta"):
                    asset = f[:-5]
                    if fold(asset) not in names or _unity_ignored(asset):
                        orphans.append(relpath(root, full))
                    guid = _meta_guid(Path(full))
                    if guid:
                        guids.setdefault(guid, []).append(relpath(root, full))
                    else:
                        no_guid.append(relpath(root, full))
                elif fold(f + ".meta") not in names:
                    missing.append(relpath(root, full))

    duplicates = [{"guid": g, "metas": sorted(p)} for g, p in sorted(guids.items()) if len(p) > 1]
    missing, orphans, no_guid = sorted(missing), sorted(orphans), sorted(no_guid)
    data = {"missingMeta": missing, "orphanMeta": orphans, "noGuid": no_guid, "duplicateGuids": duplicates}

    if not (missing or orphans or no_guid or duplicates):
        checked = sum(len(p) for p in guids.values())
        return finish("ASSETS_OK", EXIT_OK, [f"ASSETS_OK: {checked} .meta file(s) checked under {', '.join(roots)}"],
                      data, as_json)

    items = ([f"missing meta: {p}" for p in missing] + [f"orphan meta: {p}" for p in orphans] +
             [f"meta without guid: {p}" for p in no_guid] +
             [f"duplicate guid {d['guid']}: {', '.join(d['metas'])}" for d in duplicates])
    lines = [f"ASSETS_INVALID: {len(missing)} missing .meta, {len(orphans)} orphan .meta, "
             f"{len(duplicates)} duplicate GUID(s), {len(no_guid)} .meta without GUID"]
    lines += items[:max_items]
    if len(items) > max_items:
        lines.append(f"... {len(items) - max_items} more, use --json for the full list")
    if missing:
        lines.append("hint: .meta files are created by Unity on import. In headless mode run 'ludovanta.py compile' first; "
                     "never write .meta files by hand.")
    return finish("ASSETS_INVALID", EXIT_PROBLEMS, lines, data, as_json)
