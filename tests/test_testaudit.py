"""ludovanta.py test-audit: brittle, slow and flaky tests found without Unity."""
import json

import pytest

from helpers import PLATFORM_DIR, git, run_py, write

CLI = PLATFORM_DIR / "ludovanta.py"

EDIT_ASMDEF = '{"name": "Game.Tests.EditMode", "includePlatforms": ["Editor"]}'
PLAY_ASMDEF = '{"name": "Game.Tests.PlayMode", "includePlatforms": []}'

FARE_TESTS = """using NUnit.Framework;
using System.Reflection;

public class FareTests
{
    [Test]
    public void Grows()
    {
        var rate = typeof(Fare).GetField("_rate", BindingFlags.NonPublic | BindingFlags.Instance);
        Assert.AreEqual(2.5f, new Fare().Price(1));
        Assert.AreEqual(2.5f, new Fare().Price(1), 0.001f);
        Assert.That(new Fare().Price(2), Is.EqualTo(5.0f).Within(0.01f));
        // Assert.AreEqual(1.5f, x);   commented out: not a finding
    }

    [TestCase(1)]
    [TestCase(2)]
    public void Cases(int n) { Assert.AreEqual(n, n); }

    [Test, Ignore("broken")]
    public void Old() { }
}
"""

RIDE_TESTS = """using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

[Category("Flaky")]
public class RideTests
{
    [UnityTest]
    public IEnumerator PassengerGetsIn()
    {
        var taxi = GameObject.Find("Taxi");
        var x = Random.Range(0, 10);
        yield return new WaitForSeconds(3f);
    }
}
"""

SEEDED_TESTS = """using NUnit.Framework;
public class SeededTests
{
    [Test]
    public void Dice() { UnityEngine.Random.InitState(42); var x = UnityEngine.Random.Range(0, 6); }
}
"""

RESULTS = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" result="{result}" total="2" passed="1" failed="1" inconclusive="0" skipped="0" duration="4.0">
  <test-case name="Grows" fullname="FareTests.Grows" result="{grows}" duration="0.01" />
  <test-case name="Slow" fullname="FareTests.Slow" result="Passed" duration="2.5" />
</test-run>
"""


def audit(project, *args):
    code, out = run_py(CLI, "--project", str(project), "test-audit", *args)
    return code, out


@pytest.fixture
def game(make_project):
    p = make_project()
    write(p / "Assets/Tests/EditMode/Game.Tests.EditMode.asmdef", EDIT_ASMDEF)
    write(p / "Assets/Tests/EditMode/FareTests.cs", FARE_TESTS)
    write(p / "Assets/Tests/EditMode/SeededTests.cs", SEEDED_TESTS)
    write(p / "Assets/Tests/PlayMode/Game.Tests.PlayMode.asmdef", PLAY_ASMDEF)
    write(p / "Assets/Tests/PlayMode/RideTests.cs", RIDE_TESTS)
    write(p / "Assets/Scripts/Fare.cs", "public class Fare { }")
    write(p / "Assets/Scripts/Taxi.cs", "public class Taxi { }")
    write(p / "Assets/Editor/Tool.cs", "class Tool { }")
    return p


def test_no_tests(make_project):
    code, out = audit(make_project(with_git=False))
    assert code == 0, out
    assert out.startswith("TEST_AUDIT: no tests in Assets/")


def test_finds_smells(game):
    code, out = audit(game)
    assert code == 0, out
    assert out.startswith("TEST_AUDIT: about 6 test(s) in 3 file(s): 5 EditMode, 1 PlayMode; 1 quarantined, 1 ignored")
    for expected in [
        "reaches private members through reflection: tests implementation, breaks on refactor: 1",
        "Assets/Tests/EditMode/FareTests.cs:9",
        "compares floats exactly: flaky (use a tolerance, .Within(...)): 1",
        "Assets/Tests/EditMode/FareTests.cs:10",
        "is ignored ([Ignore]): checks nothing, fix or delete it: 1",
        "waits in real time: slow and flaky (inject time or wait frames instead): 1",
        "finds objects by name or type: breaks when the scene changes (pass references in): 1",
        "uses randomness without a fixed seed: flaky: 1",
        "Assets/Tests/PlayMode/RideTests.cs:13",
        "2 script(s) outside any .asmdef (Assembly-CSharp): tests cannot reference them",
        "Assets/Scripts (2)",
        "next: fix these yourself, no questions to the user",
    ]:
        assert expected in out
    assert "SeededTests" not in out, "a seeded random is fine"
    assert "Editor (1)" not in out, "editor scripts are not game code"


def test_history_and_churn(game):
    logs = game / "Logs/ludovanta"
    for i in range(4):
        write(logs / f"test-editmode-2026101{i}-100000-000.xml",
              RESULTS.format(result="Failed" if i else "Passed", grows="Failed" if i else "Passed"))
    write(logs / "test-editmode-20261019-100000-000.xml", "not xml")
    for i in range(3):
        write(game / "Assets/Tests/EditMode/FareTests.cs", FARE_TESTS + f"// change {i}\n")
        git(game, "add", "-A")
        git(game, "commit", "--quiet", "-m", f"tests {i}")
    code, out = audit(game, "--json")
    assert code == 0, out
    data = json.loads(out)
    assert data["slow"] == [{"name": "FareTests.Slow", "platform": "EditMode", "seconds": 2.5}]
    assert data["oftenFailing"] == [{"name": "FareTests.Grows", "failed": 3, "runs": 4}]
    assert data["churn"] == [{"file": "Assets/Tests/EditMode/FareTests.cs", "commits": 3}]
    code, out = audit(game)
    assert "slow tests in the last runs (EditMode 4.0s):" in out and "FareTests.Slow (EditMode) 2.5s" in out
    assert "FareTests.Grows: failed 3 of 4" in out
    assert "Assets/Tests/EditMode/FareTests.cs: 3 commits" in out
