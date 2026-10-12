---
name: ludovanta-unity-assets
description: Rules for creating, moving, renaming and deleting Unity assets (.meta files, GUIDs, scenes, prefabs, ScriptableObjects) and validating them. Use whenever you add, move, rename or delete files under Assets/, touch .unity/.prefab/.asset/.mat files, or before committing changes to a Unity project.
---

# Unity assets and .meta files

Every file and folder under `Assets/` has a sibling `.meta` file holding its GUID. Scenes,
prefabs and materials reference other assets by GUID, so a lost or changed GUID silently
breaks references (missing scripts, pink materials, empty fields).

## Creating

- Never write `.meta` files by hand and never invent GUIDs. Unity creates the `.meta` on import:
  in live mode after the Editor refreshes, in headless mode on the next `python3 .ludovanta/ludovanta.py compile` run.
- Commit the asset together with its `.meta`.
- A MonoBehaviour or ScriptableObject class name must match its file name.

## Moving and renaming

- Move the `.meta` together with the asset so the GUID survives:
  `git mv Old.cs New.cs` and `git mv Old.cs.meta New.cs.meta` (same for folders: `Folder` and `Folder.meta`).
- When renaming a MonoBehaviour script, rename the class too.
- In live mode prefer moving assets through Unity MCP tools so the Editor stays consistent.

## Deleting

- Delete the asset and its `.meta`. Before deleting, search for its GUID (from the `.meta`) in
  `Assets/` to find scenes or prefabs that still reference it, and tell the user about them.

## Duplicating

- Never copy a `.meta` file to duplicate an asset: two assets with one GUID break references.
  Copy only the asset and let Unity generate a new `.meta`.

## Scenes, prefabs and other YAML assets

- Do not edit `.unity`, `.prefab`, `.asset`, `.mat` files by hand while the Editor has the
  project open: the Editor overwrites the change or asks the user to reload.
- Live mode: change scenes and GameObjects through Unity MCP tools, then save the scene.
- Headless mode: only make small, well-understood YAML edits (for example a serialized number or
  string). For structural changes (new GameObjects, components, references), prefer creating
  content from code (editor scripts, ScriptableObjects) or ask the user to do the scene wiring.

## Ignored by Unity

Names starting with `.`, ending with `~` (for example `Samples~`), named `cvs` or with the
extension `.tmp` are not imported and have no `.meta`.

## Validate before committing

```
python3 .ludovanta/ludovanta.py validate-assets [--roots Assets Packages/com.company.package]
```

On Windows use `python` (or `py -3`) if `python3` is not available.

Reports missing `.meta`, orphan `.meta` (the asset is gone), `.meta` without GUID and duplicate
GUIDs. Exit 0: `ASSETS_OK`, exit 1: `ASSETS_INVALID`.
A missing `.meta` right after creating files in headless mode is expected: run
`python3 .ludovanta/ludovanta.py compile` and validate again.
