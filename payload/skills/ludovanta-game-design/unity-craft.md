# Unity craft: feel, art and audio without bought assets

Practical ways to reach the chosen fidelity in a Unity (URP) project with code and local tools.
Pick what the design needs; do not add everything.

## Game feel toolkit

- **Camera response**: a small shake component (Perlin noise offset with decay, amplitude by event
  strength), an FOV kick on dash or charge release, a short look-at on discoveries. If the project
  already has Cinemachine, use its Impulse instead of writing one.
- **Hit stop**: freeze or slow the game for 40-90 ms on strong hits (`Time.timeScale` with a restore
  on unscaled time; never leave it at 0 if the object is destroyed mid-pause).
- **Particles**: `ParticleSystem` bursts for impacts, pickups, casting, footsteps on special
  ground; additive soft-dot textures generated in code (`Texture2D` with a radial falloff). A
  `TrailRenderer` on projectiles and fast moves.
- **Light**: a point light flash on casts and impacts, emissive pulses (`MaterialPropertyBlock`, not
  new materials per object), a colour shift of the world when it changes.
- **Motion**: squash and stretch on jumps and landings, anticipation before attacks, overshoot on UI
  pop-ins. A tiny tween helper (coroutine with an easing function) is enough; add a tween library
  only if the user agrees to a new package.
- **Text and UI**: floating numbers or words at the hit point, HUD elements that punch when they
  change, a clear objective line, a marker for the next goal that sticks to the screen edge.
- **Telegraphs**: enemies and hazards show what they will do before they do it (wind-up pose,
  glowing ground circle, sound cue), so failure feels fair.
- **Sound on every important event**, with small random pitch variation so repeats do not tire.

## Characters and props

- At `prototype` and `stylized` fidelity, compose primitives or simple generated meshes into a
  readable silhouette: proportions, a few signature details (hair, cloak, staff, earrings), team
  colours. Never ship the raw capsule as the hero.
- Animate procedurally when there is no rig: walk bob, lean into turns, idle breathing, hair or
  cloth sway with a damped spring, blinking, a cast pose. It reads as alive far better than a
  sliding static mesh.
- Generate meshes in code (`Mesh` with vertices and vertex colours) for terrain, rocks (displaced
  spheres), trees (cones and cylinders with noise), roofs, bridges. Use a fixed seed so the world is
  the same every run.
- At `high` and `max`: generate models offline when Blender is available (`blender -b -P script.py`
  exporting FBX), or use imported assets with a clear licence. The Unity AI generators (Unity MCP
  tools named `Unity_AssetGeneration_*`) spend the user's Unity AI points: ask before using them.

## Materials, lighting, post-processing (URP)

- A toon look: a hand-written URP `.shader` (main light with a stepped ramp, shadow attenuation, a
  rim term) is easier for an agent to write and review than a Shader Graph asset. Outlines: an
  inverted-hull second pass or material.
- A Global Volume with Bloom, Color Adjustments, Tonemapping and a light Vignette. Keep the bloom
  threshold high enough that white surfaces do not wash out.
- Lighting tells the mood: warm key light and cool ambient (or the reverse), fog for depth, a sky
  gradient, real-time shadows from the main light.
- One palette for everything: environment, characters, effects and UI belong to the same game.

## Environment

- Build landmarks the player can navigate by, paths that lead the eye, and areas with their own
  identity (colour, props, sound). Empty flat planes are the most common "this is not a game" cue.
- Scatter props by script with rules (density by area, not on paths, not overlapping colliders).
- Make the world react to progress: a cleaned statue shines, a field blooms, a road opens, an NPC
  moves somewhere else.

## Audio without files

- Synthesize short effects in code: `AudioClip.Create` and fill samples (noise bursts with an
  envelope for impacts, sine or square sweeps for magic and pickups, filtered noise for wind).
- Or generate WAV files offline with a Python script (stdlib `wave` module) into `Assets/Audio/` so
  they are normal assets.
- Ambient loops per area and a simple generative music layer give the world a mood. Route sounds
  through an `AudioMixer` with music and effects volumes.

## Numbers, debug tools, actors

- Keep tunable values (speeds, damage, mana, cooldowns, timings, camera, effect intensity) in a
  `ScriptableObject` config with clear names, and validate it at boot: a broken value gives a
  readable error, not a silent NaN.
- A developer panel behind a key (for example F1) in the Editor and development builds only
  (`#if UNITY_EDITOR || DEVELOPMENT_BUILD`): teleport to points, give all abilities, jump to a
  quest stage, god mode. Expose the same actions to tests. They prepare a state; they do not prove
  the normal route.
- Enemies, companions and NPCs with behaviour use an explicit state machine (enum plus entry and
  exit per state, a timeout and a fallback), not a pile of conditions.
- Gameplay must not depend on the frame rate: use `Time.deltaTime` or `FixedUpdate` for movement,
  timers and cooldowns.

## Look at the game

You cannot judge feel and looks from code. Capture what the player sees, from the gameplay camera
with the HUD, and look at the images:

- `python3 .ludovanta/ludovanta.py screenshot --play 3` works in both modes (skill
  `ludovanta-screenshot`): headless in batchmode, or through the open Editor. A Scene view capture
  shows the level, not the player's view.
- A moment that needs the player to act (a jump, a hit, a ride): a PlayMode test that loads the
  scene, drives the player with simulated input, renders the main camera into a `RenderTexture` and
  writes PNGs to `Logs/ludovanta/screenshots/` (generated, not committed).

Look after every visible change and at least once per milestone: framing, readability, contrast,
clipping, whether the effect is visible at gameplay distance, whether the HUD covers the action.
A static shot cannot show animation timing: capture a short sequence of frames when motion matters.
