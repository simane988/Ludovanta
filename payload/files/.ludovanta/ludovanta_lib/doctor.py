"""doctor: is everything the agents need in place? One line per check and one next step for the first problem.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.

Levels: ok, info (worth knowing, nothing to do), warn (works, but something is missing or will get in the way),
FAIL (agents cannot work properly until it is fixed). Exit code 2 when anything FAILs, otherwise 0.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .assignment import AGENTS, Agents, validate_weights
from .common import (EXIT_INFRA, EXIT_OK, IS_WINDOWS, NO_WINDOW, LudovantaError, editor_open, finish,
                     load_config, read_text, resolve_unity, unity_version)

ORDER = {"FAIL": 0, "warn": 1, "info": 2, "ok": 3}
TAG_RX = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def _run(*args: str, cwd: Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def _lf_hash(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="surrogateescape").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()


class Doctor:
    def __init__(self, root: Path, offline: bool):
        self.root = root
        self.offline = offline
        self.cfg = load_config(root)
        self.agents = Agents(root)
        self.checks: list[dict] = []

    def add(self, level: str, name: str, detail: str, fix: str = "") -> None:
        self.checks.append({"level": level, "check": name, "detail": detail, "fix": fix})

    # --- checks ----------------------------------------------------------------------------------

    def python(self) -> None:
        self.add("ok", "python", f"{sys.version.split()[0]} ({sys.executable})")

    def git(self) -> None:
        if not shutil.which("git"):
            self.add("FAIL", "git", "not found", "install git (https://git-scm.com) and open a new terminal")
            return
        code, top = _run("git", "-C", str(self.root), "rev-parse", "--show-toplevel")
        if code != 0:
            self.add("warn", "git", "the project is not a git repository: no history, no worktrees for parallel agents",
                     "git init, then commit the project")
            return
        _, name = _run("git", "-C", str(self.root), "config", "user.name")
        _, email = _run("git", "-C", str(self.root), "config", "user.email")
        if not name or not email:
            self.add("warn", "git", "user.name or user.email is not set: agents cannot commit",
                     'git config --global user.name "Your Name" and git config --global user.email you@example.com')
            return
        self.add("ok", "git", f"repository, commits as {name}")

    def unity(self) -> None:
        try:
            version = unity_version(self.root)
        except LudovantaError as e:
            self.add("FAIL", "unity", str(e), "open the project once in Unity Hub")
            return
        try:
            exe = resolve_unity(self.root)
        except LudovantaError:
            self.add("FAIL", "unity", f"Unity {version} (the project's version) is not installed",
                     f"install Unity {version} in Unity Hub, or set 'unityEditorPath' in ludovanta.local.json")
            return
        mode = "open in the Editor: LIVE mode" if editor_open(self.root) else "not open: HEADLESS mode"
        self.add("ok", "unity", f"{version} at {exe}; the project is {mode}")

    def platform(self) -> None:
        lock_path = self.root / ".ludovanta" / "lock.json"
        try:
            lock = json.loads(read_text(lock_path))
        except (OSError, ValueError):
            self.add("FAIL", "ludovanta", ".ludovanta/lock.json is missing or broken",
                     "reinstall: python3 <platform>/install.py --project . --force")
            return
        version = lock.get("version") or "?"
        changed = []
        for rel, digest in sorted((lock.get("files") or {}).items()):
            path = self.root / rel
            if not path.is_file():
                changed.append(f"{rel} (missing)")
            elif not rel.endswith(".meta") and _lf_hash(path) != digest:
                changed.append(rel)
        if changed:
            self.add("warn", "ludovanta", f"{version}; {len(changed)} platform file(s) changed or missing, the next "
                     f"update will stop on them: {', '.join(changed[:3])}{' ...' if len(changed) > 3 else ''}",
                     "python3 .ludovanta/ludovanta.py update --force (changed files are backed up)")
        else:
            self.add("ok", "ludovanta", f"{version}, platform files intact")
        self._newer(version)

    def _newer(self, version: str) -> None:
        source = self.cfg.get("source")
        if self.offline or not source:
            return
        code, out = _run("git", "ls-remote", "--tags", str(source), timeout=30)
        if code != 0:
            self.add("info", "updates", f"could not check {source}")
            return
        tags = sorted({tuple(int(x) for x in m.groups()) for line in out.splitlines() if (m := TAG_RX.search(line))})
        try:
            current = tuple(int(x) for x in version.split("."))
        except ValueError:
            return
        if tags and tags[-1] > current:
            newest = "v" + ".".join(str(x) for x in tags[-1])
            self.add("warn", "updates", f"{newest} is available (installed {version})",
                     f"python3 .ludovanta/ludovanta.py update --ref {newest}")
        else:
            self.add("ok", "updates", "the newest version is installed")

    def skills(self) -> None:
        targets = [str(t).strip("/") for t in self.cfg.get("skillTargets") or [".claude/skills", ".agents/skills"]]
        missing = [t for t in targets if not (self.root / t / "ludovanta-plan" / "SKILL.md").is_file()]
        if missing:
            self.add("FAIL", "skills", f"ludovanta-* skills are missing in {', '.join(missing)}",
                     "python3 .ludovanta/ludovanta.py update")
        else:
            self.add("ok", "skills", f"installed in {', '.join(targets)}")
        self.targets = targets

    def agents_md(self) -> None:
        path = self.root / "AGENTS.md"
        text = read_text(path) if path.is_file() else ""
        if ">>> ludovanta:managed" not in text:
            self.add("FAIL", "rules", "AGENTS.md has no Ludovanta block: agents do not know the rules",
                     "python3 .ludovanta/ludovanta.py update")
            return
        claude = self.root / "CLAUDE.md"
        if not claude.is_file() or "@AGENTS.md" not in read_text(claude):
            self.add("warn", "rules", "CLAUDE.md does not import AGENTS.md: Claude does not see the rules",
                     "python3 .ludovanta/ludovanta.py update")
            return
        outside = re.sub(r"(?s)<!-- >>> ludovanta:managed.*?<<< ludovanta:managed -->", "", text)
        if not re.search(r"(?im)^#+\s*(preferences|настройки|предпочтения)\b", outside):
            self.add("info", "rules", "no '## Preferences' in AGENTS.md: language and the split between agents are "
                     "guessed (agents add it when you state a lasting preference)")
            return
        self.add("ok", "rules", "AGENTS.md with the Ludovanta block and project preferences; CLAUDE.md imports it")

    def claude(self) -> None:
        exe = shutil.which("claude")
        hooks_wanted = ".claude/skills" in getattr(self, "targets", []) and self.cfg.get("claudeHooks", True) is not False
        settings = self.root / ".claude" / "settings.json"
        hooks = settings.is_file() and ".ludovanta/hook.sh" in read_text(settings)
        if hooks_wanted and not hooks:
            self.add("warn", "claude code", "the Ludovanta hooks are not in .claude/settings.json: no plan brief at "
                     "session start, no handoff reminders", "python3 .ludovanta/ludovanta.py update")
        elif hooks_wanted and IS_WINDOWS and not shutil.which("bash") and not shutil.which("sh"):
            self.add("warn", "claude code", "the hooks run with bash, which is not on PATH",
                     "install Git for Windows (it brings bash) and restart Claude Code")
        else:
            self.add("ok" if exe else "info", "claude code", (f"{exe}" if exe else "the claude CLI is not on PATH "
                     "(fine if you use Claude Code from an app)") + ("; hooks installed" if hooks else ""))

    def codex(self) -> None:
        from .codex import find_codex
        exe = find_codex(self.root)
        usable, detail = self.agents.usable("codex")
        if not exe:
            self.add("info", "codex", detail)
            return
        if ".agents/skills" not in getattr(self, "targets", []):
            self.add("warn", "codex", f"{exe}, but it does not see the ludovanta-* skills",
                     "add \".agents/skills\" to \"skillTargets\" in ludovanta.json, then update")
            return
        if not usable:
            self.add("warn", "codex", detail, "codex login")
            return
        self.add("ok", "codex", detail)

    def assignment(self) -> None:
        try:
            weights = validate_weights(self.cfg)
        except LudovantaError as e:
            weights = None
            self.add("warn", "agent weights", str(e), "correct agentWeights in ludovanta.json / ludovanta.local.json")
        else:
            self.add("info", "agent weights", json.dumps(weights) if weights is not None else
                     "agentWeights not set: any goes to Claude (not assigned by weights)")
        eligible = []
        for agent in AGENTS:
            usable, why = self.agents.usable(agent)
            unity, source = self.agents.unity(agent)
            self.add("info", f"assignment {agent}", f"usable: {'yes' if usable else 'no'} ({why}); "
                     f"Unity MCP: {'yes' if unity else 'no'}; source: {source}")
            if weights is not None and usable and weights.get(agent, 0) > 0 and unity:
                eligible.append(agent)
        if weights is not None:
            self.add("info", "editor assignment", "Editor tasks go to " + ", ".join(eligible) if eligible else
                     "No eligible agent has Unity MCP; Editor executors can work only HEADLESS with the Editor closed")

    def orca(self) -> None:
        try:
            from .orca import available
        except ImportError:
            return
        exe, why = available(self.root)
        self.add("ok" if exe else "info", "orca", "running: executors get their own agent in Orca" if exe else
                 f"not available ({why}): executors are subagents or 'codex run'")

    def unity_packages(self) -> None:
        manifest = self.root / "Packages" / "manifest.json"
        text = read_text(manifest) if manifest.is_file() else ""
        if '"com.unity.ai.assistant"' in text:
            self.add("ok", "unity mcp", "com.unity.ai.assistant is installed")
        else:
            self.add("warn", "unity mcp", "com.unity.ai.assistant is not installed: with the Editor open, agents "
                     "cannot see the console or the scene", "Unity: Window > Package Manager > + > Add package by "
                     "name > com.unity.ai.assistant, then enable its MCP server for your agents")
        if (self.root / "Packages" / "com.ludovanta.editor" / "package.json").is_file():
            self.add("ok", "screenshots", "Packages/com.ludovanta.editor is installed ('screenshot')")
        else:
            self.add("FAIL", "screenshots", "Packages/com.ludovanta.editor is missing: agents cannot capture the game",
                     "python3 .ludovanta/ludovanta.py update")

    def plan(self) -> None:
        from . import plan as plan_mod
        p = plan_mod.Plan(self.root)
        if not p.exists:
            self.add("info", "plan", "no plan yet: ask an agent to plan the game (skill ludovanta-plan)")
            return
        if p.errors:
            self.add("warn", "plan", f"{len(p.errors)} problem(s) in the plan files", "python3 .ludovanta/ludovanta.py "
                     "plan check, or ask an agent to fix the plan")
            return
        self.add("ok", "plan", f"{len(p.tasks)} task(s), {p.progress(p.tasks)['done']}% done")


def doctor(root: Path, offline: bool, as_json: bool) -> int:
    d = Doctor(root, offline)
    for check in (d.python, d.git, d.unity, d.platform, d.skills, d.agents_md, d.claude, d.codex, d.assignment, d.orca,
                  d.unity_packages, d.plan):
        try:
            check()
        except Exception as e:  # noqa: BLE001 - one broken check must not hide the others
            d.add("warn", check.__name__.replace("_", " "), f"the check itself failed: {e}")
    fails = [c for c in d.checks if c["level"] == "FAIL"]
    warns = [c for c in d.checks if c["level"] == "warn"]
    first = min((c for c in d.checks if c["fix"]), key=lambda c: ORDER[c["level"]], default=None)
    status = "DOCTOR_FAIL" if fails else "DOCTOR_WARN" if warns else "DOCTOR_OK"
    head = f"{status}: {len(fails)} problem(s), {len(warns)} warning(s)"
    lines = [head + (f". Next: {first['fix']} ({first['check']})" if first else ". Everything the agents need is here.")]
    width = max(len(c["check"]) for c in d.checks)
    for c in d.checks:
        lines.append(f"{c['level']:<5} {c['check']:<{width}}  {c['detail']}")
        if c["fix"] and c["level"] in ("FAIL", "warn"):
            lines.append(f"{'':<5} {'':<{width}}  -> {c['fix']}")
    return finish(status, EXIT_INFRA if fails else EXIT_OK, lines, {"checks": d.checks, "next": first}, as_json)
