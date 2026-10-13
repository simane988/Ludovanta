---
name: ludovanta-unity-test
description: Run, write and maintain Unity Test Framework tests (EditMode and PlayMode) as the agent's own self-check. Use to verify game code behaviour before reporting a task as done, when tests fail or are flaky (TESTS_FLAKY, quarantine), before changing what an existing test expects, and to audit a test suite that keeps breaking (test-audit).
---

# Unity tests: the agents' self-check

Tests are how agents check their own work so that the user gets a result that works. The user does
not write, run, review or decide anything about tests: never ask them about tests, never make tests
acceptance criteria or plan tasks, and keep test details out of reports to the user (at most one line
in "Not done or uncertain" when something could not be verified). Keeping the suite fast and
trustworthy is the agents' job.

## Running tests (headless mode)

```
python3 .ludovanta/ludovanta.py test [--platform EditMode|PlayMode] [--filter <name or regex>] [--category <name>]
python3 .ludovanta/ludovanta.py test --filter <name> --repeat 5      # is this test flaky?
python3 .ludovanta/ludovanta.py test-audit                           # what is wrong with the suite
```

On Windows use `python` (or `py -3`) if `python3` is not available. Add `--json` for JSON output.

- `EditMode` (default) is fast: use it for plain C# logic.
- `PlayMode` runs the player loop and is slower: use it for MonoBehaviour lifecycle, physics,
  coroutines, scenes.
- While iterating, run only the relevant tests with `--filter` (full test name such as
  `Game.Tests.InventoryTests` or a regex). Run the whole EditMode suite before finishing.
- Failed tests are rerun once automatically (up to 5 of them, `--no-rerun` to skip): this tells a
  flaky test from one your change broke.

| Exit | Status | Action |
|---|---|---|
| 0 | `TESTS_PASSED` | Done. A `quarantine:` line lists flaky tests that still need fixing (see "Flaky tests"). |
| 0 | `TESTS_FLAKY` | No real failures, but the listed tests failed and then passed with no code change. Your change did not break them: quarantine them and go on. |
| 0 | `NO_TESTS` | No tests found or the filter matched nothing: check the filter and the test `.asmdef`. |
| 1 | `TESTS_FAILED` | Each failure prints the test name, the assertion message and `at Assets/...cs:line`; they failed again on the rerun. Decide whether the code or the test is wrong (see "Good tests"). Do not weaken a test just to make it pass. |
| 1 | `COMPILE_FAILED` | Tests did not run. Fix the compiler errors first. |
| 2 | `UNITY_FAILED` / `LUDOVANTA_ERROR` | Environment problem: report it, do not change code because of it. |
| 3 | `EDITOR_OPEN` | Live mode: use a Unity MCP test tool if one exists. Otherwise an executor leaves the tests to the orchestrator; the session talking to the user verifies through the Unity MCP console and Play mode and notes "tests not run". Do not ask the user to run tests. |
| 4 | `TIMEOUT` | Note it as not verified; a hanging test is a finding for the audit. |

**The gate.** A full run (no `--filter`, no `--category`) is recorded per platform. `plan set
--status review` refuses with `TESTS_NOT_GREEN` until each platform that has a test assembly had a
full run that started after the latest code change (`.cs`, `.asmdef`, `.asmref`,
`Packages/manifest.json`) and ended without real failures. So finish a task with `test` (and
`test --platform PlayMode` if the project has PlayMode tests), not only filtered runs. Only when
Ludovanta cannot run Unity here, pass `--unverified "<why, what you checked instead>"`; it is logged.

With `--repeat N` the same tests run N times (N Unity starts: always use `--filter`):
`TESTS_STABLE` (exit 0), `TESTS_FLAKY` (exit 1, mixed results), `TESTS_FAILED` (exit 1, a test failed
every time).

## Good tests

Tests are there to catch real regressions in rules that can break silently: quest and progression
logic, economy, damage, saves, the route through the game. A test that breaks on every harmless
change is worse than no test, because it teaches agents to "fix" tests by changing what they expect.

- **EditMode for logic.** Rules and calculations live in plain C# classes and are covered by fast
  EditMode tests. This is the bulk of the suite.
- **PlayMode only for key scenarios.** One PlayMode test per key scenario of the current milestone or
  vertical slice (for example: a passenger gets in, the ride ends, the fare is paid), not one per
  component. If an EditMode test can check it, it is not a PlayMode test.
- **Behaviour, not implementation.** Assert what the player or the calling code can observe: return
  values, public state, raised events, the scene state after a scenario. Do not assert private fields
  (no reflection), the order of internal calls, exact log text or the object hierarchy. A refactor
  that keeps the behaviour must not break a test.
- **Deterministic.** Seed random generators, inject time instead of waiting in real time, compare
  floats with a tolerance, pass references in instead of finding objects by name, no dependence on
  test order or frame rate.
- **A failing test: is the code wrong or the test?** The test is wrong only when the required
  behaviour changed (the task card or the user changed the game) or when it checked implementation
  details. Otherwise fix the code.
- **Never change an expectation silently.** If you change what an existing test expects, loosen a
  tolerance, mark it `[Ignore]`, quarantine it or delete it, add a line to the task card's `## Log`
  (no card: the commit message): the test, before -> after, why. An executor also lists it under
  "Tests changed" in its report to the orchestrator. Never do it only to get a green run.
- **A bug fix comes with a test** that fails before the fix and passes after it.

## Flaky tests

A flaky test fails sometimes with no code change. It must not send you in circles, and it must not
disappear either.

1. `TESTS_FLAKY` (or a test you suspect, confirmed with `test --filter <name> --repeat 5`):
   quarantine it with the NUnit category `Flaky`, on the test method (or the fixture if all of it is
   flaky), and log it in the card:

   ```csharp
   [Test, Category("Flaky")]   // quarantined 2026-10-13: fails ~1 in 3, suspect frame timing
   ```

2. Quarantined tests still run and are listed in every `test` result, but their failures do not fail
   the run. Carry on with your task.
3. Fix it when you are in that code anyway, or as test upkeep (see "Audit"): find the source of
   nondeterminism (real time, unseeded random, test order, frame rate, physics timing, async loading,
   shared static state), fix it, then `test --filter <name> --repeat 5`. When it is `TESTS_STABLE`,
   remove the category.
4. Never quarantine a test that fails every time: that is a real failure.

## Audit

`test-audit` reads the test code, the results of earlier runs and git history, without Unity. It
lists heuristics to check, not proven bugs: reflection into private members, real-time waits,
unseeded randomness, exact float comparisons, scene lookups by name, ignored and quarantined tests,
slow tests, tests that failed in many recent runs, test files rewritten again and again (expectations
following the code), and game scripts outside any `.asmdef` that tests cannot reach.

Run it when tests keep failing for reasons that are not your change, when a test file needs its third
rewrite, before your first change to an unfamiliar suite, and (orchestrator) at the end of a
milestone. Then fix what it finds, starting with what blocks work: flaky and often failing tests, then
brittle ones, then slow ones. Rewrite a brittle test to check behaviour, delete a test that checks
nothing, move logic checks from PlayMode to EditMode. This is upkeep: no task card, no questions to
the user, and no mention in reports to the user. An orchestrator gives larger cleanups to an executor
(Codex suits it: self-contained code with clear criteria).

## Writing tests

Follow the layout of existing tests if the project has any. Otherwise:

- Tests live in their own assembly (`.asmdef`), and **the code under test must be in an
  `.asmdef` too**: a test assembly cannot reference the default `Assembly-CSharp`. If the game
  code has no `.asmdef`, put the logic you need to test into its own assembly (for example
  `Assets/Scripts/Core/Game.Core.asmdef` for plain C# rules) rather than moving the whole project at
  once, and make sure the project still compiles. Mention it once in the report as a change of project
  structure, not as a question.
- EditMode tests: `Assets/Tests/EditMode/<Name>.Tests.EditMode.asmdef`:

  ```json
  {
    "name": "Game.Tests.EditMode",
    "rootNamespace": "Game.Tests",
    "references": ["Game.Runtime", "UnityEngine.TestRunner", "UnityEditor.TestRunner"],
    "includePlatforms": ["Editor"],
    "overrideReferences": true,
    "precompiledReferences": ["nunit.framework.dll"],
    "autoReferenced": false,
    "defineConstraints": ["UNITY_INCLUDE_TESTS"]
  }
  ```

- PlayMode tests: `Assets/Tests/PlayMode/`, same as above but `"includePlatforms": []` and
  without `UnityEditor.TestRunner` in `references`.
- `[Test]` for synchronous tests, `[UnityTest]` returning `IEnumerator` when frames must pass.
- Keep logic in plain C# classes that EditMode tests can cover. Keep MonoBehaviours thin.
