"""Project plan: milestones and task cards in plain markdown files, progress, next tasks, task contract checks.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Layout (owned by the project, committed; folder name from 'planDir' in ludovanta.json, default 'plan'):

    plan/goal.md               free text: what we are building, what is in and out of scope
    plan/milestones/M1.md      header: id, title
    plan/tasks/T-001.md        header: id, title, milestone, status, agent, size, depends, attempts

Each file starts with a header between '---' lines ('key: value', lists as '[a, b]'). The task body is free
markdown in any language; every checkbox line ('- [ ] ...') in it is an acceptance criterion.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .common import EXIT_OK, EXIT_PROBLEMS, LudovantaError, finish, load_config, relpath

STATUSES = ("todo", "in-progress", "review", "done", "blocked", "dropped")
SIZES = {"S": 1, "M": 2, "L": 4}
TASK_FILE_RX = re.compile(r"^T-(\d+)\.md$")
MILESTONE_FILE_RX = re.compile(r"^M(\d+)\.md$")
CRITERION_RX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+\S")
HEADER_LINE_RX = re.compile(r"^([A-Za-z][\w-]*):\s*(.*)$")
STARTED = ("in-progress", "review", "done")
DEPENDENCY_MET = ("review", "done")
DEFAULT_MAX_ATTEMPTS = 3


# --- Files -----------------------------------------------------------------------------

class CardFile:
    """A plan file: header fields plus body, rewritten in place without touching anything else."""

    def __init__(self, path: Path):
        self.path = path
        raw = path.read_bytes()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig", errors="replace")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.replace("\r\n", "\n").split("\n")
        self.fields: dict[str, str] = {}
        self.header_end = -1      # index of the closing '---'
        self.error = ""
        if not self.lines or self.lines[0].strip() != "---":
            self.error = "no header (the file must start with a '---' line)"
            return
        for i in range(1, len(self.lines)):
            line = self.lines[i]
            if line.strip() == "---":
                self.header_end = i
                return
            m = HEADER_LINE_RX.match(line.strip())
            if m:
                self.fields[m.group(1).lower()] = _unquote(m.group(2).strip())
            elif line.strip():
                self.error = f"bad header line {i + 1}: '{line.strip()}'"
                return
        self.error = "header is not closed with a '---' line"

    @property
    def body(self) -> list[str]:
        return self.lines[self.header_end + 1:] if self.header_end >= 0 else []

    def set_field(self, key: str, value: str) -> None:
        self.fields[key] = value
        for i in range(1, self.header_end):
            m = HEADER_LINE_RX.match(self.lines[i].strip())
            if m and m.group(1).lower() == key:
                self.lines[i] = f"{key}: {value}"
                return
        self.lines.insert(self.header_end, f"{key}: {value}")
        self.header_end += 1

    def append_log(self, entry: str) -> None:
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        if not any(re.match(r"^##\s+(log|журнал)\b", line, re.IGNORECASE) for line in self.lines):
            self.lines += ["", "## Log", ""]
        self.lines += [entry, ""]

    def save(self) -> None:
        text = self.newline.join(self.lines)
        self.path.write_bytes(("﻿" if self.bom else "").encode("utf-8") + text.encode("utf-8"))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [_unquote(v.strip()) for v in value.split(",") if v.strip()]


def _natural(id_: str) -> tuple:
    m = re.search(r"(\d+)$", id_)
    return (id_.rstrip("0123456789"), int(m.group(1)) if m else -1, id_)


# --- Model -----------------------------------------------------------------------------

class Plan:
    def __init__(self, root: Path):
        cfg = load_config(root)
        self.root = root
        self.dir = root / str(cfg.get("planDir") or "plan")
        self.max_attempts = int(cfg.get("maxAttempts") or DEFAULT_MAX_ATTEMPTS)
        self.milestones: list[dict] = []
        self.tasks: list[dict] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        if self.exists:
            self._load()

    @property
    def exists(self) -> bool:
        return (self.dir / "tasks").is_dir() or (self.dir / "milestones").is_dir()

    def rel(self, path: Path) -> str:
        return relpath(self.root, path)

    def _cards(self, sub: str, rx, example: str) -> list[CardFile]:
        folder = self.dir / sub
        cards = []
        if folder.is_dir():
            for p in sorted(folder.iterdir(), key=lambda p: _natural(p.stem)):
                if p.suffix.lower() != ".md" or p.name.lower() == "readme.md":
                    continue
                if not rx.match(p.name):
                    self.errors.append(f"{self.rel(p)}: unexpected file name (expected {example})")
                    continue
                card = CardFile(p)
                if card.error:
                    self.errors.append(f"{self.rel(p)}: {card.error}")
                    continue
                if card.fields.get("id") != p.stem:
                    self.errors.append(f"{self.rel(p)}: id '{card.fields.get('id', '')}' does not match the file name")
                    continue
                cards.append(card)
        return cards

    def _load(self) -> None:
        for card in self._cards("milestones", MILESTONE_FILE_RX, "M<number>.md"):
            self.milestones.append({"id": card.fields["id"], "title": card.fields.get("title", ""),
                                    "file": self.rel(card.path)})
        known_milestones = {m["id"] for m in self.milestones}

        for card in self._cards("tasks", TASK_FILE_RX, "T-<number>.md"):
            f = card.fields
            where = self.rel(card.path)
            criteria = [CRITERION_RX.match(line) for line in card.body]
            criteria = [m for m in criteria if m]
            task = {
                "id": f["id"], "title": f.get("title", ""), "milestone": f.get("milestone", ""),
                "status": f.get("status", "todo").lower(), "agent": (f.get("agent") or "any").lower(),
                "size": (f.get("size") or "M").upper(), "depends": parse_list(f.get("depends", "")),
                "attempts": 0, "criteria": len(criteria),
                "criteriaChecked": sum(1 for m in criteria if m.group(1) != " "), "file": where,
            }
            try:
                task["attempts"] = int(f.get("attempts") or 0)
            except ValueError:
                self.errors.append(f"{where}: attempts must be a number")
            if not task["title"]:
                self.errors.append(f"{where}: title is empty")
            if task["status"] not in STATUSES:
                self.errors.append(f"{where}: unknown status '{task['status']}' (use {', '.join(STATUSES)})")
            if task["size"] not in SIZES:
                self.errors.append(f"{where}: unknown size '{task['size']}' (use S, M or L; split bigger tasks)")
                task["size"] = "M"
            if task["milestone"] not in known_milestones:
                self.errors.append(f"{where}: unknown milestone '{task['milestone']}'")
            if task["status"] in STARTED and not task["criteria"]:
                self.errors.append(f"{where}: status '{task['status']}' but no acceptance criteria ('- [ ] ...' lines)")
            elif task["status"] == "todo" and not task["criteria"]:
                self.warnings.append(f"{task['id']}: no acceptance criteria yet, cannot be started")
            if task["status"] == "done" and task["criteriaChecked"] < task["criteria"]:
                self.warnings.append(f"{task['id']}: done, but {task['criteria'] - task['criteriaChecked']} "
                                     "acceptance criteria are not ticked")
            self.tasks.append(task)

        by_id = self.by_id
        for t in self.tasks:
            for d in t["depends"]:
                if d not in by_id:
                    self.errors.append(f"{t['file']}: depends on unknown task '{d}'")
        self.errors += [f"dependency cycle: {' -> '.join(c)}" for c in self._cycles()]

    @property
    def by_id(self) -> dict[str, dict]:
        return {t["id"]: t for t in self.tasks}

    def _cycles(self) -> list[list[str]]:
        by_id, state, cycles = self.by_id, {}, []

        def visit(tid: str, path: list[str]) -> None:
            state[tid] = 1
            for d in by_id[tid]["depends"]:
                if d not in by_id:
                    continue
                if state.get(d) == 1:
                    cycles.append(path[path.index(d):] + [d])
                elif not state.get(d):
                    visit(d, path + [d])
            state[tid] = 2

        for t in self.tasks:
            if not state.get(t["id"]):
                visit(t["id"], [t["id"]])
        return cycles

    def ready(self, agent: str | None = None) -> list[dict]:
        by_id = self.by_id
        order = {m["id"]: i for i, m in enumerate(self.milestones)}
        out = []
        for t in self.tasks:
            if t["status"] != "todo" or not t["criteria"]:
                continue
            if agent and t["agent"] not in (agent.lower(), "any"):
                continue
            if all(by_id.get(d, {}).get("status") in DEPENDENCY_MET for d in t["depends"]):
                out.append(t)
        return sorted(out, key=lambda t: (order.get(t["milestone"], 1 << 30), _natural(t["id"])))

    def progress(self, tasks: list[dict]) -> dict:
        live = [t for t in tasks if t["status"] != "dropped"]
        total = sum(SIZES[t["size"]] for t in live)
        weight = lambda status: sum(SIZES[t["size"]] for t in live if t["status"] == status)  # noqa: E731
        counts = {s: sum(1 for t in live if t["status"] == s) for s in STATUSES if s != "dropped"}
        return {"done": round(100 * weight("done") / total) if total else 0,
                "review": round(100 * weight("review") / total) if total else 0,
                "tasks": len(live), "counts": counts}

    def goal_title(self) -> str:
        goal = self.dir / "goal.md"
        if goal.is_file():
            for line in goal.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                if line.startswith("# "):
                    return line[2:].strip()
        return ""

    def card(self, task_id: str) -> CardFile:
        path = self.dir / "tasks" / f"{task_id}.md"
        if not path.is_file():
            raise LudovantaError(f"task {task_id} not found ({self.rel(path)})")
        card = CardFile(path)
        if card.error:
            raise LudovantaError(f"{self.rel(path)}: {card.error}")
        return card

    def next_id(self, sub: str, rx, prefix: str, width: int) -> str:
        folder = self.dir / sub
        numbers = [int(m.group(1)) for p in folder.iterdir() if (m := rx.match(p.name))] if folder.is_dir() else []
        return f"{prefix}{max(numbers, default=0) + 1:0{width}d}"


# --- Output helpers ----------------------------------------------------------------------

def _bar(percent: int, review: int = 0, width: int = 20) -> str:
    done = round(width * percent / 100)
    rev = min(width - done, round(width * review / 100))
    return "[" + "#" * done + "+" * rev + "." * (width - done - rev) + "]"


def _task_line(t: dict) -> str:
    return f"{t['id']} [{t['agent']}, {t['size']}] {t['title']} ({t['milestone']})"


def _no_plan(plan: Plan, as_json: bool) -> int:
    return finish("NO_PLAN", EXIT_OK, [f"NO_PLAN: no plan in {plan.rel(plan.dir)}/. "
                                       "Create one with 'ludovanta.py plan init' (skill ludovanta-plan)."],
                  {"planDir": plan.rel(plan.dir)}, as_json)


# --- Commands ------------------------------------------------------------------------------

def status(root: Path, as_json: bool) -> int:
    plan = Plan(root)
    if not plan.exists:
        return _no_plan(plan, as_json)
    overall = plan.progress(plan.tasks)
    c = overall["counts"]
    title = plan.goal_title()
    lines = [f"PLAN: {title}" if title else f"PLAN: {plan.rel(plan.dir)}/",
             f"overall {_bar(overall['done'], overall['review'])} {overall['done']}% done"
             + (f" (+{overall['review']}% in review)" if overall["review"] else "")
             + f" - {c['done']}/{overall['tasks']} tasks done, {c['review']} in review, {c['in-progress']} in progress, "
               f"{c['blocked']} blocked, {c['todo']} todo"]
    milestones = []
    for m in plan.milestones:
        p = plan.progress([t for t in plan.tasks if t["milestone"] == m["id"]])
        milestones.append({**m, **p})
        extra = f", {p['counts']['review']} in review" if p["counts"]["review"] else ""
        lines.append(f"{m['id']} {_bar(p['done'], p['review'])} {p['done']:>3}% {m['title']} "
                     f"({p['counts']['done']}/{p['tasks']} done{extra})")

    def section(name: str, tasks: list[dict]) -> None:
        if tasks:
            lines.append(f"{name}:")
            lines.extend(f"  {_task_line(t)}" for t in tasks)

    review = [t for t in plan.tasks if t["status"] == "review"]
    section("waiting for the user's review", review)
    stuck = [t for t in plan.tasks if t["status"] == "in-progress" and t["attempts"]
             and t["attempts"] % plan.max_attempts == 0]
    section("in progress", [t for t in plan.tasks if t["status"] == "in-progress" and t not in stuck])
    section("blocked", [t for t in plan.tasks if t["status"] == "blocked"])
    section(f"stopped after {plan.max_attempts} failed attempts, need the user's decision", stuck)
    ready = plan.ready()
    section("next (ready to start)", ready[:5])
    if plan.errors:
        lines.append(f"problems: {len(plan.errors)} - run 'ludovanta.py plan check'")
    data = {"goal": title, "overall": overall, "milestones": milestones, "tasks": plan.tasks,
            "next": [t["id"] for t in ready], "problems": plan.errors, "warnings": plan.warnings}
    return finish("PLAN", EXIT_OK, lines, data, as_json)


def check(root: Path, as_json: bool) -> int:
    plan = Plan(root)
    if not plan.exists:
        return _no_plan(plan, as_json)
    data = {"problems": plan.errors, "warnings": plan.warnings}
    warn_lines = [f"warning: {w}" for w in plan.warnings]
    if plan.errors:
        lines = [f"PLAN_INVALID: {len(plan.errors)} problem(s)"] + [f"- {e}" for e in plan.errors] + warn_lines
        return finish("PLAN_INVALID", EXIT_PROBLEMS, lines, data, as_json)
    lines = [f"PLAN_OK: {len(plan.milestones)} milestone(s), {len(plan.tasks)} task(s)"] + warn_lines
    return finish("PLAN_OK", EXIT_OK, lines, data, as_json)


def next_tasks(root: Path, agent: str | None, count: int, as_json: bool) -> int:
    plan = Plan(root)
    if not plan.exists:
        return _no_plan(plan, as_json)
    ready = plan.ready(agent)[:count]
    data = {"agent": agent, "tasks": ready}
    if not ready:
        why = "no todo task with acceptance criteria and finished dependencies"
        return finish("NO_READY_TASKS", EXIT_OK, [f"NO_READY_TASKS: {why}" + (f" for agent '{agent}'" if agent else "")],
                      data, as_json)
    lines = ["NEXT:"] + [f"  {_task_line(t)} -> {t['file']}" for t in ready]
    return finish("NEXT", EXIT_OK, lines, data, as_json)


GOAL_TEMPLATE = """# {title}

## Goal

What the player should experience when this is done, in two or three sentences.

## In scope

-

## Out of scope

-

## Done when

-
"""

README_TEMPLATE = """# Plan

This folder is the project plan. AI agents keep it up to date (skill `ludovanta-plan`), people review it.

- `goal.md`: what we are building and what is out of scope.
- `milestones/M<n>.md`: milestones in order.
- `tasks/T-<nnn>.md`: one task card per file. Status, agent and size are in the header,
  acceptance criteria are the `- [ ]` lines in the body.

Progress: `python3 .ludovanta/ludovanta.py plan` (on Windows `python` or `py -3`).
"""

MILESTONE_TEMPLATE = """---
id: {id}
title: {title}
---

## Goal

## Done when

-
"""

TASK_TEMPLATE = """---
id: {id}
title: {title}
milestone: {milestone}
status: todo
agent: {agent}
size: {size}
depends: [{depends}]
attempts: 0
---

## Goal

## Acceptance criteria

## Do not touch

## Notes
"""


def init(root: Path, title: str | None) -> int:
    plan = Plan(root)
    created = []
    for sub in ("milestones", "tasks"):
        (plan.dir / sub).mkdir(parents=True, exist_ok=True)
    for name, text in (("README.md", README_TEMPLATE), ("goal.md", GOAL_TEMPLATE.format(title=title or "Goal"))):
        path = plan.dir / name
        if not path.exists():
            path.write_text(text, encoding="utf-8", newline="\n")
            created.append(plan.rel(path))
    lines = [f"PLAN_INIT: {plan.rel(plan.dir)}/ ready" + (f", created {', '.join(created)}" if created else
                                                           " (already existed, nothing overwritten)")]
    return finish("PLAN_INIT", EXIT_OK, lines)


def add_milestone(root: Path, title: str) -> int:
    plan = Plan(root)
    folder = plan.dir / "milestones"
    folder.mkdir(parents=True, exist_ok=True)
    mid = plan.next_id("milestones", MILESTONE_FILE_RX, "M", 1)
    path = folder / f"{mid}.md"
    path.write_text(MILESTONE_TEMPLATE.format(id=mid, title=title), encoding="utf-8", newline="\n")
    return finish("MILESTONE_ADDED", EXIT_OK, [f"MILESTONE_ADDED: {mid} -> {plan.rel(path)}"])


def add_task(root: Path, title: str, milestone: str, agent: str, size: str, depends: list[str]) -> int:
    plan = Plan(root)
    if milestone not in {m["id"] for m in plan.milestones}:
        raise LudovantaError(f"unknown milestone '{milestone}'; create it with 'plan add-milestone'")
    unknown = [d for d in depends if d not in plan.by_id]
    if unknown:
        raise LudovantaError(f"unknown dependencies: {', '.join(unknown)}")
    size = size.upper()
    if size not in SIZES:
        raise LudovantaError("size must be S, M or L (split bigger tasks)")
    folder = plan.dir / "tasks"
    folder.mkdir(parents=True, exist_ok=True)
    tid = plan.next_id("tasks", TASK_FILE_RX, "T-", 3)
    path = folder / f"{tid}.md"
    path.write_text(TASK_TEMPLATE.format(id=tid, title=title, milestone=milestone, agent=agent.lower(), size=size,
                                         depends=", ".join(depends)), encoding="utf-8", newline="\n")
    return finish("TASK_ADDED", EXIT_OK, [f"TASK_ADDED: {tid} -> {plan.rel(path)}",
                                          "Fill in the goal and the acceptance criteria ('- [ ] ...') before starting it."])


def set_task(root: Path, task_id: str, new_status: str | None, agent: str | None) -> int:
    plan = Plan(root)
    card = plan.card(task_id)
    task = plan.by_id[task_id]
    lines = []
    if new_status:
        if new_status in STARTED and not task["criteria"]:
            return finish("NO_CRITERIA", EXIT_PROBLEMS, [
                f"NO_CRITERIA: {task_id} has no acceptance criteria, it cannot be {new_status}.",
                f"Add '- [ ] ...' lines to {task['file']} (what the user will check, observable), "
                "agree them with the user if the task is ambiguous, then set the status again."])
        card.set_field("status", new_status)
        lines.append(f"TASK_UPDATED: {task_id} status {task['status']} -> {new_status}")
        open_criteria = task["criteria"] - task["criteriaChecked"]
        if new_status in ("review", "done") and open_criteria:
            lines.append(f"note: {open_criteria} acceptance criteria are not ticked; list them in the report "
                         "as 'not verified' or tick the ones you verified.")
    if agent:
        card.set_field("agent", agent.lower())
        lines.append(f"TASK_UPDATED: {task_id} agent {task['agent']} -> {agent.lower()}")
    if not lines:
        raise LudovantaError("nothing to change: pass --status and/or --agent")
    card.save()
    return finish("TASK_UPDATED", EXIT_OK, lines)


def fail_task(root: Path, task_id: str, reason: str) -> int:
    """Records a failed attempt (own verification failed or the user rejected the result)."""
    plan = Plan(root)
    card = plan.card(task_id)
    task = plan.by_id[task_id]
    attempts = task["attempts"] + 1
    card.set_field("attempts", str(attempts))
    if task["status"] in ("review", "done", "todo"):
        card.set_field("status", "in-progress")
    card.append_log(f"- {date.today().isoformat()} attempt {attempts} failed: {reason.strip()}")
    card.save()
    if attempts % plan.max_attempts == 0:
        return finish("STOP", EXIT_PROBLEMS, [
            f"STOP: {task_id} failed {plan.max_attempts} attempts in a row. Do not try again on your own.",
            "Report to the user: what you tried, why each attempt failed, your hypotheses, and ONE concrete question "
            "or decision you need. Continue only after the user answers."])
    left = plan.max_attempts - attempts % plan.max_attempts
    return finish("ATTEMPT_RECORDED", EXIT_OK, [
        f"ATTEMPT_RECORDED: {task_id} attempt {attempts} failed, {left} attempt(s) left before you must stop and ask.",
        "Before the next attempt, change the approach: do not repeat what already failed."])
