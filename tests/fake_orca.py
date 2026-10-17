"""Stand-in for the Orca CLI in tests: a JSON file (FAKE_ORCA_STATE) plays the Orca app.

Worktrees are real git worktrees, so Ludovanta's git side works as with Orca. Agents live in 'agents': one per
worktree made with --agent, one per 'terminal create --command'. A test plays an executor by editing its folder and
setting its agent's 'state' and 'lastAssistantMessage' in the state file (see test_orca.py).
FAKE_ORCA_MODE=down reports the app as not running; 'terminal wait' times out for a working agent, and for
every agent with FAKE_ORCA_TUI=never.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_ORCA_STATE"])


def load():
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"repos": [], "worktrees": [], "agents": [], "calls": []}


def arg(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def norm(path):
    return os.path.normcase(os.path.normpath(path))


def selector_path(state, value):
    """id:<repo>::<path> or path:<path> -> the path."""
    if value.startswith("path:"):
        return value[len("path:"):]
    return value[len("id:"):].split("::", 1)[1]


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    state = load()
    state["calls"].append(args)
    cmd = " ".join(args[:2])
    result, error = None, None
    if args[:1] == ["status"]:
        result = {"runtime": {"reachable": os.environ.get("FAKE_ORCA_MODE") != "down"}}
    elif cmd == "repo list":
        result = {"repos": state["repos"]}
    elif cmd == "repo add":
        repo = {"id": f"repo{len(state['repos']) + 1}", "path": arg(args, "--path")}
        state["repos"].append(repo)
        result = {"repo": repo}
    elif cmd == "worktree create":
        repo = next(r for r in state["repos"] if r["id"] == arg(args, "--repo")[len("id:"):])
        name = arg(args, "--name")
        path = (STATE.parent / "workspaces" / name).as_posix()
        branch = f"orca/{name}"
        subprocess.run(["git", "-C", repo["path"], "worktree", "add", "--quiet", "-b", branch, path,
                        arg(args, "--base-branch")], check=True, capture_output=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)
        wt = {"id": f"{repo['id']}::{path}", "path": path, "branch": f"refs/heads/{branch}",
              "comment": arg(args, "--comment")}
        state["worktrees"].append(wt)
        result = {"worktree": {k: wt[k] for k in ("id", "path", "branch")}}
        if arg(args, "--agent"):
            agent = {"handle": f"term_{name}", "path": path, "agentType": arg(args, "--agent"),
                     "paneKey": f"tab_{name}:leaf", "state": "working", "lastAssistantMessage": None,
                     "prompt": arg(args, "--prompt"), "sent": []}
            state["agents"].append(agent)
            result["agentTerminalHandle"] = agent["handle"]
    elif cmd == "worktree ps":
        paths = {norm(w["path"]): w["path"] for w in state["worktrees"]}
        paths.update({norm(a["path"]): a["path"] for a in state["agents"] if norm(a["path"]) not in paths})
        rows = []
        for key, path in paths.items():
            wt = next((w for w in state["worktrees"] if norm(w["path"]) == key), {})
            agents = [{k: a[k] for k in ("paneKey", "agentType", "state", "lastAssistantMessage")}
                      for a in state["agents"] if norm(a["path"]) == key]
            rows.append({"worktreeId": wt.get("id", f"repo1::{path}"), "path": path, "agents": agents,
                         "status": "working" if any(a["state"] == "working" for a in agents) else "done"})
        result = {"worktrees": rows}
    elif cmd == "worktree set":
        w = next(w for w in state["worktrees"] if w["id"] == arg(args, "--worktree")[len("id:"):])
        w["workspaceStatus"] = arg(args, "--workspace-status")
        result = {"worktree": {"id": w["id"]}}
    elif cmd == "worktree rm":
        w = next(w for w in state["worktrees"] if w["id"] == arg(args, "--worktree")[len("id:"):])
        repo = next(r for r in state["repos"] if w["id"].startswith(r["id"] + "::"))
        subprocess.run(["git", "-C", repo["path"], "worktree", "remove", "--force", w["path"]], check=True,
                       capture_output=True, creationflags=0x08000000 if os.name == "nt" else 0)
        state["worktrees"].remove(w)
        state["agents"] = [a for a in state["agents"] if norm(a["path"]) != norm(w["path"])]
        result = {"removed": True}
    elif cmd == "terminal create":
        path = selector_path(state, arg(args, "--worktree"))
        n = len(state["agents"]) + 1
        agent = {"handle": f"term_{n}", "path": path, "agentType": arg(args, "--command").split()[0],
                 "command": arg(args, "--command"), "paneKey": f"tab{n}:leaf{n}", "state": "idle",
                 "lastAssistantMessage": None, "title": arg(args, "--title"), "sent": []}
        state["agents"].append(agent)
        result = {"terminal": {"handle": agent["handle"], "paneKey": agent["paneKey"], "worktreeId": f"repo1::{path}"}}
    elif cmd == "terminal wait":
        agent = next((a for a in state["agents"] if a["handle"] == arg(args, "--terminal")), {})
        if os.environ.get("FAKE_ORCA_TUI") == "never" or agent.get("state") == "working":
            error = "timeout"
        else:
            result = {"wait": {"satisfied": True}}
    elif cmd == "terminal read":
        a = next(a for a in state["agents"] if a["handle"] == arg(args, "--terminal"))
        result = {"terminal": {"tail": a.get("tail", os.environ.get("FAKE_ORCA_SCREEN", "").splitlines())}}
    elif cmd == "terminal list":
        path = selector_path(state, arg(args, "--worktree"))
        result = {"terminals": [{"handle": a["handle"], "agentIdentity": a["agentType"], "paneKey": a["paneKey"],
                                 "lastOutputAt": a.get("lastOutputAt")}
                                for a in state["agents"] if norm(a["path"]) == norm(path)]}
    elif cmd == "terminal send":
        a = next(a for a in state["agents"] if a["handle"] == arg(args, "--terminal"))
        if a.get("dialog"):
            error = "agent_prompt_blocked"
        else:
            a["sent"].append(arg(args, "--text"))
            a["state"] = "working"
            result = {"send": {"accepted": True, "prompt": {"stages": ["input_accepted"]
                      + (["turn_started"] if a.get("submitted", True) else [])}}}
    elif cmd == "terminal close":
        state["agents"] = [a for a in state["agents"] if a["handle"] != arg(args, "--terminal")]
        result = {"close": {"handle": arg(args, "--terminal")}}
    else:
        error = f"fake orca: unknown command {cmd}"
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if error:
        print(json.dumps({"ok": False, "error": {"code": error, "message": error}}))
        return 1
    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
