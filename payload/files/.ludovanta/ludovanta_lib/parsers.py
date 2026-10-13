"""Parsers for Unity logs and NUnit3 test results.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import read_text, relpath

_COMPILER_RX = re.compile(
    r"(?P<file>(?:[A-Za-z]:)?[^:()]*?\.cs)\((?P<line>\d+),(?P<col>\d+)\): "
    r"(?P<sev>error|warning) (?P<code>[A-Z]+\d+): (?P<msg>.+)$")
_LICENSE_RX = re.compile(
    r"(?im)^.*(licen[cs]e.*(no valid|not (be )?activ|fail|expired|invalid)|(no valid|invalid|expired).*licen[cs]e).*$")
_ANOTHER_INSTANCE_RX = re.compile(
    r"another Unity instance is running with this project open|"
    r"Multiple Unity instances cannot open the same project")
_STACK_RX = re.compile(r"in (?P<path>.+?\.cs):(?:line )?(?P<line>\d+)")


def compiler_messages(log_path: Path, root) -> list[dict]:
    """Compiler errors/warnings from a Unity log, deduplicated (Unity repeats them)."""
    if not Path(log_path).is_file():
        return []
    seen = set()
    result = []
    for line in read_text(log_path).splitlines():
        m = _COMPILER_RX.search(line)
        if not m:
            continue
        item = {
            "severity": m["sev"],
            "file": relpath(root, m["file"].strip()),
            "line": int(m["line"]),
            "column": int(m["col"]),
            "code": m["code"],
            "message": m["msg"].strip(),
        }
        key = tuple(item.values())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def format_compiler_message(msg: dict) -> str:
    return f"{msg['file']}:{msg['line']}:{msg['column']} {msg['code']} {msg['message']}"


def known_problems(log_path: Path) -> list[str]:
    """Environment problems worth explaining instead of dumping the log."""
    if not Path(log_path).is_file():
        return ["Unity produced no log file (crashed on start or wrong path?)."]
    text = read_text(log_path)
    found = []
    if _ANOTHER_INSTANCE_RX.search(text):
        found.append("Another Unity instance (Editor or batchmode run) has this project open.")
    m = _LICENSE_RX.search(text)
    if m:
        found.append(f"Unity license problem: {m.group(0).strip()} - open Unity Hub, sign in and check the license.")
    return found


def log_tail(log_path: Path, count: int = 15) -> list[str]:
    if not Path(log_path).is_file():
        return []
    lines = read_text(log_path).splitlines()
    interesting = [l for l in lines if re.search(r"(?i)\berror\b|exception|aborting|fatal", l)]
    return (interesting or lines)[-count:]


def stack_locations(stack: str, root, limit: int = 3) -> list[str]:
    """'Assets/...cs:line' entries of a stack trace that point into the project."""
    result = []
    for line in (stack or "").splitlines():
        m = _STACK_RX.search(line)
        if m:
            rel = relpath(root, m["path"].strip())
            if rel.startswith(("Assets/", "Packages/")):
                result.append(f"{rel}:{m['line']}")
        if len(result) >= limit:
            break
    return result


def _categories(el) -> set[str]:
    return {p.get("value", "") for p in el.findall("properties/property") if p.get("name") == "Category"}


def _cases(el, inherited: set[str], out: list) -> None:
    """Test cases with their categories, including those set on the fixture or the assembly."""
    cats = inherited | _categories(el)
    if el.tag == "test-case":
        out.append((el, cats))
        return
    for child in el:
        if child.tag in ("test-suite", "test-case"):
            _cases(child, cats, out)


def _float(value: str | None) -> float:
    """Unity writes durations in the system locale: '0,0331029' on a Russian Windows."""
    try:
        return float((value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def test_results(xml_path: Path, root) -> dict:
    tree = ET.parse(str(xml_path))
    run = tree.getroot()
    if run.tag != "test-run":
        raise ValueError(f"Not an NUnit3 result file: {xml_path}")
    found: list = []
    _cases(run, set(), found)
    cases, failures = [], []
    for case, cats in found:
        item = {"name": case.get("fullname", ""), "result": case.get("result", ""), "categories": sorted(cats),
                "duration": round(_float(case.get("duration")), 3)}
        cases.append(item)
        if item["result"] != "Failed":
            continue
        failures.append({
            "name": item["name"],
            "categories": item["categories"],
            "message": (case.findtext("failure/message") or "").strip(),
            "locations": stack_locations(case.findtext("failure/stack-trace") or "", root),
        })
    return {
        "result": run.get("result", ""),
        "total": int(run.get("total", "0")),
        "passed": int(run.get("passed", "0")),
        "failed": int(run.get("failed", "0")),
        "skipped": int(run.get("skipped", "0")),
        "inconclusive": int(run.get("inconclusive", "0")),
        "duration": round(_float(run.get("duration")), 1),
        "failures": failures,
        "cases": cases,
    }
