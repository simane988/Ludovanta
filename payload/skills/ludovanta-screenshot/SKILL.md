---
name: ludovanta-screenshot
description: Capture what the player sees (a camera with the HUD) as PNG files, headless or through the open Unity Editor, and use them as evidence - before/after pairs for visual tasks, frame series for motion, images in the task report. Use for any task that changes something visible, before reporting it, when the critic needs gameplay shots, or when the user asks to see the result.
---

# Screenshots: look at the game, show the result

The user wants to see the result as a picture, not read about it. Agents cannot judge looks from
code either. So every task that changes something the player sees ends with images you have looked
at yourself.

```
python3 .ludovanta/ludovanta.py screenshot [--scene Assets/Scenes/City.unity] [--camera "Main Camera"]
    [--play 3] [--frames 4 --every 0.25] [--size 1280x720] [--label T-012-after] [--out path.png] [--json]
```

On Windows use `python` (or `py -3`) if `python3` is not available.

- **Where it runs.** With the Editor closed (HEADLESS), Unity starts in batchmode, opens `--scene`
  (default: the first enabled scene in Build Settings) and renders. With the Editor open (LIVE), the
  open Editor takes the shot within a second: no Unity MCP needed. In LIVE mode it shoots the scene that
  is open there and never switches scenes (unsaved work); `--scene` must name that scene.
- **What it renders.** The camera named by `--camera`, else `Camera.main`. Screen Space - Overlay
  canvases (the HUD) are drawn onto the shot. The Scene view is never captured: the result is what the
  player sees.
- **`--play SEC`.** Enters Play mode and waits SEC seconds before the shot. Use it whenever the game
  builds its camera, player, HUD or level at runtime, and for anything that moves. In LIVE mode Play
  mode is left again afterwards. Without `--play`, the shot shows the scene as saved.
- **`--frames N --every SEC`.** A series in Play mode for motion and timing (an effect, an animation):
  files `<label>-01.png`, `-02.png` ...
- **Files.** `Logs/ludovanta/screenshots/<label>.png` (not committed). The output lists project paths
  and absolute paths; give the user the absolute ones so the chat can show them.

| Status | Meaning, action |
|---|---|
| `SCREENSHOT` | Done. Open every image and look before you describe it. A `warning: ... flat colour` means the camera saw nothing: try `--play`, another `--camera`, or LIVE mode. |
| `SCREENSHOT_FAILED` | No camera, wrong camera name, scene not open in the Editor: the message says which. |
| `COMPILE_FAILED` | The project does not compile, so nothing can render. Fix the errors first. |
| `PACKAGE_MISSING` / `EDITOR_NOT_ANSWERING` | `Packages/com.ludovanta.editor` is missing or not compiled (run `update`), or the open Editor is busy (compiling, a modal dialog): try again, or use a Unity MCP capture tool. |
| `UNITY_FAILED`, `TIMEOUT` | Environment problem: run `doctor`. |

## Before and after

For a task that changes how something looks or feels:

1. At the start, before changing anything: `screenshot --play 3 --label T-012-before` (same scene and
   camera as the change will be seen from).
2. At the end: the same command with `--label T-012-after`.
3. Look at both. If the difference is not visible at gameplay distance, the task is not done.
4. In the report, under "How to check", give both absolute paths and one line on what to look at.
   Executors name the files in their report to the orchestrator; the orchestrator shows them to the
   user.

## What to look for

Framing, readability, contrast, clipping, whether the effect is visible at gameplay distance, whether
the HUD covers the action, whether it matches the fidelity and art direction in `plan/design.md`. A
moment that needs player input (a jump, a hit, a ride) cannot be reached by waiting: write a PlayMode
test that drives the player and renders the camera (skill `ludovanta-game-design`, `unity-craft.md`,
"Look at the game").
