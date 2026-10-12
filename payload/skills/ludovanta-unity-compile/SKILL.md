---
name: ludovanta-unity-compile
description: Check that the Unity project compiles after changing C# scripts, .asmdef/.asmref files or packages, and fix compiler errors. Use after every batch of code changes in a Unity project and before reporting a task as done. Covers headless mode (batchmode script) and live mode (Unity Editor open, Unity MCP).
---

# Compile the Unity project

## Headless mode

```
python3 .ludovanta/ludovanta.py compile
```

On Windows use `python` (or `py -3`) if `python3` is not available.
Options: `--warnings` (also list warnings), `--json`, `--timeout <seconds>`, `--max-items <n>`.

The first run in a fresh checkout or worktree imports all assets and may take many minutes.
Do not abort it and do not run two Unity commands in parallel for the same folder.

| Exit | Status | Action |
|---|---|---|
| 0 | `COMPILE_OK` | Continue. |
| 1 | `COMPILE_FAILED` | Fix errors listed as `path:line:col CODE message`, then re-run. Start with the first error: later ones are often consequences of it. |
| 2 | `UNITY_FAILED` / `LUDOVANTA_ERROR` | Environment problem (Unity not installed, license, crash). Do not change game code because of it. Report the `reason:` lines and the log path to the user. |
| 3 | `EDITOR_OPEN` | The project is open in Unity. Switch to live mode. Never kill Unity. |
| 4 | `TIMEOUT` | Report to the user. |

Compiler errors from `Library/PackageCache/...` come from a package, not from project code:
usually a package version mismatch. Tell the user instead of editing package code.

## Live mode (Unity Editor is open)

1. After editing scripts, Unity recompiles once it refreshes assets. If the Unity MCP server
   offers a tool to refresh assets or request a script compilation, call it.
2. Read the Editor console through Unity MCP (for example `Unity_ReadConsole`) and look for
   compiler errors (`error CS....`).
3. Fix and repeat until the console has no compiler errors.

If no Unity MCP tools are available in your session, ask the user to check the Editor console,
or to close the Editor so the headless command can be used.

## Common causes

- `CS0246` type or namespace not found: missing `using`, or the type is in an assembly that the
  current `.asmdef` does not reference.
- Errors only in one assembly after adding an `.asmdef`: code that used to compile into
  `Assembly-CSharp` now needs explicit references.
- Editor-only API (`UnityEditor`) in runtime code: move the code to an `Editor` folder or
  editor-only assembly, or wrap it in `#if UNITY_EDITOR`.
