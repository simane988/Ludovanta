"""install.py and 'ludovanta.py update': ownership model, conflict detection, determinism, merges."""
import json

import pytest

from helpers import INSTALL, REPO, git, git_status, lock, read, run_py, write

VERSION = read(REPO / "VERSION").strip()


def install(project, *args, installer=INSTALL):
    return run_py(installer, "--project", str(project), *args)


def update(project, *args):
    return run_py(project / ".ludovanta" / "ludovanta.py", "update", *args)


# --- first install -------------------------------------------------------------------------

def test_installs_platform_files(installed_project):
    p = installed_project
    for rel in (".ludovanta/ludovanta.py", ".ludovanta/ludovanta_lib/commands.py", ".ludovanta/AGENTS.platform.md",
                ".claude/skills/ludovanta-unity-compile/SKILL.md", ".claude/skills/ludovanta-platform-update/SKILL.md"):
        assert (p / rel).is_file(), rel
    assert lock(p)["version"] == VERSION
    assert not list(p.rglob("__pycache__"))


def test_keeps_user_content(installed_project):
    p = installed_project
    assert "mine" in read(p / ".claude/skills/my-skill/SKILL.md")
    agents = read(p / "AGENTS.md")
    assert agents.startswith("# My game\n\nUser rules for agents.\n")
    assert ">>> ludovanta:managed" in agents and "<<< ludovanta:managed" in agents
    assert "@.ludovanta/AGENTS.platform.md" in read(p / "CLAUDE.md")


def test_preserves_crlf_in_shared_files(installed_project):
    gitignore = read(installed_project / ".gitignore")
    assert "/[Ll]ibrary/\r\n" in gitignore
    assert "/ludovanta.local.json\r\n" in gitignore
    assert "\n" not in gitignore.replace("\r\n", "")


def test_creates_config(installed_project):
    cfg = json.loads(read(installed_project / "ludovanta.json"))
    assert cfg == {"source": "https://example.com/ludovanta.git", "ref": "v0.1.0", "skillTargets": [".claude/skills"]}
    assert "/.claude/skills/ludovanta-*/** text eol=lf" in read(installed_project / ".gitattributes")


def test_rejects_non_unity_folder(tmp_path):
    code, out = install(tmp_path)
    assert code == 2, out
    assert "not a Unity project root" in out


# --- idempotency -----------------------------------------------------------------------------

def test_second_install_changes_nothing(installed_project):
    code, out = install(installed_project)
    assert code == 0, out
    assert git_status(installed_project) == ""


def test_dry_run_does_not_write(installed_project):
    target = installed_project / ".ludovanta/ludovanta_lib/parsers.py"
    target.unlink()
    code, out = install(installed_project, "--dry-run")
    assert code == 0, out
    assert "+ .ludovanta/ludovanta_lib/parsers.py" in out
    assert not target.exists()


# --- local changes -----------------------------------------------------------------------------

def test_modified_platform_file_blocks_update(installed_project):
    target = installed_project / ".ludovanta/AGENTS.platform.md"
    write(target, read(target) + "local hack\n")
    code, out = install(installed_project)
    assert code == 1, out
    assert "AGENTS.platform.md: modified locally" in out
    assert "local hack" in read(target), "nothing is written on conflict"


def test_force_backs_up_and_restores(installed_project):
    target = installed_project / ".ludovanta/AGENTS.platform.md"
    write(target, read(target) + "local hack\n")
    code, out = install(installed_project, "--force")
    assert code == 0, out
    assert "local hack" not in read(target)
    [backup] = (installed_project / ".ludovanta-backup").rglob("AGENTS.platform.md")
    assert "local hack" in read(backup)
    assert git_status(installed_project) == "", "backups are gitignored"


def test_edited_managed_block_blocks_update(installed_project):
    agents = installed_project / "AGENTS.md"
    write(agents, read(agents).replace("Skills named", "EDITED Skills named"))
    code, out = install(installed_project)
    assert code == 1, out
    assert "AGENTS.md: ludovanta:managed block edited locally" in out
    code, out = install(installed_project, "--force")
    assert code == 0, out
    assert git_status(installed_project) == ""


def test_text_around_block_is_kept(installed_project):
    agents = installed_project / "AGENTS.md"
    write(agents, read(agents) + "\n## Project rules\n\nUse tabs.\n")
    code, out = install(installed_project)
    assert code == 0, out
    assert read(agents).endswith("## Project rules\n\nUse tabs.\n")


def test_unmanaged_file_with_platform_name(project):
    write(project / ".claude/skills/ludovanta-unity-test/SKILL.md", "my own file\n")
    code, out = install(project)
    assert code == 1, out
    assert "exists but is not managed by Ludovanta" in out


# --- new versions ------------------------------------------------------------------------------

def test_new_version_replaces_and_removes(installed_project, copy_platform):
    p = installed_project
    write(p / "AGENTS.md", read(p / "AGENTS.md") + "\nUse tabs.\n")
    v2 = copy_platform("platform-v2")
    write(v2 / "VERSION", "0.2.0\n")
    (v2 / "payload/files/.ludovanta/ludovanta_lib/parsers.py").unlink()
    skill = v2 / "payload/skills/ludovanta-unity-test/SKILL.md"
    write(skill, read(skill) + "\nNew rule from v2.\n")
    write(v2 / "payload/blocks/AGENTS.md", "## Ludovanta v2 block\n")

    code, out = install(p, installer=v2 / "install.py")
    assert code == 0, out
    assert not (p / ".ludovanta/ludovanta_lib/parsers.py").exists(), "files removed from the platform are deleted"
    assert "New rule from v2" in read(p / ".claude/skills/ludovanta-unity-test/SKILL.md")
    agents = read(p / "AGENTS.md")
    assert agents.startswith("# My game") and "v2 block" in agents and "Use tabs." in agents
    assert lock(p)["version"] == "0.2.0"


def test_skill_targets_added_and_removed(installed_project):
    p = installed_project
    cfg = json.loads(read(p / "ludovanta.json"))

    cfg["skillTargets"] = [".claude/skills", ".agents/skills"]
    write(p / "ludovanta.json", json.dumps(cfg, indent=2) + "\n")
    code, out = install(p)
    assert code == 0, out
    assert (p / ".agents/skills/ludovanta-unity-test/SKILL.md").is_file()
    assert "/.agents/skills/ludovanta-*/** text eol=lf" in read(p / ".gitattributes")

    cfg["skillTargets"] = [".agents/skills"]
    write(p / "ludovanta.json", json.dumps(cfg, indent=2) + "\n")
    code, out = install(p)
    assert code == 0, out
    assert not (p / ".claude/skills/ludovanta-unity-test").exists()
    assert (p / ".claude/skills/my-skill/SKILL.md").is_file(), "user skill survives target cleanup"


@pytest.mark.parametrize("target", ["../outside", "/abs/path", "C:/abs", ""])
def test_invalid_skill_target(installed_project, target):
    write(installed_project / "ludovanta.json", json.dumps({"source": "x", "ref": "y", "skillTargets": [target]}))
    code, out = install(installed_project)
    assert code == 2, out
    assert "invalid skillTargets" in out


def test_conflict_markers_are_regenerated(installed_project):
    p = installed_project
    agents = read(p / "AGENTS.md")
    start, end = agents.index("## Ludovanta"), agents.index("<!-- <<< ludovanta:managed")
    write(p / "AGENTS.md", agents[:start] + "<<<<<<< HEAD\n## ours\n=======\n## theirs\n>>>>>>> other\n" + agents[end:])
    write(p / ".ludovanta/lock.json", "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")

    code, out = install(p)
    assert code == 2, out
    assert "cannot be parsed" in out
    code, out = install(p, "--force")
    assert code == 0, out
    assert git_status(p) == ""


# --- updates from a git source ----------------------------------------------------------------

@pytest.fixture
def pinned_project(make_project, origin):
    """Project installed from the origin repo, pinned to v1.0.0 via `ludovanta.py update`, committed."""
    repo, url = origin
    p = make_project()
    code, out = install(p, "--source", url, "--ref", "v1.0.0", installer=repo / "install.py")
    assert code == 0, out
    code, out = update(p)
    assert code == 0, out
    git(p, "add", "-A")
    git(p, "commit", "--quiet", "-m", "ludovanta 1.0.0")
    return p


def test_update_installs_pinned_tag(pinned_project, origin):
    repo, _ = origin
    assert lock(pinned_project)["version"] == "1.0.0", "the pinned tag, not the source HEAD"
    assert lock(pinned_project)["commit"] == git(repo, "rev-parse", "v1.0.0").stdout.strip()


def test_update_to_other_ref_and_back(pinned_project):
    code, out = update(pinned_project, "--ref", "v1.1.0")
    assert code == 0, out
    assert lock(pinned_project)["version"] == "1.1.0"
    assert (pinned_project / ".ludovanta/NEW.md").is_file()
    assert json.loads(read(pinned_project / "ludovanta.json"))["ref"] == "v1.1.0", "--ref updates the pin"

    code, out = update(pinned_project, "--ref", "v1.0.0")
    assert code == 0, out
    assert lock(pinned_project)["version"] == "1.0.0"
    assert not (pinned_project / ".ludovanta/NEW.md").exists(), "downgrade removes newer files"


def test_branches_updated_to_same_version_merge_cleanly(pinned_project):
    p = pinned_project
    git(p, "checkout", "--quiet", "-b", "feature-a")
    assert update(p, "--ref", "v1.1.0")[0] == 0
    git(p, "add", "-A")
    git(p, "commit", "--quiet", "-m", "ludovanta 1.1.0 on a")

    git(p, "checkout", "--quiet", "main")
    git(p, "checkout", "--quiet", "-b", "feature-b")
    write(p / "Assets/Game.cs", "class Game {}")
    write(p / "AGENTS.md", read(p / "AGENTS.md") + "\nTeam B rule.\n")
    assert update(p, "--ref", "v1.1.0")[0] == 0
    git(p, "add", "-A")
    git(p, "commit", "--quiet", "-m", "work + ludovanta 1.1.0 on b")

    merge = git(p, "merge", "--no-edit", "feature-a", check=False)
    assert merge.returncode == 0, merge.stdout + merge.stderr
    assert "Team B rule." in read(p / "AGENTS.md")


def test_update_unknown_ref_leaves_project_untouched(pinned_project):
    code, out = update(pinned_project, "--ref", "v9.9.9")
    assert code == 2, out
    assert "git clone failed" in out
    assert lock(pinned_project)["version"] == "1.0.0"
    assert git_status(pinned_project) == ""
