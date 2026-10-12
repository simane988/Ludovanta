---
name: ludovanta-unity-test
description: Run and write Unity Test Framework tests (EditMode and PlayMode) in a Unity project. Use to verify game code behaviour, before reporting a task as done, when a task asks for tests, or when tests fail.
---

# Unity tests

## Running tests (headless mode)

```
python3 .ludovanta/ludovanta.py test [--platform EditMode|PlayMode] [--filter <name or regex>] [--category <name>]
```

On Windows use `python` (or `py -3`) if `python3` is not available. Add `--json` for JSON output.

- `EditMode` (default) is fast: use it for plain C# logic.
- `PlayMode` runs the player loop and is slower: use it for MonoBehaviour lifecycle, physics,
  coroutines, scenes.
- While iterating, run only the relevant tests with `--filter` (full test name such as
  `Game.Tests.InventoryTests` or a regex). Run the whole EditMode suite before finishing.

| Exit | Status | Action |
|---|---|---|
| 0 | `TESTS_PASSED` | Done. |
| 0 | `NO_TESTS` | No tests found or the filter matched nothing: check the filter and the test `.asmdef`. |
| 1 | `TESTS_FAILED` | Each failure prints the test name, the assertion message and `at Assets/...cs:line`. Decide whether the code or the test is wrong. Do not weaken a test just to make it pass. |
| 1 | `COMPILE_FAILED` | Tests did not run. Fix the compiler errors first. |
| 2 | `UNITY_FAILED` / `LUDOVANTA_ERROR` | Environment problem: report it, do not change code because of it. |
| 3 | `EDITOR_OPEN` | Live mode: use a Unity MCP test tool if one exists, otherwise ask the user to run the tests in Window > General > Test Runner or to close the Editor. |
| 4 | `TIMEOUT` | Report to the user. |

## Writing tests

Follow the layout of existing tests if the project has any. Otherwise:

- Tests live in their own assembly (`.asmdef`), and **the code under test must be in an
  `.asmdef` too**: a test assembly cannot reference the default `Assembly-CSharp`. If the game
  code has no `.asmdef`, ask the user before adding one, because it changes how the whole
  project compiles.
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
- Make tests deterministic: seed random generators, avoid real-time waits and test order dependence.
- Best evidence for a bug fix: a test that failed before the fix and passes after it.
