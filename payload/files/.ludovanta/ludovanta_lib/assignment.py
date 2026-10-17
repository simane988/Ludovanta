"""Agent usability, read-only Unity MCP discovery and weighted task assignment.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from fractions import Fraction
from pathlib import Path

from .codex import find_codex
from .common import LudovantaError, load_config, read_text
from .plan import SIZES

AGENTS = ("claude", "codex")


def validate_weights(cfg: dict) -> dict | None:
    """Validate assignment settings only where used; unrelated commands can still load the config."""
    if "agentWeights" not in cfg:
        return None
    weights = cfg["agentWeights"]
    if not isinstance(weights, dict):
        raise LudovantaError("agentWeights must be an object from agent name to weight")
    for agent, weight in weights.items():
        if agent not in AGENTS:
            raise LudovantaError(f"agentWeights: unknown agent '{agent}'")
        if (isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0
                or (isinstance(weight, float) and not math.isfinite(weight))):
            raise LudovantaError(f"agentWeights: '{agent}' must have a finite numeric weight >= 0")
    if not any(weights.values()):
        raise LudovantaError("agentWeights must contain at least one weight above zero")
    return weights


def _run(exe: str, root: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run([exe, *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, timeout=30)
        return p.returncode, (p.stdout if p.returncode == 0 else p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


class Agents:
    """One command's probes: Codex login and MCP listing run at most once each, only when needed."""

    def __init__(self, root: Path):
        self.root = root
        self.cfg = load_config(root)
        self._usability: dict = {}
        self._unity: dict = {}

    def usable(self, agent: str) -> tuple[bool, str]:
        if agent not in self._usability:
            if agent == "claude":
                result = True, "Claude is always usable"
            else:
                exe = find_codex(self.root)
                if not exe:
                    result = False, "Codex CLI not found; install it or set codexPath / CODEX_PATH, then codex login"
                else:
                    code, out = _run(exe, self.root, "login", "status")
                    result = (True, f"{exe}, logged in") if code == 0 else (
                        False, f"{exe}, not logged in ({out.splitlines()[-1] if out else 'no answer'}); run codex login")
            self._usability[agent] = result
        return self._usability[agent]

    def unity(self, agent: str) -> tuple[bool, str]:
        if agent not in self._unity:
            overrides = self.cfg.get("unityMcp") or {}
            if agent in overrides:
                result = bool(overrides[agent]), f"unityMcp.{agent}"
            elif agent == "claude":
                result = self._claude_unity()
            else:
                exe = find_codex(self.root)
                if not exe:
                    result = False, "codex mcp list --json: CLI not found"
                else:
                    code, out = _run(exe, self.root, "mcp", "list", "--json")
                    try:
                        servers = json.loads(out)
                        if code != 0 or not isinstance(servers, list) or any(not isinstance(s, dict) for s in servers):
                            raise ValueError()
                        result = any(_unity_server(s.get("name", ""), s, self.root) for s in servers), \
                            "codex mcp list --json"
                    except ValueError:
                        result = False, "codex mcp list --json: unreadable answer (no Unity MCP)"
            self._unity[agent] = result
        return self._unity[agent]

    def _claude_unity(self) -> tuple[bool, str]:
        sources, notes = [], []
        for path in (self.root / ".mcp.json", Path.home() / ".claude.json"):
            try:
                data = json.loads(read_text(path))
                if not isinstance(data, dict):
                    raise ValueError()
                scopes = [(data, str(path))]
                if path.name == ".claude.json":
                    for project, scope in (data.get("projects") or {}).items():
                        if _same_path(project, self.root, self.root) and isinstance(scope, dict):
                            scopes.append((scope, f"{path} projects[{project}]"))
                for scope, source in scopes:
                    servers = scope.get("mcpServers") or {}
                    if isinstance(servers, dict) and any(_unity_server(name, s, self.root)
                                                         for name, s in servers.items()):
                        sources.append(source)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, AttributeError):
                notes.append(f"{path}: unreadable")
        return bool(sources), "; ".join(sources or notes or [".mcp.json / ~/.claude.json: no Unity MCP"])


def _same_path(value: str, root: Path, base: Path) -> bool:
    path = Path(value).expanduser()
    return os.path.normcase(str((base / path).resolve())) == os.path.normcase(str(root.resolve()))


def _unity_server(name: str, server, root: Path) -> bool:
    if not isinstance(server, dict):
        return False
    transport = server.get("transport") or server
    if not isinstance(transport, dict):
        return False
    if "unity" not in (str(name) + " " + str(transport.get("command", ""))).lower():
        return False
    args = transport.get("args") or []
    if not isinstance(args, list):
        return False
    for i, arg in enumerate(args):
        if arg == "--project-path":
            if i + 1 == len(args) or not _same_path(str(args[i + 1]), root, root):
                return False
        elif isinstance(arg, str) and arg.startswith("--project-path="):
            if not _same_path(arg.split("=", 1)[1], root, root):
                return False
    return True


def weighted_work(tasks: list[dict]) -> dict:
    return {agent: sum(SIZES[t["size"]] for t in tasks if t.get("assigned") == "weights"
                       and t["agent"] == agent and t["status"] not in ("todo", "dropped")) for agent in AGENTS}


def pick(tasks: list[dict], size: str, weights: dict, candidates: list[str]) -> tuple[str, dict]:
    work = weighted_work(tasks)
    shares = {a: (Fraction(work[a] + SIZES[size]) / Fraction(str(weights[a]))) for a in candidates}
    agent = min(candidates, key=lambda a: (shares[a], -weights[a], AGENTS.index(a)))
    details = {}
    for a in candidates:
        try:
            after = float(shares[a])
        except OverflowError:
            after = str(shares[a])
        details[a] = {"work": work[a], "weight": weights[a], "after": after}
    return agent, details
