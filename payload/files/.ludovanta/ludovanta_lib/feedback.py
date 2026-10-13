"""Friction log: what gets in the user's way when working with the platform and the agents.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

The log is docs/feedback-log.md in the project (committed, owned by the project): a markdown table with one row
per entry, newest at the bottom. Rows are only ever appended, and .gitattributes merges the file with
'merge=union', so entries written in parallel worktrees survive the merge.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .common import EXIT_OK, finish, relpath, write_lf

LOG_REL = "docs/feedback-log.md"
SEVERITY = {1: "annoying", 2: "slowed the work down", 3: "blocked it or needed outside help"}
ROW_RX = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|")
CELL_SPLIT_RX = re.compile(r"(?<!\\)\|")

TEMPLATE = """# Friction log

What gets in the way when working on this game with Ludovanta and the AI agents. Agents add a row when
the user asks ("запиши, что неудобно", skill `ludovanta-feedback`); people add rows by hand too. It is
read at the weekly review: `python3 .ludovanta/ludovanta.py feedback show`.

Severity: 1 annoying, 2 slowed the work down, 3 blocked it or needed outside help.

| Date | Severity | Doing | What got in the way |
|---|---|---|---|
"""


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def add(root: Path, problem: str, doing: str, severity: int) -> int:
    path = root / LOG_REL
    if path.is_file():
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="replace")
        newline = "\r\n" if "\r\n" in text else "\n"
        prefix = "" if text.endswith("\n") or not text else newline
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lf(path, TEMPLATE)
        newline, prefix = "\n", ""
    row = f"| {date.today().isoformat()} | {severity} | {_cell(doing) or '-'} | {_cell(problem)} |"
    with open(path, "ab") as f:
        f.write((prefix + row + newline).encode("utf-8"))
    return finish("FEEDBACK_ADDED", EXIT_OK, [f"FEEDBACK_ADDED: {relpath(root, path)}, severity {severity} "
                                              f"({SEVERITY[severity]})"])


def entries(root: Path) -> list[dict]:
    path = root / LOG_REL
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not ROW_RX.match(line.strip()):
            continue
        cells = [c.strip().replace("\\|", "|") for c in CELL_SPLIT_RX.split(line.strip().strip("|"))]
        cells += [""] * (4 - len(cells))
        try:
            severity = int(cells[1])
        except ValueError:
            severity = 0
        out.append({"date": cells[0], "severity": severity, "doing": cells[2], "problem": " | ".join(cells[3:]).strip(" |")})
    return out


def show(root: Path, days: int, as_json: bool) -> int:
    all_entries = entries(root)
    since = (date.today() - timedelta(days=days)).isoformat() if days > 0 else ""
    recent = sorted((e for e in all_entries if e["date"] >= since), key=lambda e: (-e["severity"], e["date"]))
    period = f"the last {days} days" if days > 0 else "all time"
    data = {"log": LOG_REL, "since": since or None, "entries": recent, "total": len(all_entries)}
    if not recent:
        return finish("NO_FEEDBACK", EXIT_OK, [f"NO_FEEDBACK: no entries in {LOG_REL} for {period}."], data, as_json)
    counts = ", ".join(f"{sum(1 for e in recent if e['severity'] == s)} x {s}" for s in (3, 2, 1))
    lines = [f"FEEDBACK: {len(recent)} entr{'y' if len(recent) == 1 else 'ies'} for {period} (severity {counts}), "
             f"{len(all_entries)} in total in {LOG_REL}"]
    for e in recent:
        doing = f" [{e['doing']}]" if e["doing"] and e["doing"] != "-" else ""
        lines.append(f"  {e['date']} {e['severity'] or '?'}{doing} {e['problem']}")
    return finish("FEEDBACK", EXIT_OK, lines, data, as_json)
