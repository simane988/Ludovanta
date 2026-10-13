#!/usr/bin/env python3
"""Install or update Ludovanta in a Unity project.

    python3 install.py --project /path/to/MyGame --source https://github.com/me/ludovanta.git --ref v0.1.4

Ownership model that keeps updates free of merge problems:
  * Platform-owned files (.ludovanta/**, <skillTarget>/ludovanta-*/**) are written only by this script.
    .ludovanta/lock.json records their content hashes. An update replaces them as a whole and deletes files
    that are gone from the new version.
  * Shared files (AGENTS.md, CLAUDE.md, .gitignore, .gitattributes) get exactly one managed block
    between '>>> ludovanta:managed' and '<<< ludovanta:managed' markers. Text outside it is never touched.
  * ludovanta.json (committed) and ludovanta.local.json (per machine) belong to the project. They are never
    overwritten; only the "ref"/"source" values are changed when --ref/--source are passed.
  * Local edits of platform-owned content are detected by hash, and the script stops without writing
    anything unless --force is given (then originals go to .ludovanta-backup/).
  * The output is deterministic: the same version always produces the same bytes (LF line endings,
    sorted lock file, no timestamps), so branches updated to the same version merge cleanly.

Exit codes: 0 done, 1 conflicts (nothing written), 2 error.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 9):
    print("LUDOVANTA_ERROR: Python 3.9+ is required, found " + sys.version.split()[0])
    sys.exit(2)

PLATFORM_ROOT = Path(__file__).resolve().parent
PAYLOAD = PLATFORM_ROOT / "payload"
BEGIN_TOKEN = ">>> ludovanta:managed"
END_TOKEN = "<<< ludovanta:managed"
LOCK_REL = ".ludovanta/lock.json"
BLOCK_FILES = [("AGENTS.md", "html"), ("CLAUDE.md", "html"), (".gitignore", "hash"), (".gitattributes", "hash")]
SKIP_PAYLOAD = {"__pycache__", ".DS_Store"}
DEFAULT_SKILL_TARGETS = (".claude/skills", ".agents/skills")   # Claude Code, Codex
BOM = b"\xef\xbb\xbf"


class InstallError(Exception):
    pass


# --- Text helpers -------------------------------------------------------------------
# Shared files may be in any encoding: decode with surrogateescape so their bytes round-trip unchanged.

def decode(data: bytes) -> str:
    if data.startswith(BOM):
        data = data[len(BOM):]
    return data.decode("utf-8", errors="surrogateescape")


def to_lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def text_hash(text: str) -> str:
    return hashlib.sha256(to_lf(text).encode("utf-8", errors="surrogateescape")).hexdigest()


def read_file(path: Path) -> str:
    return decode(path.read_bytes())


def write_file(path: Path, text: str, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8", errors="surrogateescape")
    path.write_bytes((BOM if bom else b"") + data)


def full(root: Path, rel: str) -> Path:
    return root.joinpath(*PurePosixPath(rel).parts)


def git(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True, errors="replace")
    except OSError as e:
        return 127, str(e)
    return p.returncode, p.stdout.strip()


# --- Payload --------------------------------------------------------------------------

def payload_files(folder: Path) -> dict[str, str]:
    """Relative posix path -> LF text for every file under folder."""
    result = {}
    if not folder.is_dir():
        return result
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or SKIP_PAYLOAD.intersection(path.relative_to(folder).parts) or path.suffix == ".pyc":
            continue
        result[path.relative_to(folder).as_posix()] = to_lf(read_file(path))
    return result


def skill_targets(cfg: dict | None) -> list[str]:
    targets = (cfg or {}).get("skillTargets") or list(DEFAULT_SKILL_TARGETS)
    result = []
    for t in targets:
        raw = str(t).replace("\\", "/").strip()
        n = raw.strip("/")
        if not n or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or ".." in n.split("/"):
            raise InstallError(f"ludovanta.json: invalid skillTargets entry '{t}' (must be a relative folder inside the project)")
        if n not in result:
            result.append(n)
    return result


# --- Managed blocks --------------------------------------------------------------------

def block_text(name: str, style: str, targets: list[str]) -> str:
    body = to_lf(read_file(PAYLOAD / "blocks" / name))
    body = body.replace("{{SKILL_EOL_RULES}}", "\n".join(f"/{t}/ludovanta-*/** text eol=lf" for t in targets)).rstrip("\n")
    note = "do not edit inside this block, it is overwritten by 'python3 .ludovanta/ludovanta.py update'"
    if style == "html":
        return f"<!-- {BEGIN_TOKEN}: {note} -->\n{body}\n<!-- {END_TOKEN} -->"
    return f"# {BEGIN_TOKEN}: {note}\n{body}\n# {END_TOKEN}"


def find_block(lines: list[str], name: str) -> tuple[int, int] | None:
    """From the first begin marker to the last end marker, so a block that got duplicated or mangled by
    a merge conflict is replaced as a whole."""
    begin = next((i for i, l in enumerate(lines) if BEGIN_TOKEN in l), -1)
    end = max((i for i, l in enumerate(lines) if END_TOKEN in l), default=-1)
    if begin < 0 and end < 0:
        return None
    if begin < 0 or end < begin:
        raise InstallError(f"{name} has broken ludovanta:managed markers; fix them by hand "
                           f"(keep one '{BEGIN_TOKEN}' line before one '{END_TOKEN}' line).")
    return begin, end


def current_block(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    lines = to_lf(read_file(path)).split("\n")
    pos = find_block(lines, name)
    return "\n".join(lines[pos[0]:pos[1] + 1]) if pos else None


def set_block(path: Path, name: str, block: str) -> bool:
    raw_bytes = path.read_bytes() if path.is_file() else b""
    raw = decode(raw_bytes)
    crlf = "\r\n" in raw
    text = to_lf(raw)
    lines = text.split("\n") if text else []
    pos = find_block(lines, name)
    if pos:
        new = "\n".join(lines[:pos[0]] + block.split("\n") + lines[pos[1] + 1:])
        if pos[1] == len(lines) - 1:
            new += "\n"
    elif not text.strip():
        new = block + "\n"
    else:
        new = text.rstrip("\n") + "\n\n" + block + "\n"
    if crlf:
        new = new.replace("\n", "\r\n")
    if new == raw:
        return False
    write_file(path, new, bom=raw_bytes.startswith(BOM))
    return True


# --- Lock and config --------------------------------------------------------------------

def read_lock(root: Path, force: bool) -> dict:
    path = full(root, LOCK_REL)
    empty = {"version": None, "files": {}, "blocks": {}}
    if not path.is_file():
        return empty
    try:
        data = json.loads(read_file(path))
    except ValueError:
        if not force:
            raise InstallError(f"{LOCK_REL} cannot be parsed (merge conflict?). "
                               "Re-run with --force to regenerate all Ludovanta files.")
        print(f"warning: {LOCK_REL} cannot be parsed, ignoring it (--force)")
        return empty
    return {"version": data.get("version"), "files": data.get("files") or {}, "blocks": data.get("blocks") or {}}


def format_lock(version: str, commit: str, files: dict, blocks: dict) -> str:
    data = {"schema": 1, "version": version, "commit": commit, "files": files, "blocks": blocks}
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def default_source() -> str:
    code, out = git("-C", str(PLATFORM_ROOT), "remote", "get-url", "origin")
    return out if code == 0 and out else str(PLATFORM_ROOT)


def default_ref(version: str) -> str:
    code, out = git("-C", str(PLATFORM_ROOT), "describe", "--tags", "--exact-match", "HEAD")
    return out if code == 0 and out else f"v{version}"


# --- Claude Code hooks ---------------------------------------------------------------------
# .claude/settings.json belongs to the project. Ludovanta owns only the hook handlers whose command runs
# .ludovanta/hook.sh: they are removed and re-added on every run, everything else is left as is.

SETTINGS_REL = ".claude/settings.json"
HOOK_MARKER = ".ludovanta/hook.sh"


def ludovanta_hooks() -> dict:
    def handler(event: str, timeout: int) -> dict:
        return {"type": "command", "shell": "bash", "timeout": timeout,
                "command": f'sh "$CLAUDE_PROJECT_DIR/{HOOK_MARKER}" {event}'}
    return {"SessionStart": [{"matcher": "startup|clear|compact", "hooks": [handler("session-start", 30)]}],
            "Stop": [{"hooks": [handler("stop", 30)]}]}


def merge_hooks(settings: dict, enabled: bool) -> dict:
    result = json.loads(json.dumps(settings))
    hooks = result.get("hooks") if isinstance(result.get("hooks"), dict) else {}
    for event in list(hooks):
        groups = []
        for group in hooks[event] if isinstance(hooks[event], list) else []:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                group = dict(group, hooks=[h for h in group["hooks"]
                                           if HOOK_MARKER not in str(h.get("command", "") if isinstance(h, dict) else "")])
                if not group["hooks"]:
                    continue
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if enabled:
        for event, groups in ludovanta_hooks().items():
            hooks.setdefault(event, []).extend(groups)
    if hooks:
        result["hooks"] = hooks
    else:
        result.pop("hooks", None)
    return result


def plan_settings(root: Path, targets: list[str], cfg: dict | None) -> tuple[str, bool] | None:
    """New text for .claude/settings.json, or None when nothing changes."""
    enabled = ".claude/skills" in targets and (cfg or {}).get("claudeHooks", True) is not False
    path = full(root, SETTINGS_REL)
    raw = path.read_bytes() if path.is_file() else b""
    if not raw.strip():
        if not enabled:
            return None
        current = {}
    else:
        try:
            current = json.loads(decode(raw))
        except ValueError as e:
            raise InstallError(f"{SETTINGS_REL} is not valid JSON ({e}); fix it, then run the update again")
        if not isinstance(current, dict):
            raise InstallError(f"{SETTINGS_REL} must contain a JSON object")
    merged = merge_hooks(current, enabled)
    if merged == current and raw.strip():
        return None
    text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    return text, raw.startswith(BOM)


def replace_json_string(text: str, key: str, value: str) -> str:
    """Targeted replace keeps the user's formatting and other keys untouched."""
    rx = re.compile(r'"%s"\s*:\s*"(?:[^"\\]|\\.)*"' % re.escape(key))
    return rx.sub(lambda m: f'"{key}": {json.dumps(value)}', text, count=1)


# --- Main ----------------------------------------------------------------------------------

def install(project: str, source: str | None, ref: str | None, commit: str | None, force: bool, dry_run: bool) -> int:
    version = read_file(PLATFORM_ROOT / "VERSION").strip()
    if not commit:
        code, out = git("-C", str(PLATFORM_ROOT), "rev-parse", "HEAD")
        commit = out if code == 0 else ""
    root = Path(project).resolve()
    if not (root / "ProjectSettings" / "ProjectVersion.txt").is_file():
        raise InstallError(f"{root} is not a Unity project root (no ProjectSettings/ProjectVersion.txt)")

    cfg_path = root / "ludovanta.json"
    cfg = None
    if cfg_path.is_file():
        try:
            cfg = json.loads(read_file(cfg_path))
        except ValueError as e:
            raise InstallError(f"ludovanta.json is not valid JSON: {e}")
    targets = skill_targets(cfg)
    old = read_lock(root, force)

    # Desired state: relative path -> LF text.
    desired = dict(payload_files(PAYLOAD / "files"))
    for rel, text in payload_files(PAYLOAD / "skills").items():
        for t in targets:
            desired[f"{t}/{rel}"] = text

    # Plan files.
    plan: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    for rel in sorted(desired):
        path = full(root, rel)
        if not path.is_file():
            plan.append(("add", rel))
            continue
        cur = text_hash(read_file(path))
        if cur == text_hash(desired[rel]):
            plan.append(("same", rel))
            continue
        plan.append(("update", rel))
        if rel.endswith(".meta"):
            continue   # Unity rewrites .meta files of the editor package itself: not a user's edit
        if rel not in old["files"]:
            conflicts.append((rel, "exists but is not managed by Ludovanta"))
        elif old["files"][rel] != cur:
            conflicts.append((rel, "modified locally"))
    for rel in sorted(old["files"]):
        path = full(root, rel)
        if rel in desired or not path.is_file():
            continue
        plan.append(("remove", rel))
        if not rel.endswith(".meta") and text_hash(read_file(path)) != old["files"][rel]:
            conflicts.append((rel, "modified locally, removed in the new version"))

    # Plan blocks.
    blocks = {}
    for name, style in BLOCK_FILES:
        blocks[name] = block_text(name, style, targets)
        cur = current_block(root / name, name)
        if cur is None or cur == blocks[name]:
            continue
        if name in old["blocks"] and old["blocks"][name] != text_hash(cur):
            conflicts.append((name, "ludovanta:managed block edited locally"))

    settings = plan_settings(root, targets, cfg)

    # Report.
    print(f"{'[dry-run] ' if dry_run else ''}Ludovanta {old['version'] or 'none'} -> {version} in {root}")
    marks = {"add": "+", "update": "~", "remove": "-"}
    for op, rel in plan:
        if op in marks:
            print(f"  {marks[op]} {rel}")
    if settings:
        print(f"  ~ {SETTINGS_REL} (Ludovanta hooks)")
    same = sum(1 for op, _ in plan if op == "same")
    if same:
        print(f"  = {same} file(s) unchanged")

    if conflicts:
        print("\nPlatform-owned content was changed outside Ludovanta:")
        for rel, why in conflicts:
            print(f"  ! {rel}: {why}")
        if not force:
            print("\nNothing was written. Move customizations to project-owned places (own skills without the ludovanta-\n"
                  "prefix, text outside ludovanta:managed blocks), or re-run with --force to back up the changed files\n"
                  "to .ludovanta-backup/ and overwrite them.")
            return 1
    if dry_run:
        return 0

    code, out = git("-C", str(root), "status", "--porcelain", "--", ".ludovanta", "ludovanta.json", "AGENTS.md", "CLAUDE.md",
                    ".gitignore", ".gitattributes", SETTINGS_REL)
    if code == 0 and out:
        print("warning: Ludovanta-managed paths already had uncommitted changes before this run.")

    if conflicts:
        backup = root / ".ludovanta-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
        for rel, _ in conflicts:
            src = full(root, rel)
            if src.is_file():
                dst = full(backup, rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        print(f"  backup: {backup.relative_to(root).as_posix()}/")

    # Apply files.
    lock_files = {}
    for op, rel in plan:
        path = full(root, rel)
        if op == "remove":
            path.unlink()
            parent = path.parent
            while parent != root and root in parent.parents and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            continue
        if op != "same":
            write_file(path, desired[rel])
        lock_files[rel] = text_hash(desired[rel])

    # Apply blocks.
    lock_blocks = {}
    for name, _ in BLOCK_FILES:
        if set_block(root / name, name, blocks[name]):
            print(f"  block: {name}")
        lock_blocks[name] = text_hash(blocks[name])

    if settings:
        write_file(full(root, SETTINGS_REL), settings[0], bom=settings[1])

    # Project config: created once, afterwards only explicitly passed values change.
    if not cfg_path.is_file():
        cfg_text = json.dumps({"source": source or default_source(), "ref": ref or default_ref(version),
                               "skillTargets": targets}, indent=2) + "\n"
        write_file(cfg_path, cfg_text)
        print("  + ludovanta.json")
    else:
        text = read_file(cfg_path)
        new = text
        if ref and cfg.get("ref") != ref:
            new = replace_json_string(new, "ref", ref)
        if source and cfg.get("source") != source:
            new = replace_json_string(new, "source", source)
        if new != text:
            write_file(cfg_path, new, bom=cfg_path.read_bytes().startswith(BOM))
            print("  ~ ludovanta.json")

    write_file(full(root, LOCK_REL), format_lock(version, commit, lock_files, lock_blocks))

    skills = " ".join(f'"{t}/ludovanta-*"' for t in targets)
    if full(root, SETTINGS_REL).is_file():
        skills += f" {SETTINGS_REL}"
    print(f"\nLudovanta {version} installed. Review and commit the platform changes separately, e.g.:\n"
          f"  git add -A .ludovanta ludovanta.json AGENTS.md CLAUDE.md .gitignore .gitattributes {skills}\n"
          f'  git commit -m "chore(ludovanta): update to {version}"')
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="Install or update Ludovanta in a Unity project.")
    parser.add_argument("--project", required=True, help="Unity project root")
    parser.add_argument("--source", help="where future updates come from (git URL or local folder); stored in ludovanta.json")
    parser.add_argument("--ref", help="version pin (git tag or branch); stored in ludovanta.json")
    parser.add_argument("--commit", help="commit of the platform being installed (recorded in the lock file)")
    parser.add_argument("--force", action="store_true", help="overwrite locally modified platform content (with backup)")
    parser.add_argument("--dry-run", action="store_true", help="only show what would change")
    a = parser.parse_args(argv)
    try:
        return install(a.project, a.source, a.ref, a.commit, a.force, a.dry_run)
    except (InstallError, OSError) as e:
        print(f"LUDOVANTA_ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
