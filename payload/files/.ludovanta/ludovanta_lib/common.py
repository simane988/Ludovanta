"""Shared helpers for Ludovanta commands: project lookup, Unity discovery, running Unity, output.

Managed by Ludovanta - do not edit in a game project, changes are overwritten on update.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

EXIT_OK = 0           # success
EXIT_PROBLEMS = 1     # project problems the agent should fix (compile errors, failed tests, bad assets)
EXIT_INFRA = 2        # Unity / environment failure (not found, license, crash) - not the agent's code
EXIT_EDITOR_OPEN = 3  # project is open in another Unity instance - use live mode (Unity MCP)
EXIT_TIMEOUT = 4

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"


class LudovantaError(Exception):
    """Environment or usage problem; reported as LUDOVANTA_ERROR with exit code 2."""


# --- Paths ---------------------------------------------------------------------

def slash(path) -> str:
    return str(path).replace("\\", "/")


def relpath(root: Path, path) -> str:
    """Project-relative path with forward slashes, or the path unchanged if outside the project."""
    r = slash(root).rstrip("/") + "/"
    p = slash(path)
    if p.casefold().startswith(r.casefold()):
        return p[len(r):]
    return p


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig", errors="replace")


def write_lf(path: Path, text: str) -> None:
    """UTF-8 with LF line endings on every OS (Path.write_text has no 'newline' argument before Python 3.10)."""
    Path(path).write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


# --- Project -------------------------------------------------------------------

def find_project_root(start=None) -> Path:
    path = Path(start or os.getcwd()).resolve()
    for d in [path, *path.parents]:
        if (d / "ProjectSettings" / "ProjectVersion.txt").is_file():
            return d
    raise LudovantaError(f"Unity project root not found from '{path}' (no ProjectSettings/ProjectVersion.txt).")


def unity_version(root: Path) -> str:
    for line in read_text(root / "ProjectSettings" / "ProjectVersion.txt").splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    raise LudovantaError("m_EditorVersion not found in ProjectSettings/ProjectVersion.txt.")


def load_config(root: Path) -> dict:
    """ludovanta.json is committed and shared; ludovanta.local.json is per machine (gitignored) and wins."""
    cfg: dict = {}
    for name in ("ludovanta.json", "ludovanta.local.json"):
        path = root / name
        if path.is_file():
            try:
                cfg.update(json.loads(read_text(path)))
            except ValueError as e:
                raise LudovantaError(f"{name} is not valid JSON: {e}")
    return cfg


def _hub_secondary_path() -> str | None:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", ""))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    path = base / "UnityHub" / "secondaryInstallPath.json"
    try:
        value = json.loads(read_text(path))
        return value if isinstance(value, str) and value else None
    except (OSError, ValueError):
        return None


def _editor_in(folder: Path) -> Path:
    if IS_WINDOWS:
        return folder / "Editor" / "Unity.exe"
    if IS_MAC:
        return folder / "Unity.app" / "Contents" / "MacOS" / "Unity"
    return folder / "Editor" / "Unity"


def resolve_unity(root: Path) -> Path:
    version = unity_version(root)
    cfg = load_config(root)
    candidates: list[Path] = []
    for explicit in (os.environ.get("UNITY_EDITOR_PATH"), cfg.get("unityEditorPath")):
        if explicit:
            p = Path(explicit).expanduser()
            if p.suffix == ".app":
                p = p / "Contents" / "MacOS" / "Unity"
            candidates.append(p)

    if IS_WINDOWS:
        hubs = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Unity" / "Hub" / "Editor"]
    elif IS_MAC:
        hubs = [Path("/Applications/Unity/Hub/Editor")]
    else:
        hubs = [Path.home() / "Unity" / "Hub" / "Editor"]
    secondary = _hub_secondary_path()
    if secondary:
        hubs.append(Path(secondary))
    candidates += [_editor_in(hub / version) for hub in hubs]

    for c in candidates:
        if c.is_file():
            return c
    raise LudovantaError(
        f"Unity {version} not found. Install it via Unity Hub or set UNITY_EDITOR_PATH / "
        f"'unityEditorPath' in ludovanta.local.json. Checked: " + "; ".join(str(c) for c in candidates))


# --- Is the project open in another Unity instance? -----------------------------

def _locked_windows(lock: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, no_sharing, open_existing, normal = 0x80000000, 0, 3, 0x80
    handle = kernel32.CreateFileW(str(lock), generic_read, no_sharing, None, open_existing, normal, None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        # 32 = sharing violation, 33 = lock violation, 5 = access denied: someone holds the file.
        return ctypes.get_last_error() in (5, 32, 33)
    kernel32.CloseHandle(handle)
    return False   # stale lockfile left by a crashed Editor


def _locked_posix(lock: Path) -> bool:
    import fcntl

    try:
        fd = os.open(lock, os.O_RDWR)
    except OSError:
        return False
    try:
        for locker in (fcntl.flock, fcntl.lockf):
            try:
                locker(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locker(fd, fcntl.LOCK_UN)
            except OSError:
                return True
        return False
    finally:
        os.close(fd)


def _unity_process_for(root: Path) -> bool:
    try:
        out = subprocess.run(["ps", "-Ao", "args"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    # Unity Hub and batchmode runs both pass the project as '-projectPath <path>'.
    needle = "-projectpath " + slash(root).rstrip("/").casefold()
    return any(needle in slash(line).casefold() for line in out.splitlines())


def editor_open(root: Path) -> bool:
    """True when another Unity instance (Editor or batchmode run) holds this project."""
    lock = root / "Temp" / "UnityLockfile"
    if not lock.exists():
        return False
    if IS_WINDOWS:
        return _locked_windows(lock)
    return _locked_posix(lock) or _unity_process_for(root)


# --- Running Unity ---------------------------------------------------------------

def new_log_path(root: Path, kind: str, keep: int = 20) -> Path:
    folder = root / "Logs" / "ludovanta"
    folder.mkdir(parents=True, exist_ok=True)
    old = sorted(folder.glob(f"{kind}-*.log"), reverse=True)
    for log in old[keep:]:
        for p in (log, log.with_suffix(".xml")):
            try:
                p.unlink()
            except OSError:
                pass
    now = datetime.now()
    return folder / f"{kind}-{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}.log"


def run_unity(exe: Path, args: list[str], timeout_sec: int) -> dict:
    flags = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW
    start = time.monotonic()
    proc = subprocess.Popen([str(exe), *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        code = proc.wait(timeout=timeout_sec)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        code, timed_out = -1, True
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.monotonic() - start, 1)}


def spawn_detached(root: Path, *args: str) -> None:
    """Starts 'ludovanta.py <args>' for this project in the background: it outlives the caller (a hook, a command)."""
    cli = Path(__file__).resolve().parent.parent / "ludovanta.py"
    if IS_WINDOWS:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: outlives the caller, no console window.
        kwargs = {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}
    else:
        kwargs = {"start_new_session": True}
    subprocess.Popen([sys.executable, "-B", str(cli), "--project", str(root), *args], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, cwd=str(root), **kwargs)


# --- Output ------------------------------------------------------------------------

def finish(status: str, code: int, lines: list[str], data: dict | None = None, as_json: bool = False) -> int:
    if as_json:
        payload = dict(data or {})
        payload["status"] = status
        payload["exitCode"] = code
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for line in lines:
            print(line)
    return code
