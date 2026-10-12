"""Stand-in for the Unity executable in tests. Behaviour is chosen by the FAKE_UNITY_MODE env var."""
import os
import shutil
import sys
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


def main():
    mode = os.environ.get("FAKE_UNITY_MODE", "ok")
    log, results = arg("-logFile"), arg("-testResults")
    text, code = "Fake Unity batchmode\nargs: " + " ".join(sys.argv[1:]) + "\n", 0
    if mode == "compile_error":
        text += (FIXTURES / "compile-errors.log").read_text(encoding="utf-8")
        code = 1
    elif mode == "license":
        text += "[Licensing::Client] Error: No valid Unity Editor license found. Please activate your license.\n"
        code = 1
    elif mode == "tests_fail" and results:
        shutil.copy(FIXTURES / "test-results-failed.xml", results)
        code = 2
    elif mode == "ok" and results:
        Path(results).write_text(PASSING_RESULTS, encoding="utf-8")
    if log:
        Path(log).write_text(text, encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
