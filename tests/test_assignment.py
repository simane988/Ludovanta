"""Weighted assignment and read-only machine probes, with a temporary home and fake Codex."""
import json
from pathlib import Path

import pytest

from helpers import PLATFORM_DIR, REPO, read, write


@pytest.fixture
def assignment(monkeypatch):
    monkeypatch.syspath_prepend(str(PLATFORM_DIR))
    from ludovanta_lib import assignment
    return assignment


@pytest.mark.parametrize("weights", [{"claude": 2, "codex": 1}, {"codex": 0.5}, {"claude": 1, "codex": 0}])
def test_weights_valid(assignment, project, weights):
    write(project / "ludovanta.json", json.dumps({"agentWeights": weights}))
    assert assignment.validate_weights(assignment.load_config(project)) == weights


def test_local_weights_replace_the_whole_map(assignment, project):
    write(project / "ludovanta.json", '{"agentWeights": {"claude": 2, "codex": 1}}')
    write(project / "ludovanta.local.json", '{"agentWeights": {"claude": 1}}')
    assert assignment.validate_weights(assignment.load_config(project)) == {"claude": 1}


@pytest.mark.parametrize("weights, message", [({"gemini": 1}, "gemini"), ({"claude": -1}, "claude"),
    ({"claude": "1"}, "claude"), ({"claude": True}, "claude"), ({"claude": float("inf")}, "claude"),
    ({"claude": float("nan")}, "claude"), ({"claude": 0, "codex": 0}, "above zero"), ({}, "above zero"),
    ([], "object"), (None, "object")])
def test_invalid_weights(assignment, project, weights, message):
    from ludovanta_lib.common import LudovantaError
    write(project / "ludovanta.json", json.dumps({"agentWeights": weights}))
    cfg = assignment.load_config(project)
    with pytest.raises(LudovantaError, match="agentWeights.*" + message):
        assignment.validate_weights(cfg)


def test_missing_weights_preserve_the_default(assignment):
    assert assignment.validate_weights({}) is None


@pytest.mark.parametrize("mode, usable", [("task", True), ("fail", False), ("missing", False)])
def test_usability_is_cached(assignment, project, fake_codex_env, monkeypatch, mode, usable):
    monkeypatch.setenv("CODEX_PATH", fake_codex_env["CODEX_PATH"] if mode != "missing" else str(project / "absent"))
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    calls = []
    run = assignment._run

    def record(*args):
        calls.append(args)
        return run(*args)

    monkeypatch.setattr(assignment, "_run", record)
    probes = assignment.Agents(project)
    assert probes.usable("claude")[0]
    assert probes.usable("codex")[0] == usable
    assert probes.usable("codex")[0] == usable
    assert len(calls) == (0 if mode == "missing" else 1)
    if not usable:
        assert "codex login" in probes.usable("codex")[1]


def server(project):
    return {"command": "UnityRelay", "args": ["--project-path", str(project)]}


@pytest.mark.parametrize("source", ["project", "user", "user-project"])
def test_claude_configuration_is_read_only(assignment, project, source):
    path = project / ".mcp.json" if source == "project" else Path.home() / ".claude.json"
    data = {"mcpServers": {"relay": server(project)}}
    if source == "user-project":
        data = {"projects": {str(project): data}}
    write(path, json.dumps(data))
    before = path.read_bytes()
    probes = assignment.Agents(project)
    assert probes.unity("claude")[0]
    assert str(path) in probes.unity("claude")[1]
    assert path.read_bytes() == before


@pytest.mark.parametrize("other", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_codex_mcp_project_binding(assignment, project, fake_codex_env, monkeypatch, other, nested):
    config = Path.home() / ".codex/config.toml"
    write(config, "# agent-owned configuration\n")
    before = config.read_bytes()
    monkeypatch.setenv("CODEX_PATH", fake_codex_env["CODEX_PATH"])
    transport = server(project.parent / "other" if other else project)
    data = {"name": "unity-mcp", **({"transport": transport} if nested else transport)}
    monkeypatch.setenv("FAKE_CODEX_MCP", json.dumps([data]))
    assert assignment.Agents(project).unity("codex")[0] == (not other)
    assert config.read_bytes() == before


@pytest.mark.parametrize("answer", ["[]", "broken json", "{}", "[null]"])
def test_codex_empty_or_unreadable_mcp(assignment, project, fake_codex_env, monkeypatch, answer):
    monkeypatch.setenv("CODEX_PATH", fake_codex_env["CODEX_PATH"])
    monkeypatch.setenv("FAKE_CODEX_MCP", answer)
    found, source = assignment.Agents(project).unity("codex")
    assert not found
    if answer != "[]":
        assert "unreadable" in source


def test_mcp_overrides_and_other_claude_project(assignment, project):
    path = Path.home() / ".claude.json"
    write(path, json.dumps({"projects": {str(project.parent / "other"): {"mcpServers": {"unity": server(project)}}}}))
    write(project / ".mcp.json", json.dumps({"mcpServers": {"unity": server(project)}}))
    before = {p: p.read_bytes() for p in (path, project / ".mcp.json")}
    write(project / "ludovanta.local.json", '{"unityMcp": {"claude": false, "codex": true}}')
    probes = assignment.Agents(project)
    assert probes.unity("claude") == (False, "unityMcp.claude")
    assert probes.unity("codex") == (True, "unityMcp.codex")
    assert all(p.read_bytes() == b for p, b in before.items())
    (project / "ludovanta.local.json").unlink()
    (project / ".mcp.json").unlink()
    assert not assignment.Agents(project).unity("claude")[0]


def task(agent, size="S", status="in-progress", assigned="weights"):
    return {"agent": agent, "size": size, "status": status, "assigned": assigned}


def test_two_to_one_and_ties(assignment):
    tasks = []
    weights = {"claude": 2, "codex": 1}
    for _ in range(6):
        agent, _ = assignment.pick(tasks, "S", weights, list(weights))
        tasks.append(task(agent))
    assert [t["agent"] for t in tasks].count("claude") == 4
    assert [t["agent"] for t in tasks].count("codex") == 2
    assert assignment.pick([], "S", {"claude": 1, "codex": 1}, ["codex", "claude"])[0] == "claude"
    assert assignment.pick([task("claude")], "S", weights, list(weights))[0] == "claude"


def test_size_and_statuses_count(assignment):
    tasks = [task("claude", "L"), task("codex")]
    weights = {"claude": 1, "codex": 1}
    assert assignment.pick(tasks, "M", weights, list(weights))[0] == "codex"
    for status in ("todo", "dropped"):
        tasks = [task("codex", "L", status), task("claude", assigned="")]
        assert assignment.weighted_work(tasks) == {"claude": 0, "codex": 0}
    for status in ("in-progress", "review", "done", "blocked"):
        assert assignment.weighted_work([task("codex", "L", status)])["codex"] == 4
    tasks = [task("claude"), task("codex", "L")]
    assert assignment.pick(tasks, "S", weights, list(weights))[0] == "claude"
    tasks[1]["status"] = "dropped"
    assert assignment.pick(tasks, "S", weights, list(weights))[0] == "codex"


def test_small_positive_weights_still_choose_deterministically(assignment):
    agent, _ = assignment.pick([], "L", {"claude": 5e-324, "codex": 1e-323}, ["claude", "codex"])
    assert agent == "codex"


def test_readme_example(assignment):
    import re
    text = read(REPO / "README.md")
    examples = [json.loads(s) for s in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    example = next(e for e in examples if "agentWeights" in e and "unityMcp" in e)
    weights = example["agentWeights"]
    tasks = []
    for _ in range(6):
        agent, _ = assignment.pick(tasks, "S", weights, list(weights))
        tasks.append(task(agent))
    assert sum(t["agent"] == "claude" for t in tasks) == 4
