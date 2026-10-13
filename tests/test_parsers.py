import pytest

from helpers import FIXTURES, write
from ludovanta_lib import parsers

ROOT = r"C:\Proj\Game"


@pytest.fixture(scope="module")
def messages():
    return parsers.compiler_messages(FIXTURES / "compile-errors.log", ROOT)


@pytest.fixture(scope="module")
def results():
    return parsers.test_results(FIXTURES / "test-results-failed.xml", ROOT)


def test_compiler_errors_are_deduplicated(messages):
    assert [m["severity"] for m in messages] == ["error", "error", "warning"]


@pytest.mark.parametrize("index, expected", [
    (0, "Assets/Scripts/Player.cs:12:17 CS0103 The name 'speed' does not exist in the current context"),
    (1, "Assets/Scripts/Enemy.cs:3:1 CS1002 ; expected"),   # absolute Windows path -> project-relative
    (2, "Assets/Scripts/Util.cs:5:9 CS0168 The variable 'e' is declared but never used"),
])
def test_compiler_message_format(messages, index, expected):
    assert parsers.format_compiler_message(messages[index]) == expected


def test_compiler_messages_missing_log(tmp_path):
    assert parsers.compiler_messages(tmp_path / "nope.log", ROOT) == []


def test_test_counts(results):
    assert (results["total"], results["passed"], results["failed"], results["skipped"]) == (3, 1, 1, 1)


def test_test_failure_details(results):
    [failure] = results["failures"]
    assert failure["name"] == "Game.Tests.MathTests.Subtracts"
    assert "Expected: 1" in failure["message"]
    assert failure["locations"] == ["Assets/Tests/EditMode/MathTests.cs:15"]


@pytest.mark.parametrize("stack, root, expected", [
    (r"at A.B () [0x00001] in C:\Proj\Game\Assets\X.cs:12", r"C:\Proj\Game", ["Assets/X.cs:12"]),
    ("at A.B () in /home/me/Game/Assets/X.cs:line 7", "/home/me/Game", ["Assets/X.cs:7"]),
    ("at A.B () in /home/me/Game/Packages/com.me.lib/Y.cs:3", "/home/me/Game", ["Packages/com.me.lib/Y.cs:3"]),
    ("at NUnit.Framework.Assert () in /usr/lib/mono/Assert.cs:3", "/home/me/Game", []),
    ("", "/home/me/Game", []),
])
def test_stack_locations(stack, root, expected):
    assert parsers.stack_locations(stack, root) == expected


@pytest.mark.parametrize("log_text, expected", [
    ("No valid Unity Editor license found. Please activate your license.", "Unity license problem"),
    ("[Licensing::Client] License is not active", "Unity license problem"),
    ("It looks like another Unity instance is running with this project open.", "Another Unity instance"),
    ("Refreshing native plugins compatible for Editor in 0.42 ms", None),
], ids=["license-no-valid", "license-not-active", "another-instance", "nothing"])
def test_known_problems(tmp_path, log_text, expected):
    log = tmp_path / "unity.log"
    write(log, log_text + "\n")
    problems = parsers.known_problems(log)
    if expected is None:
        assert problems == []
    else:
        assert len(problems) == 1 and expected in problems[0]


def test_known_problems_missing_log(tmp_path):
    assert "no log file" in parsers.known_problems(tmp_path / "nope.log")[0]


def test_test_cases_with_inherited_categories(tmp_path):
    xml = tmp_path / "r.xml"
    xml.write_text('<?xml version="1.0"?><test-run total="2" passed="1" failed="1" duration="1.5">'
                   '<test-suite name="Asm"><properties><property name="Category" value="Slow" /></properties>'
                   '<test-suite name="Fixture"><properties><property name="Category" value="Flaky" /></properties>'
                   '<test-case fullname="A.B" result="Failed" duration="0.25"><failure><message>no</message></failure>'
                   '</test-case></test-suite>'
                   '<test-case fullname="A.C" result="Passed" duration="x" /></test-suite></test-run>', encoding="utf-8")
    r = parsers.test_results(xml, ROOT)
    assert r["cases"] == [{"name": "A.B", "result": "Failed", "categories": ["Flaky", "Slow"], "duration": 0.25},
                          {"name": "A.C", "result": "Passed", "categories": ["Slow"], "duration": 0.0}]
    assert r["failures"][0]["categories"] == ["Flaky", "Slow"]
