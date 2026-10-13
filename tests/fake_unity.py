"""Stand-in for the Unity executable in tests. Behaviour is chosen by the FAKE_UNITY_MODE env var.

    ok, compile_error, license, tests_fail   fixed outcomes
    tests_flaky        Subtracts fails on odd runs and passes on even ones (run counter: FAKE_UNITY_COUNTER file)
    tests_quarantine   Subtracts fails but is in category Flaky; the TimerTests fixture is quarantined as a whole
"""
import json
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PASSING_RESULTS = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="2" result="Passed" total="2" passed="2" failed="0" inconclusive="0" skipped="0" duration="0.1">
  <test-case id="1" name="A" fullname="Game.Tests.A" result="Passed" />
  <test-case id="2" name="B" fullname="Game.Tests.B" result="Passed" />
</test-run>
"""


def arg(name):
    args = sys.argv[1:]
    return args[args.index(name) + 1] if name in args else None


def next_run() -> int:
    counter = Path(os.environ["FAKE_UNITY_COUNTER"])
    n = int(counter.read_text()) + 1 if counter.is_file() else 1
    counter.write_text(str(n))
    return n


def results_xml(suites) -> str:
    """suites: [(fixture categories, [(fullname, passed, case categories)])], filtered by -testFilter regexes."""
    patterns = [p for p in (arg("-testFilter") or "").split(";") if p]
    total = passed = 0
    body = []
    for suite_cats, cases in suites:
        props = "".join(f'<property name="Category" value="{c}" />' for c in suite_cats)
        body.append(f'  <test-suite type="TestFixture" name="Fixture"><properties>{props}</properties>')
        for name, ok, cats in cases:
            if patterns and not any(re.search(p, name) for p in patterns):
                continue
            total += 1
            passed += ok
            case_props = "".join(f'<property name="Category" value="{c}" />' for c in cats)
            failure = "" if ok else ("<failure><message><![CDATA[Expected: 1\n  But was:  2]]></message>"
                                     "<stack-trace><![CDATA[at X () in /p/Assets/Tests/T.cs:9]]></stack-trace></failure>")
            body.append(f'    <test-case name="{name.rsplit(".", 1)[1]}" fullname="{name}" '
                        f'result="{"Passed" if ok else "Failed"}" duration="0.01"><properties>{case_props}</properties>'
                        f'{failure}</test-case>')
        body.append("  </test-suite>")
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<test-run id="2" result="{"Passed" if passed == total else "Failed"}" '
            f'total="{total}" passed="{passed}" failed="{total - passed}" inconclusive="0" skipped="0" duration="0.2">\n'
            + "\n".join(body) + "\n</test-run>\n")


def png() -> bytes:
    """A valid 1x1 PNG."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30")) + chunk(b"IEND", b""))


def capture(mode: str) -> tuple[str, int]:
    """-executeMethod Ludovanta.Editor.Capture.Batch: answers like Capture.cs (modes: ok, capture_uniform,
    capture_error; compile_error and no_package write no result)."""
    if mode == "compile_error":
        return (FIXTURES / "compile-errors.log").read_text(encoding="utf-8"), 1
    if mode == "no_package":
        return "executeMethod class 'Ludovanta.Editor.Capture' could not be found.\n", 1
    if mode == "license":
        return "[Licensing::Client] Error: No valid Unity Editor license found. Please activate your license.\n", 1
    request_path = Path(arg("-ludovantaRequest"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = answer(request, mode)
    (request_path.parent / f"{request['id']}.result.json").write_text(json.dumps(result), encoding="utf-8")
    return "capture done\n", 0 if result["ok"] else 1


def answer(request: dict, mode: str) -> dict:
    """What Capture.cs writes for a request (also used by the tests that play the open Editor)."""
    result = {"id": request["id"], "ok": True, "error": "", "files": [], "scene": request["scene"] or "Assets/Main.unity",
              "camera": request["camera"] or "Main Camera", "playMode": request["play"] > 0,
              "uniform": mode == "capture_uniform", "width": request["width"], "height": request["height"]}
    if mode == "capture_error":
        return {**result, "ok": False, "error": f"camera '{request['camera']}' not found among the enabled cameras: Main Camera"}
    out = Path(request["output"])
    series = request["frames"] > 1 and request["play"] > 0
    for i in range(request["frames"] if series else 1):
        path = out.with_name(f"{out.stem}-{i + 1:02d}.png") if series else out
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png())
        result["files"].append(str(path))
    return result


def main():
    mode = os.environ.get("FAKE_UNITY_MODE", "ok")
    log, results = arg("-logFile"), arg("-testResults")
    text, code = "Fake Unity batchmode\nargs: " + " ".join(sys.argv[1:]) + "\n", 0
    if arg("-executeMethod") == "Ludovanta.Editor.Capture.Batch":
        more, code = capture(mode)
        text += more
    elif mode == "compile_error":
        text += (FIXTURES / "compile-errors.log").read_text(encoding="utf-8")
        code = 1
    elif mode == "license":
        text += "[Licensing::Client] Error: No valid Unity Editor license found. Please activate your license.\n"
        code = 1
    elif mode == "tests_fail" and results:
        shutil.copy(FIXTURES / "test-results-failed.xml", results)
        code = 2
    elif mode == "tests_flaky" and results:
        flaky_passes = next_run() % 2 == 0
        Path(results).write_text(results_xml([([], [("Game.Tests.MathTests.Adds", True, []),
                                                     ("Game.Tests.MathTests.Subtracts", flaky_passes, [])])]),
                                 encoding="utf-8")
    elif mode == "tests_quarantine" and results:
        Path(results).write_text(results_xml([([], [("Game.Tests.MathTests.Adds", True, []),
                                                    ("Game.Tests.MathTests.Subtracts", False, ["Flaky"])]),
                                              (["Flaky"], [("Game.Tests.TimerTests.Ticks", True, [])])]),
                                 encoding="utf-8")
    elif mode == "ok" and results:
        Path(results).write_text(PASSING_RESULTS, encoding="utf-8")
    if log:
        Path(log).write_text(text, encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
