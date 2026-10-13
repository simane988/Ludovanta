"""Ludovanta commands that inspect, compile, test and validate the Unity project.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import parsers, testgate
from .common import (EXIT_EDITOR_OPEN, EXIT_INFRA, EXIT_OK, EXIT_PROBLEMS, EXIT_TIMEOUT, IS_WINDOWS, LudovantaError,
                     editor_open, finish, load_config, new_log_path, read_text, relpath, resolve_unity, run_unity,
                     unity_version)

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
    targets = [str(t).strip("/") for t in load_config(root).get("skillTargets") or [".claude/skills", ".agents/skills"]]
    if codex and ".agents/skills" not in targets:
        lines.append("codex skills: Codex does not see the ludovanta-* skills - add \".agents/skills\" to "
                     "\"skillTargets\" in ludovanta.json and run 'update'")
    from .orca import available
    orca_exe, orca_note = available(root)
    lines.append("orca: running -> executors go to Orca worktrees ('worker start')" if orca_exe
                 else f"orca: not available ({orca_note}) -> executors are subagents or 'codex run'")
    data = {"project": str(root), "platformVersion": platform_version, "unityVersion": unity_version(root),
            "unityEditor": unity, "editorOpen": is_open, "mode": mode, "mcpPackage": has_mcp, "codex": codex,
            "orca": bool(orca_exe)}
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
# Tests are the agents' self-check. Two things keep a flaky test from sending an agent in circles:
#   * quarantine: tests in the NUnit category 'Flaky' still run and are reported, but their failures do not fail the run;
#   * rerun: failed tests run once more; one that passes with no code change is flaky, not broken by the change.

QUARANTINE = "Flaky"
RERUN_MAX = 5   # more failures than this are almost never flakiness: do not spend another Unity start on them


def _run_tests_once(root: Path, unity: Path, platform: str, test_filter: str | None, category: str | None,
                    timeout: int) -> dict:
    """One batchmode run: {'status': 'RESULTS' | 'TIMEOUT' | 'COMPILE_FAILED' | 'UNITY_FAILED', ...}."""
    log = new_log_path(root, f"test-{platform.lower()}")
    xml_path = log.with_suffix(".xml")
    args = ["-batchmode", "-projectPath", str(root), "-runTests", "-testPlatform", platform,
            "-testResults", str(xml_path), "-logFile", str(log)]
    if platform == "EditMode":
        args.append("-nographics")
    if test_filter:
        args += ["-testFilter", test_filter]
    if category:
        args += ["-testCategory", category]
    run = run_unity(unity, args, timeout)
    out = {"log": log, "relLog": relpath(root, log), "seconds": run["seconds"], "exitCode": run["exit_code"]}
    if run["timed_out"]:
        return {**out, "status": "TIMEOUT"}
    if not xml_path.is_file():
        errors = [m for m in parsers.compiler_messages(log, root) if m["severity"] == "error"]
        return {**out, "status": "COMPILE_FAILED" if errors else "UNITY_FAILED", "errors": errors}
    return {**out, "status": "RESULTS", "results": parsers.test_results(xml_path, root),
            "relResults": relpath(root, xml_path)}


def _no_results(once: dict, timeout: int, max_items: int, data: dict, as_json: bool) -> int:
    rel_log = once["relLog"]
    if once["status"] == "TIMEOUT":
        return finish("TIMEOUT", EXIT_TIMEOUT, [f"TIMEOUT: tests did not finish in {timeout} s (log: {rel_log})."],
                      data, as_json)
    if once["status"] == "COMPILE_FAILED":
        data["errors"] = once["errors"]
        lines = [f"COMPILE_FAILED: tests did not run, {len(once['errors'])} compiler error(s) (log: {rel_log})"]
        lines += [parsers.format_compiler_message(e) for e in once["errors"][:max_items]]
        return finish("COMPILE_FAILED", EXIT_PROBLEMS, lines, data, as_json)
    return _unity_failed("UNITY_FAILED", f"UNITY_FAILED: no test results produced, Unity exit code "
                         f"{once['exitCode']} after {once['seconds']}s (log: {rel_log})", once["log"], data, as_json)


def _failure_lines(failures: list[dict], max_items: int, more_in: str) -> list[str]:
    lines = []
    for f in failures[:max_items]:
        lines.append(f"- {f['name']}")
        message_lines = [m.strip() for m in f["message"].splitlines() if m.strip()]
        lines += [f"    {m}" for m in message_lines[:6]]
        lines += [f"    at {loc}" for loc in f["locations"]]
    if len(failures) > max_items:
        lines.append(f"... {len(failures) - max_items} more failure(s), see {more_in}")
    return lines


def _exact_filter(names: list[str]) -> str | None:
    """-testFilter for these tests: Unity reads each ';'-separated part as a regex. No '^': cmd.exe eats it when Unity
    is started through a .cmd wrapper."""
    if not names or any(";" in n for n in names):
        return None
    return ";".join(re.escape(n) + "$" for n in names)


def _quarantine_lines(quarantined: list[dict], failed: list[dict]) -> list[str]:
    if not quarantined:
        return []
    failed_names = {f["name"] for f in failed}
    lines = [f"quarantine: {len(quarantined)} test(s) in category '{QUARANTINE}', {len(failed_names)} failed this run "
             "(not counted; fix them when you can: skill ludovanta-unity-test, 'Flaky tests')"]
    lines += [f"  {c['name']}" + (" - failed" if c["name"] in failed_names else "") for c in quarantined[:10]]
    return lines


def run_tests(root: Path, platform: str, test_filter: str | None, category: str | None, timeout: int,
              max_items: int, as_json: bool, repeat: int = 1, rerun: bool = True) -> int:
    if editor_open(root):
        return finish("EDITOR_OPEN", EXIT_EDITOR_OPEN, [
            EDITOR_OPEN_LINE,
            "Live mode: run tests through a Unity MCP tool if one is available, otherwise leave them to the "
            "orchestrator or ask the user to close the Editor."], {}, as_json)
    unity = resolve_unity(root)
    if repeat > 1:
        return _repeat_tests(root, unity, platform, test_filter, category, timeout, max_items, as_json, repeat)

    started = time.time()

    def remember(status: str, failed: list[dict]) -> None:
        """A full run is what 'plan set --status review' checks (testgate)."""
        if not test_filter and not category:
            testgate.record(root, platform, started, status, [f["name"] for f in failed])

    once = _run_tests_once(root, unity, platform, test_filter, category, timeout)
    data: dict = {"platform": platform, "seconds": once["seconds"], "log": once["relLog"]}
    if once["status"] != "RESULTS":
        remember(once["status"], [])
        return _no_results(once, timeout, max_items, data, as_json)

    r = once["results"]
    quarantined = [c for c in r["cases"] if QUARANTINE in c["categories"]]
    q_failed = [f for f in r["failures"] if QUARANTINE in f["categories"]]
    failures = [f for f in r["failures"] if QUARANTINE not in f["categories"]]
    seconds = once["seconds"]

    flaky, notes = [], []
    if failures and rerun:
        rerun_filter = _exact_filter([f["name"] for f in failures]) if len(failures) <= RERUN_MAX else None
        if rerun_filter:
            again = _run_tests_once(root, unity, platform, rerun_filter, category, timeout)
            seconds = round(seconds + again["seconds"], 1)
            if again["status"] == "RESULTS":
                seen = {c["name"]: c["result"] for c in again["results"]["cases"]}
                flaky = [f for f in failures if seen.get(f["name"]) == "Passed"]
                failures = [f for f in failures if seen.get(f["name"]) != "Passed"]
                confirmed = sum(1 for f in failures if seen.get(f["name"]) == "Failed")
                if confirmed:
                    notes.append(f"{confirmed} of the failure(s) above failed again on a rerun: they are real")
                if confirmed < len(failures):
                    notes.append(f"note: {len(failures) - confirmed} failed test(s) were not found by the rerun filter, "
                                 "so flakiness could not be checked for them")
            else:
                notes.append(f"note: the rerun of the failed tests did not finish ({again['status']}, "
                             f"log: {again['relLog']})")

    data.update({"seconds": seconds, "total": r["total"], "passed": r["passed"], "failed": r["failed"],
                 "skipped": r["skipped"], "failures": failures, "flaky": [f["name"] for f in flaky],
                 "quarantined": [c["name"] for c in quarantined], "quarantinedFailed": [f["name"] for f in q_failed],
                 "results": once["relResults"]})
    counts = f"{r['failed']} failed, {r['passed']} passed, {r['skipped']} skipped, total {r['total']}"
    tail = notes
    if flaky:
        tail += [f"flaky: {len(flaky)} test(s) failed, then passed on a rerun with no code change: your change did not "
                 f"break them. Quarantine each with [Category(\"{QUARANTINE}\")] and go on (skill ludovanta-unity-test, "
                 "'Flaky tests'):"] + [f"  {f['name']}" for f in flaky]
    tail += _quarantine_lines(quarantined, q_failed)

    if failures:
        remember("TESTS_FAILED", failures)
        lines = [f"TESTS_FAILED ({platform}): {counts} in {seconds}s (log: {once['relLog']})"]
        lines += _failure_lines(failures, max_items, data["results"])
        return finish("TESTS_FAILED", EXIT_PROBLEMS, lines + tail, data, as_json)
    if r["total"] == 0:
        remember("NO_TESTS", [])
        what = "no tests matched the filter" if (test_filter or category) else "no tests found"
        return finish("NO_TESTS", EXIT_OK, [f"NO_TESTS ({platform}): {what} in {seconds}s. "
                                            "Check the test assembly (.asmdef) setup or the filter."], data, as_json)
    status = "TESTS_FLAKY" if flaky else "TESTS_PASSED"
    remember(status, [])
    return finish(status, EXIT_OK, [f"{status} ({platform}): {counts} in {seconds}s"] + tail, data, as_json)


def _repeat_tests(root: Path, unity: Path, platform: str, test_filter: str | None, category: str | None,
                  timeout: int, max_items: int, as_json: bool, repeat: int) -> int:
    """The same tests 'repeat' times with no change in between: a test with mixed results is flaky."""
    history: dict[str, dict] = {}
    seconds, logs = 0.0, []
    for i in range(repeat):
        once = _run_tests_once(root, unity, platform, test_filter, category, timeout)
        seconds = round(seconds + once["seconds"], 1)
        logs.append(once["relLog"])
        if once["status"] != "RESULTS":
            data = {"platform": platform, "seconds": seconds, "log": once["relLog"], "run": i + 1}
            return _no_results(once, timeout, max_items, data, as_json)
        failures = {f["name"]: f for f in once["results"]["failures"]}
        for c in once["results"]["cases"]:
            h = history.setdefault(c["name"], {"name": c["name"], "passed": 0, "failed": 0,
                                               "quarantined": QUARANTINE in c["categories"], "failure": None})
            if c["result"] == "Passed":
                h["passed"] += 1
            elif c["result"] == "Failed":
                h["failed"] += 1
                h["failure"] = failures.get(c["name"])

    tests = list(history.values())
    flaky = [t for t in tests if t["passed"] and t["failed"]]
    broken = [t for t in tests if t["failed"] and not t["passed"]]
    stable_quarantined = [t for t in tests if t["quarantined"] and t["passed"] == repeat]
    data = {"platform": platform, "repeat": repeat, "seconds": seconds, "logs": logs, "tests": len(tests),
            "flaky": [t["name"] for t in flaky], "failing": [t["name"] for t in broken],
            "stableQuarantined": [t["name"] for t in stable_quarantined]}

    def describe(t: dict) -> list[str]:
        out = [f"- {t['name']}: failed {t['failed']} of {repeat}" + (" (quarantined)" if t["quarantined"] else "")]
        if t["failure"]:
            out += [f"    {m.strip()}" for m in t["failure"]["message"].splitlines() if m.strip()][:3]
            out += [f"    at {loc}" for loc in t["failure"]["locations"][:1]]
        return out

    if any(not t["quarantined"] for t in broken):
        status, code = "TESTS_FAILED", EXIT_PROBLEMS
    elif any(not t["quarantined"] for t in flaky):
        status, code = "TESTS_FLAKY", EXIT_PROBLEMS
    else:
        status, code = "TESTS_STABLE", EXIT_OK
    lines = [f"{status} ({platform}): {len(tests)} test(s) run {repeat} times in {seconds}s: {len(flaky)} flaky, "
             f"{len(broken)} always failing"]
    if flaky:
        lines.append(f"flaky (mixed results with no code change; quarantine with [Category(\"{QUARANTINE}\")] until "
                     "fixed):")
        for t in flaky[:max_items]:
            lines += describe(t)
    if broken:
        lines.append("always failing (a real failure, not flakiness):")
        for t in broken[:max_items]:
            lines += describe(t)
    if stable_quarantined:
        lines.append(f"quarantined but passed all {repeat} runs (if the cause is fixed, remove "
                     f"[Category(\"{QUARANTINE}\")]):")
        lines += [f"  {t['name']}" for t in stable_quarantined[:max_items]]
    return finish(status, code, lines, data, as_json)


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
