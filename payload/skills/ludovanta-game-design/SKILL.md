---
name: ludovanta-game-design
description: Design the game before planning or building it - fantasy, main verb, core loop, session walk-through, game feel, art direction and the graphics fidelity level - and keep it in plan/design.md. Use when the user describes a new game or a big new feature, before breaking work down with ludovanta-plan, when plan/design.md is missing, and when the user says the game feels raw, boring, empty or "not like a game".
---

# Game design: make it a game, not a set of working mechanics

Compiling code and passing tests do not make a game. The result the user wants is something that
is fun to play in the first minute and looks intentional. This skill owns that. It runs before
`ludovanta-plan`, and its result, `plan/design.md`, is what the plan, the task criteria and the
reviews (`ludovanta-design-review`) are checked against.

You are the game designer, the gameplay programmer and the technical artist. Invent routine
details yourself (names, layout, controls, camera, numbers, palette, UI, timings); the user should
not have to do design work you can do.

## 1. Intake: ask once, only what is missing

Read the user's message and any references first (images, links, other projects, older versions:
open them, a filename is not inspection). Then ask, in ONE message, only the questions the user
has not answered explicitly. Keep the numbering and the options:

1. **The idea** in a sentence or more, plus references if there are any.
2. **Graphics fidelity.** Do not guess it from words like "good" or "nice":
   - `prototype`: simple shapes composed into recognizable objects, a coherent palette, lighting
     and effects. Never a grey capsule in a grey box.
   - `stylized` (recommended default): an intentional style - shaded materials (toon, flat or
     painterly), outlines or not, post-processing, procedural or simple modelled meshes, particles,
     procedural animation, sound.
   - `high`: as stylized, plus generated or imported models, textures, animations and audio where
     they visibly beat procedural ones.
   - `max`: the highest quality the target hardware sustains, using every available local tool.
   - `reference`: match the user's references (name them).
3. **Design rounds.** `one-shot` (design it yourself and build) or `discuss` (one or two short
   rounds about the idea before building).

Questions about the core fantasy, the main mechanic or the scope that genuinely change the game
may be added (at most three, each with 2-4 options, your recommendation first). Do not ask about
routine details. If everything is answered, do not ask anything: continue.

Scope is not a question with a "small prototype with stubs" default. The first goal is a **vertical
slice: small in breadth, finished in feel**. One area, a few mechanics, a beginning and an end,
and everything in it reacts, sounds and looks like the chosen fidelity.

## 2. Design pass

Think the game through before any task exists. Fill `plan/design.md` (`plan init` creates the
template; the `fidelity` header line is read by `plan check`). Write it in the user's language,
short: a page or two, decisions rather than essays.

- **Fantasy**: what the player feels and is, in two or three sentences. What makes it this game
  and not a generic one (the source material, the twist, the mood).
- **Main verb and core loop**: what the player does most of the time, why it is satisfying on its
  own, and the loop around it (do -> get -> unlock -> do something new). The main verb must be
  available in the first 30 seconds.
- **Session walk-through**: what happens at 30 seconds, 2 minutes, 5 minutes, 10 minutes and at the
  ending. Look for dead time (walking with nothing to do, waiting, reading), repetition without
  escalation, and moments where the player does not know what to do. Fix them in the design.
- **Challenge and failure**: what can go wrong for the player, how it is telegraphed, what it costs,
  how the player recovers. A game without any resistance is a tour. Combat is not mandatory, but
  something must push back (enemies, puzzles, timing, resources, hazards, choices).
- **Progression the player sees**: new abilities, areas, characters, changes in the world. Avoid
  progress that is only a number going up.
- **Game feel**: a table of the important events (main verb, hit, pickup, unlock, failure, success,
  ending) and the feedback each one gets: animation, particles, light, sound, camera response,
  hit stop, UI, world reaction. No important event is a silent state change.
- **Art direction**: palette, shape language, proportions, materials and lighting, characters,
  environment density, UI identity, and how this is achieved in Unity at the chosen fidelity.
  Pick one shipped game as a quality anchor for presentation if the user gave no references.
- **Audio**: what makes sound (main verb, feedback, ambience, music) and where it comes from
  (generated in code, generated offline, imported).
- **What to cut first**: when time runs short, reduce breadth (fewer areas, enemies, spells), never
  the feel or the fidelity of what remains.
- **Acceptance scenarios**: three to six things the user will do in Play mode to judge the slice,
  written as player actions and what they should see and feel.

How to build feel, art and audio in Unity without bought assets: [unity-craft.md](unity-craft.md).
Read it before writing the art direction and the game feel table.

If the design is `discuss`: after one or two rounds ask exactly «Нужна ещё итерация дизайна или
фиксируем дизайн?» (in the user's language) and continue to planning only after the user fixes it.
If `one-shot`: do not ask for approval of the design, show it together with the plan.

## 3. Hand over to planning

Then follow `ludovanta-plan`: milestones and tasks are derived from `design.md`, and the plan is
reviewed by a critic (`ludovanta-design-review`, checkpoint "plan") before the user sees it.

## When the user says it is boring or raw

Do not defend the build and do not start polishing at random. Run `ludovanta-design-review` with
the checkpoint "boring": it compares the build against `design.md` and the quality bar below and
names the few changes that matter most. Fix the design first if the design is the problem (no
challenge, no escalation, dead time), then the feel, then the looks. Update `design.md` and add
tasks to the plan for what you change.

## Quality bar (checked by every review)

- The first 30 seconds show the fantasy: the main verb is in the player's hands, with feedback.
- Nothing the user is asked to look at is greybox below the chosen fidelity: placeholder shapes are
  composed into recognizable objects, materials and lighting follow the art direction.
- Every important event has visible and audible feedback. Clarity over effect spam.
- The player always knows what to do next (objective, marker, level composition, a line from an
  NPC), without walls of tutorial text.
- Something pushes back, and there is an ending or a repeatable session end.
- Progress changes what the player sees and can do.
- Tunable numbers live in one place (ScriptableObject config), not scattered literals.
