"""ludovanta.py screenshot: batchmode capture through the fake Unity, and the open Editor through request files."""
import json
import threading
import time

import pytest

from fake_unity import answer
from helpers import PLATFORM_DIR, REPO, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"
PACKAGE = REPO / "payload" / "files" / "Packages" / "com.ludovanta.editor"


def cli(project, *args, env=None):
    return run_py(CLI, "--project", str(project), "screenshot", *args, env=env)


@pytest.fixture
def game(project):
    write(project / "Packages/com.ludovanta.editor/package.json", "{}")
    write(project / "Assets/Scenes/City.unity", "scene")
    return project


@pytest.mark.parametrize("mode, args, exit_code, expected", [
    ("ok", ["--scene", "Assets/Scenes/City.unity", "--label", "T-012-before"], 0,
     ["SCREENSHOT (HEADLESS, batchmode): 1 image(s), 1280x720, camera 'Main Camera', scene Assets/Scenes/City.unity, "
      "edit mode", "Logs/ludovanta/screenshots/T-012-before.png"]),
    ("ok", ["--play", "2", "--frames", "3", "--size", "640x360", "--camera", "Chase"], 0,
     ["3 image(s), 640x360, camera 'Chase'", "Play mode", "-01.png", "-03.png"]),
    ("capture_uniform", [], 0, ["warning: an image is one flat colour"]),
    ("capture_error", ["--camera", "Nope"], 1, ["SCREENSHOT_FAILED (HEADLESS, batchmode): camera 'Nope' not found"]),
    ("compile_error", [], 1, ["COMPILE_FAILED: the project does not compile, no screenshot"]),
    ("no_package", [], 2, ["PACKAGE_MISSING: Unity does not know Ludovanta.Editor.Capture"]),
    ("license", [], 2, ["UNITY_FAILED: Unity exited with code 1 without a picture", "reason: Unity license problem"]),
], ids=["label", "play-series", "uniform", "no-camera", "compile-errors", "package-not-compiled", "license"])
def test_batchmode(game, fake_unity_env, mode, args, exit_code, expected):
    code, out = cli(game, *args, env={**fake_unity_env, "FAKE_UNITY_MODE": mode})
    assert code == exit_code, out
    for line in expected:
        assert line in out
    if exit_code == 0:
        [log] = (game / "Logs/ludovanta").glob("screenshot-*.log")
        text = log.read_text(encoding="utf-8")
        assert "-executeMethod Ludovanta.Editor.Capture.Batch -ludovantaRequest" in text
        assert "-nographics" not in text and "-quit" not in text


def test_files_exist_and_json(game, fake_unity_env):
    code, out = cli(game, "--label", "after", "--json", env={**fake_unity_env, "FAKE_UNITY_MODE": "ok"})
    assert code == 0, out
    data = json.loads(out)
    assert data["files"] == ["Logs/ludovanta/screenshots/after.png"]
    assert (game / data["files"][0]).read_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize("args, expected", [
    (["--size", "big"], "--size must look like 1280x720"),
    (["--scene", "Assets/Nope.unity"], "scene not found: Assets/Nope.unity"),
    (["--frames", "0"], "--frames must be between 1 and 60"),
    (["--out", "../outside.png"], "--out must be a path inside the project"),
])
def test_bad_arguments(game, args, expected):
    code, out = cli(game, *args)
    assert code == 2 and expected in out, out


def test_package_missing(project):
    code, out = cli(project)
    assert code == 2 and out.startswith("PACKAGE_MISSING: Packages/com.ludovanta.editor/package.json"), out


def _editor(project, mode="ok", stop=None):
    """Plays the open Editor: takes a request like Capture.cs does and answers it."""
    folder = project / "Temp/ludovanta/capture"
    while not stop.is_set():
        for req in folder.glob("*.request.json") if folder.is_dir() else []:
            taken = req.with_name(req.name + ".taken")
            req.rename(taken)
            request = json.loads(taken.read_text(encoding="utf-8"))
            (folder / f"{request['id']}.result.json").write_text(json.dumps(answer(request, mode)), encoding="utf-8")
        time.sleep(0.05)


def test_live_editor_answers(game, held_lockfile):
    stop = threading.Event()
    editor = threading.Thread(target=_editor, args=(game, "ok", stop), daemon=True)
    editor.start()
    try:
        code, out = cli(game, "--label", "live")
    finally:
        stop.set()
        editor.join(5)
    assert code == 0, out
    assert out.startswith("SCREENSHOT (LIVE, open Editor): 1 image(s)")
    assert (game / "Logs/ludovanta/screenshots/live.png").is_file()


def test_live_editor_not_answering(game, held_lockfile):
    code, out = cli(game, "--timeout", "1")
    assert code == 2, out
    assert out.startswith("EDITOR_NOT_ANSWERING")
    assert not list((game / "Temp/ludovanta/capture").glob("*.request.json")), "the stale request is removed"


def test_package_files_are_consistent():
    """The editor package is installed as platform files: fixed GUIDs, a .meta for every file, LF-safe."""
    files = sorted(p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*") if p.is_file())
    assert files == ["Editor.meta", "Editor/Capture.cs", "Editor/Capture.cs.meta", "Editor/Ludovanta.Editor.asmdef",
                     "Editor/Ludovanta.Editor.asmdef.meta", "package.json", "package.json.meta"]
    guids = [line.split()[1] for p in PACKAGE.rglob("*.meta") for line in p.read_text().splitlines()
             if line.startswith("guid:")]
    assert len(guids) == len(set(guids)) == 4 and all(len(g) == 32 for g in guids)
    version = (REPO / "VERSION").read_text().strip()
    assert json.loads((PACKAGE / "package.json").read_text())["version"] == version, "bump the package with VERSION"
    source = (PACKAGE / "Editor/Capture.cs").read_text(encoding="utf-8")
    assert "public static void Batch()" in source and "namespace Ludovanta.Editor" in source
    assert source.count("{") == source.count("}")
