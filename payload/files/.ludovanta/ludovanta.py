#!/usr/bin/env python3
"""Ludovanta command line for AI agents and humans.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.

    python3 .ludovanta/ludovanta.py status            # LIVE (Editor open) or HEADLESS, Unity found?
    python3 .ludovanta/ludovanta.py compile           # batchmode compile, compact compiler errors
    python3 .ludovanta/ludovanta.py test [--platform EditMode|PlayMode] [--filter X] [--category Y] [--repeat N]
    python3 .ludovanta/ludovanta.py test-audit        # brittle, slow and flaky tests, no Unity needed
    python3 .ludovanta/ludovanta.py validate-assets   # .meta / GUID consistency, no Unity needed
    python3 .ludovanta/ludovanta.py plan [status|check|next|brief|stats|init|add-milestone|add-task|set|fail|close]
    python3 .ludovanta/ludovanta.py codex run T-001 | codex image --out Art/References/x.png "description"
    python3 .ludovanta/ludovanta.py feedback add "what gets in the way" [--doing "..."] [--severity 1|2|3] | feedback show
    python3 .ludovanta/ludovanta.py hook session-start|stop    # called by Claude Code hooks (stdin: hook JSON)
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
    p.add_argument("--timeout", type=int, default=3600, help="seconds per Unity run (default 3600)")
    p.add_argument("--repeat", type=int, default=1, metavar="N",
                   help="run the same tests N times with no change and report flaky ones (N Unity runs: use --filter)")
    p.add_argument("--no-rerun", dest="rerun", action="store_false",
                   help="do not rerun failed tests once to tell flaky tests from real failures")
    p.add_argument("--max-items", type=int, default=20)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("test-audit", help="find brittle, slow and flaky tests without running Unity")
    p.add_argument("--max-items", type=int, default=10, help="findings shown per kind (default 10)")
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
    q.add_argument("--unverified", metavar="WHY",
                   help="go to review/done although Ludovanta has no green full test run (Editor open, sandbox): "
                        "why, and what you checked instead; recorded in the card's log")
    q = plan.add_parser("fail", help="record a failed attempt; stops the agent after maxAttempts (default 3)")
    q.add_argument("task")
    q.add_argument("reason", help="why the attempt failed")
    q = plan.add_parser("brief", help="what a fresh session (no task) or an executor (task id) needs, in one read")
    q.add_argument("task", nargs="?")
    q = plan.add_parser("stats", help="per agent: tasks accepted, first-try rate, failed attempts (closed plans too)")
    q.add_argument("--json", action="store_true")
    q = plan.add_parser("close", help="archive a finished plan to plan/archive/, numbering continues")
    q.add_argument("--carry", action="store_true", help="keep unfinished tasks (and their milestones) for the next plan")

    p = sub.add_parser("codex", help="Codex CLI as an executor: run a task, generate a reference image (skill ludovanta-codex)")
    codex = p.add_subparsers(dest="codex_command", required=True)
    q = codex.add_parser("run", help="give one task card to 'codex exec' and report what it did")
    q.add_argument("task")
    q.add_argument("--model", help="Codex model (default: codex.model in ludovanta.json or Codex's own default)")
    q.add_argument("--timeout", type=int, default=3600, help="seconds (default 3600)")
    q.add_argument("--json", action="store_true")
    q = codex.add_parser("image", help="generate one image with Codex's built-in image generation")
    q.add_argument("description", help="what the image shows: subject, style, composition, palette")
    q.add_argument("--out", required=True, help="project-relative file, e.g. Art/References/hero.png")
    q.add_argument("--timeout", type=int, default=900, help="seconds (default 900)")
    q.add_argument("--json", action="store_true")

    p = sub.add_parser("feedback", help="friction log: what gets in the user's way (skill ludovanta-feedback)")
    fb = p.add_subparsers(dest="feedback_command", required=True)
    q = fb.add_parser("add", help="add an entry to docs/feedback-log.md")
    q.add_argument("problem", help="what got in the way, close to the user's words")
    q.add_argument("--doing", default="", help="what the user was doing at that moment")
    q.add_argument("--severity", type=int, choices=[1, 2, 3], default=2,
                   help="1 annoying, 2 slowed the work down (default), 3 blocked it or needed outside help")
    q = fb.add_parser("show", help="entries of the last days, most severe first")
    q.add_argument("--days", type=int, default=7, help="how many days back (default 7, 0 = all)")
    q.add_argument("--json", action="store_true")

    p = sub.add_parser("hook", help="Claude Code hook entry point (installed into .claude/settings.json)")
    p.add_argument("event", choices=["session-start", "stop"])

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
                                      args.max_items, args.json, args.repeat, args.rerun)
        if args.command == "test-audit":
            from ludovanta_lib import testaudit
            return testaudit.audit(root, args.max_items, args.json)
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
                return plan.set_task(root, args.task, args.status, args.agent, args.unverified)
            if pc == "fail":
                return plan.fail_task(root, args.task, args.reason)
            if pc == "brief":
                return plan.brief(root, args.task)
            if pc == "stats":
                return plan.stats(root, args.json)
            if pc == "close":
                return plan.close(root, args.carry)
        if args.command == "codex":
            from ludovanta_lib import codex
            if args.codex_command == "run":
                return codex.run_task(root, args.task, args.timeout, args.model, args.json)
            return codex.generate_image(root, args.description, args.out, args.timeout, args.json)
        if args.command == "feedback":
            from ludovanta_lib import feedback
            if args.feedback_command == "add":
                return feedback.add(root, args.problem, args.doing, args.severity)
            return feedback.show(root, args.days, args.json)
        if args.command == "hook":
            from ludovanta_lib import hooks
            return hooks.run(root, args.event)
    except LudovantaError as e:
        print(f"LUDOVANTA_ERROR: {e}")
        return EXIT_INFRA
    return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
