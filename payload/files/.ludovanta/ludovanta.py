#!/usr/bin/env python3
"""Ludovanta command line for AI agents and humans.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.

    python3 .ludovanta/ludovanta.py status            # LIVE (Editor open) or HEADLESS, Unity found?
    python3 .ludovanta/ludovanta.py compile           # batchmode compile, compact compiler errors
    python3 .ludovanta/ludovanta.py test [--platform EditMode|PlayMode] [--filter X] [--category Y]
    python3 .ludovanta/ludovanta.py validate-assets   # .meta / GUID consistency, no Unity needed
    python3 .ludovanta/ludovanta.py plan [status|check|next|init|add-milestone|add-task|set|fail]
    python3 .ludovanta/ludovanta.py update [--ref vX.Y.Z] [--dry-run] [--force]

Exit codes: 0 ok, 1 project problems, 2 environment failure, 3 project open in Unity Editor, 4 timeout.
"""
from __future__ import annotations

import argparse
import os
import sys

if sys.version_info < (3, 9):
    print("LUDOVANTA_ERROR: Python 3.9+ is required, found " + sys.version.split()[0])
    sys.exit(2)

sys.dont_write_bytecode = True   # keep .ludovanta/ free of __pycache__ folders

from pathlib import Path  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ludovanta.py", description="Ludovanta commands.")
    parser.add_argument("--project", help="Unity project root (default: the project containing this .ludovanta folder)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show LIVE/HEADLESS mode and environment")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("compile", help="compile the project in batchmode")
    p.add_argument("--warnings", action="store_true", help="also list compiler warnings")
    p.add_argument("--timeout", type=int, default=1800, help="seconds (default 1800)")
    p.add_argument("--max-items", type=int, default=30)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("test", help="run Unity Test Framework tests in batchmode")
    p.add_argument("--platform", choices=["EditMode", "PlayMode"], default="EditMode",
                   type=lambda s: {"editmode": "EditMode", "playmode": "PlayMode"}.get(s.lower(), s))
    p.add_argument("--filter", help="test name or regex (Unity -testFilter)")
    p.add_argument("--category", help="NUnit category (Unity -testCategory)")
    p.add_argument("--timeout", type=int, default=3600, help="seconds (default 3600)")
    p.add_argument("--max-items", type=int, default=20)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("validate-assets", help="check .meta files and GUIDs without Unity")
    p.add_argument("--roots", nargs="+", default=["Assets"], help="folders to check (default: Assets)")
    p.add_argument("--max-items", type=int, default=50)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("plan", help="project plan: progress, next tasks, task cards (skill ludovanta-plan)")
    plan = p.add_subparsers(dest="plan_command")
    p.set_defaults(plan_command="status", json=False)
    q = plan.add_parser("status", help="progress by milestone, tasks in review/in progress/blocked, next tasks")
    q.add_argument("--json", action="store_true")
    q = plan.add_parser("check", help="validate plan files and the task contract")
    q.add_argument("--json", action="store_true")
    q = plan.add_parser("next", help="tasks ready to start")
    q.add_argument("--agent", help="only tasks for this agent (plus 'any')")
    q.add_argument("--count", type=int, default=3)
    q.add_argument("--json", action="store_true")
    q = plan.add_parser("init", help="create the plan folder")
    q.add_argument("--title", help="title for goal.md")
    q = plan.add_parser("add-milestone", help="create the next milestone card")
    q.add_argument("--title", required=True)
    q = plan.add_parser("add-task", help="create the next task card")
    q.add_argument("--title", required=True)
    q.add_argument("--milestone", required=True)
    q.add_argument("--agent", default="any", help="claude, codex, any, or a person (default: any)")
    q.add_argument("--size", default="M", help="S, M or L (default: M)")
    q.add_argument("--depends", nargs="*", default=[], help="task ids this task needs")
    q = plan.add_parser("set", help="change a task's status or agent")
    q.add_argument("task")
    q.add_argument("--status", choices=["todo", "in-progress", "review", "done", "blocked", "dropped"])
    q.add_argument("--agent")
    q = plan.add_parser("fail", help="record a failed attempt; stops the agent after maxAttempts (default 3)")
    q.add_argument("task")
    q.add_argument("reason", help="why the attempt failed")

    p = sub.add_parser("update", help="update the platform to the ref in ludovanta.json or --ref")
    p.add_argument("--ref", help="git tag or branch to switch to (also updates ludovanta.json)")
    p.add_argument("--source", help="override the platform source (git URL or local folder)")
    p.add_argument("--force", action="store_true", help="overwrite locally modified platform files (with backup)")
    p.add_argument("--dry-run", action="store_true", help="only show what would change")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        # Plan titles and paths can be non-ASCII; agents read piped output as UTF-8 (Windows pipes default to ANSI).
        if os.environ.get("PYTHONIOENCODING"):
            sys.stdout.reconfigure(errors="replace")
        else:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))

    if args.command == "update":
        # Imported alone so that an update can repair other broken platform files.
        from ludovanta_lib.update import update
        root = Path(args.project).resolve() if args.project else here.parent
        return update(root, args.ref, args.source, args.force, args.dry_run)

    from ludovanta_lib import commands
    from ludovanta_lib.common import EXIT_INFRA, LudovantaError, find_project_root

    try:
        root = find_project_root(args.project or here)
        if args.command == "status":
            return commands.status(root, args.json)
        if args.command == "compile":
            return commands.compile_project(root, args.timeout, args.max_items, args.warnings, args.json)
        if args.command == "test":
            return commands.run_tests(root, args.platform, args.filter, args.category, args.timeout,
                                      args.max_items, args.json)
        if args.command == "validate-assets":
            return commands.validate_assets(root, args.roots, args.max_items, args.json)
        if args.command == "plan":
            from ludovanta_lib import plan
            pc = args.plan_command
            if pc == "status":
                return plan.status(root, args.json)
            if pc == "check":
                return plan.check(root, args.json)
            if pc == "next":
                return plan.next_tasks(root, args.agent, args.count, args.json)
            if pc == "init":
                return plan.init(root, args.title)
            if pc == "add-milestone":
                return plan.add_milestone(root, args.title)
            if pc == "add-task":
                return plan.add_task(root, args.title, args.milestone, args.agent, args.size, args.depends)
            if pc == "set":
                return plan.set_task(root, args.task, args.status, args.agent)
            if pc == "fail":
                return plan.fail_task(root, args.task, args.reason)
    except LudovantaError as e:
        print(f"LUDOVANTA_ERROR: {e}")
        return EXIT_INFRA
    return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
