"""test-audit: find tests that break for the wrong reasons, without running Unity.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Tests are the agents' self-check. A test suite that "breaks all the time" usually has a few causes, and each leaves
traces that can be found without Unity:
  * the test code: private members through reflection, real-time waits, unseeded randomness, exact float comparison,
    scene lookups by name, ignored and quarantined tests (heuristics: findings are to check, not proven bugs);
  * earlier runs (Logs/ludovanta/test-*.xml): slow tests, tests that failed in many recent runs;
  * git history: test files rewritten again and again, a sign that expectations follow the code;
  * game code outside any .asmdef, which tests cannot reference at all.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from . import parsers
from .common import EXIT_OK, NO_WINDOW, finish, read_text, relpath

TEST_ATTR_RX = re.compile(r"\[\s*(?:NUnit\.Framework\.)?(Test|UnityTest|TestCase|TestCaseSource)\b")
SLOW_SECONDS = {"EditMode": 0.5, "PlayMode": 10.0}
FAILED_RUNS_MIN = 3
CHURN_MIN = 3
CHURN_DAYS = 30

# kind, what it means, pattern. Heuristics over single lines, comments stripped.
SMELLS = [
    ("private", "reaches private members through reflection: tests implementation, breaks on refactor",
     re.compile(r"BindingFlags\.NonPublic|\.GetField\s*\(|\.GetMethod\s*\(\s*\"")),
    ("realtime", "waits in real time: slow and flaky (inject time or wait frames instead)",
     re.compile(r"\bWaitForSeconds(?:Realtime)?\s*\(|Thread\.Sleep\s*\(|Task\.Delay\s*\(")),
    ("scene", "finds objects by name or type: breaks when the scene changes (pass references in)",
     re.compile(r"GameObject\.Find\s*\(|\bFind(?:Objects?OfType|FirstObjectByType|AnyObjectByType|ObjectsByType)\b")),
    ("ignored", "is ignored ([Ignore]): checks nothing, fix or delete it",
     re.compile(r"[\[,]\s*Ignore\b")),
]
RANDOM_RX = re.compile(r"\bRandom\.(?:Range|value|insideUnit\w+|onUnitSphere|rotation\w*)\b|new\s+(?:System\.)?Random\s*\(\s*\)")
SEEDED_RX = re.compile(r"Random\.InitState\s*\(|Random\.state\s*=|new\s+(?:System\.)?Random\s*\(\s*[^)\s]")
FLOAT_LITERAL_RX = re.compile(r"^-?\d+(?:\.\d+f?|f)$")
ARE_EQUAL_RX = re.compile(r"Assert\.AreEqual\s*\((.*)\)\s*;")
EQUAL_TO_RX = re.compile(r"Is\.EqualTo\s*\(\s*-?\d+(?:\.\d+f?|f)\s*\)(?!\s*\.Within)")
QUARANTINE_RX = re.compile(r"Category\s*\(\s*\"Flaky\"\s*\)")
KINDS = {k: what for k, what, _ in SMELLS}
KINDS.update({"random": "uses randomness without a fixed seed: flaky",
              "float": "compares floats exactly: flaky (use a tolerance, .Within(...))"})


def _ignored(name: str) -> bool:
    return name.startswith(".") or name.endswith("~")


def _split_args(text: str) -> list[str]:
    args, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return args + [cur.strip()] if cur.strip() else args


class Assemblies:
    """Which assembly (and so which test platform) a script belongs to: the nearest .asmdef / .asmref above it."""

    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[Path, dict | None] = {}

    def owner(self, folder: Path) -> dict | None:
        if folder in self.cache:
            return self.cache[folder]
        found = None
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        asmdef = next((n for n in names if n.endswith(".asmdef")), None)
        if asmdef:
            try:
                data = json.loads(read_text(folder / asmdef))
            except (OSError, ValueError):
                data = {}
            found = {"name": data.get("name") or asmdef[:-7],
                     "editorOnly": data.get("includePlatforms") == ["Editor"]}
        elif any(n.endswith(".asmref") for n in names):
            found = {"name": "(asmref)", "editorOnly": None}
        elif folder != self.root / "Assets" and self.root / "Assets" in folder.parents:
            found = self.owner(folder.parent)
        self.cache[folder] = found
        return found


def _scan(root: Path) -> dict:
    assemblies = Assemblies(root)
    files, findings, loose = [], {k: [] for k in KINDS}, {}
    quarantined = ignored = 0
    for dirpath, dirnames, filenames in os.walk(root / "Assets"):
        dirnames[:] = [d for d in dirnames if not _ignored(d)]
        folder = Path(dirpath)
        for name in filenames:
            if not name.endswith(".cs"):
                continue
            path = folder / name
            text = read_text(path)
            rel = relpath(root, path)
            owner = assemblies.owner(folder)
            in_editor = "/Editor/" in "/" + rel
            if not TEST_ATTR_RX.search(text):
                if owner is None and not in_editor:
                    top = "/".join(rel.split("/")[:2])
                    loose[top] = loose.get(top, 0) + 1
                continue
            editor_only = owner["editorOnly"] if owner and owner["editorOnly"] is not None else in_editor
            platform = "EditMode" if editor_only else "PlayMode"
            lines = [line.split("//")[0] for line in text.splitlines()]
            count = sum(len(TEST_ATTR_RX.findall(line)) for line in lines)
            files.append({"file": rel, "platform": platform, "tests": count})
            quarantined += sum(1 for line in lines if QUARANTINE_RX.search(line))
            for i, line in enumerate(lines, 1):
                for kind, _, rx in SMELLS:
                    if rx.search(line):
                        findings[kind].append({"file": rel, "line": i, "code": line.strip()[:100]})
                        ignored += kind == "ignored"
                m = ARE_EQUAL_RX.search(line)
                args = _split_args(m.group(1)) if m else []
                if (len(args) == 2 and any(FLOAT_LITERAL_RX.match(a) for a in args)) or EQUAL_TO_RX.search(line):
                    findings["float"].append({"file": rel, "line": i, "code": line.strip()[:100]})
            if not any(SEEDED_RX.search(line) for line in lines):
                hits = [i for i, line in enumerate(lines, 1) if RANDOM_RX.search(line)]
                if hits:
                    findings["random"].append({"file": rel, "line": hits[0], "code": lines[hits[0] - 1].strip()[:100]})
    return {"files": files, "findings": findings, "loose": loose, "quarantined": quarantined, "ignored": ignored}


def _history(root: Path, max_items: int) -> dict:
    """Earlier 'test' runs: the slowest tests of the latest run per platform, tests that failed in many runs."""
    folder = root / "Logs" / "ludovanta"
    runs = []
    for path in sorted(folder.glob("test-*.xml")) if folder.is_dir() else []:
        try:
            r = parsers.test_results(path, root)
        except (ET.ParseError, ValueError, OSError):
            continue
        platform = "PlayMode" if path.name.startswith("test-playmode") else "EditMode"
        runs.append((platform, path, r))
    slow, latest = [], {}
    for platform, path, r in runs:
        latest[platform] = (path, r)
    for platform, (path, r) in sorted(latest.items()):
        limit = SLOW_SECONDS[platform]
        cases = sorted((c for c in r["cases"] if c["duration"] >= limit), key=lambda c: -c["duration"])
        slow += [{"name": c["name"], "platform": platform, "seconds": c["duration"]} for c in cases[:max_items]]
    counts: dict[str, list[int]] = {}
    for _, _, r in runs:
        for c in r["cases"]:
            if c["result"] in ("Passed", "Failed"):
                n = counts.setdefault(c["name"], [0, 0])
                n[0] += 1
                n[1] += c["result"] == "Failed"
    failing = sorted(({"name": k, "failed": v[1], "runs": v[0]} for k, v in counts.items() if v[1] >= FAILED_RUNS_MIN),
                     key=lambda t: (-t["failed"], t["name"]))
    durations = {p: r["duration"] for p, (_, r) in latest.items()}
    return {"runs": len(runs), "slow": slow, "failing": failing[:max_items], "durations": durations}


def _churn(root: Path, test_files: set[str], max_items: int) -> list[dict]:
    """Test files changed in many commits recently: expectations may be following the code."""
    if not test_files:
        return []
    try:
        p = subprocess.run(["git", "-C", str(root), "log", f"--since={CHURN_DAYS}.days", "--format=%x00",
                            "--name-only", "--", "Assets"], capture_output=True, text=True, errors="replace",
                           timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
    counts: dict[str, int] = {}
    for commit in p.stdout.split("\x00"):
        for name in {line.strip() for line in commit.splitlines() if line.strip()}:
            if name in test_files:
                counts[name] = counts.get(name, 0) + 1
    rows = sorted(({"file": f, "commits": n} for f, n in counts.items() if n >= CHURN_MIN), key=lambda r: -r["commits"])
    return rows[:max_items]


def audit(root: Path, max_items: int, as_json: bool) -> int:
    scan = _scan(root)
    history = _history(root, max_items)
    churn = _churn(root, {f["file"] for f in scan["files"]}, max_items)
    files = scan["files"]
    by_platform = {p: sum(f["tests"] for f in files if f["platform"] == p) for p in ("EditMode", "PlayMode")}
    total = sum(by_platform.values())
    smells = {k: v for k, v in scan["findings"].items() if v}
    loose = sorted(scan["loose"].items(), key=lambda kv: -kv[1])
    data = {"testFiles": files, "tests": total, "byPlatform": by_platform, "quarantined": scan["quarantined"],
            "findings": smells, "slow": history["slow"], "oftenFailing": history["failing"], "churn": churn,
            "runsRead": history["runs"], "lastRunSeconds": history["durations"],
            "scriptsOutsideAsmdef": dict(loose)}

    count = sum(len(v) for v in smells.values()) + len(history["slow"]) + len(history["failing"]) + len(churn)
    if not files:
        lines = ["TEST_AUDIT: no tests in Assets/. Cover the rules that can break silently with EditMode tests "
                 "(skill ludovanta-unity-test)."]
    else:
        lines = [f"TEST_AUDIT: about {total} test(s) in {len(files)} file(s): {by_platform['EditMode']} EditMode, "
                 f"{by_platform['PlayMode']} PlayMode; {scan['quarantined']} quarantined, {scan['ignored']} ignored; "
                 f"{count} finding(s) to check"]
    if by_platform["PlayMode"] > by_platform["EditMode"]:
        lines.append("most tests are PlayMode (slow, more flaky): move checks of logic to EditMode, keep PlayMode for "
                     "the key scenarios")
    for kind, items in smells.items():
        lines.append(f"{KINDS[kind]}: {len(items)}")
        lines += [f"  {f['file']}:{f['line']}  {f['code']}" for f in items[:max_items]]
    if history["slow"]:
        last = ", ".join(f"{p} {s}s" for p, s in sorted(history["durations"].items()))
        lines.append(f"slow tests in the last runs ({last}):")
        lines += [f"  {s['name']} ({s['platform']}) {s['seconds']}s" for s in history["slow"]]
    if history["failing"]:
        lines.append(f"failed in {FAILED_RUNS_MIN}+ of the last {history['runs']} runs (brittle or flaky; check with "
                     "'test --filter <name> --repeat 5'):")
        lines += [f"  {t['name']}: failed {t['failed']} of {t['runs']}" for t in history["failing"]]
    if churn:
        lines.append(f"test files changed in {CHURN_MIN}+ commits in {CHURN_DAYS} days (are the expectations "
                     "following the code instead of the rules?):")
        lines += [f"  {c['file']}: {c['commits']} commits" for c in churn]
    if loose:
        n = sum(v for _, v in loose)
        lines.append(f"{n} script(s) outside any .asmdef (Assembly-CSharp): tests cannot reference them; "
                     "third-party folders are fine, game logic is not: "
                     + ", ".join(f"{k} ({v})" for k, v in loose[:5]))
    if count:
        lines.append("next: fix these yourself, no questions to the user (skill ludovanta-unity-test, 'Audit').")
    return finish("TEST_AUDIT", EXIT_OK, lines, data, as_json)
