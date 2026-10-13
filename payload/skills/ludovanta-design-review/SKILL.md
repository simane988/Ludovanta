---
name: ludovanta-design-review
description: Independent critic for game quality - is it fun, readable and as polished as the chosen fidelity. Use at fixed checkpoints - before showing a new plan to the user, when the first playable milestone is done, at the end of a milestone with new gameplay - and whenever the user says the game is boring, raw or empty, or asks how to make it better.
---

# Design review: a second pair of eyes on fun and quality

The agent who built something is the worst judge of whether it is fun: it knows what was meant.
A critic looks at the evidence with fresh context, against `plan/design.md` and the quality bar in
`ludovanta-game-design`, and returns a short list of gaps. You (the lead) verify the findings and
fix the important ones once. Reviews are bounded: they are not a loop and not a new approval step
for the user.

## Checkpoints

| Checkpoint | When | The critic answers |
|---|---|---|
| `plan` | design and plan are drafted, before the user sees them | Does the plan deliver the fantasy? Is the main verb with feedback in the first milestone? Is there challenge, escalation, an ending? Do the criteria cover feel, not only function? Is anything cut that the fidelity requires? Where is dead time? |
| `first-playable` | the first milestone is done, before reporting it | Is the main verb readable and satisfying within 30 seconds? Is it obvious what to do? Does every important event have feedback? Does it look like the chosen fidelity or like greybox? |
| `milestone` | a later milestone adds gameplay | Same as first-playable for the new content, plus: does progress change the world, does the session still escalate? |
| `boring` | the user says it is boring, raw, empty, or asks how to improve | The three to five changes that would most improve the experience, ranked, with the cause (design, feel or looks) |

Skip the review for small fixes and for tasks that change no gameplay or visuals.

## Running the critic

- **With subagents** (Claude Code: the Agent tool; other agents: their equivalent): start one
  read-only critic with fresh context. Give it the checkpoint, the question from the table, and the
  evidence below. Use the strongest available model for it.
- **Without subagents**: do it yourself as a separate step - re-read the evidence as if you had not
  built it - and call it a self-review in the report.

Evidence (small and real, no capture tours):

- `plan/design.md`, `plan/goal.md`, the milestone and its task cards;
- up to five screenshots from the gameplay camera with the HUD, from normal play (see "Look at the
  game" in `ludovanta-game-design/unity-craft.md`); a short frame sequence if motion matters;
- for `plan`: the plan only; for the others also the list of feedback actually implemented for the
  events in the design's game feel table (where in the code), and what the tests cover.

Prompt for the critic (adapt the checkpoint and the paths):

```
You are a senior game designer reviewing a Unity game for checkpoint <checkpoint>.
Read plan/design.md (the intended fantasy, main verb, session walk-through, game feel table,
fidelity) and <other evidence>. Answer: <the question from the table>.
Judge as a player and a game designer, not as a code reviewer. Do not propose new systems or a
bigger scope; work within the design and the fidelity the user chose.
Return at most 5 findings, most important first. Each: severity (BLOCKER: the slice is not a
game / the main verb or the ending does not work; MAJOR: clearly hurts fun, readability or the
chosen fidelity; MINOR: polish), what you saw (cite the file, screenshot or design section),
why it matters to the player, the smallest change that fixes it. "READY" with no findings is a
valid answer.
```

## After the review

1. Verify each finding against the design, the code and the screenshots. Reject findings that are
   stale, unsupported, or that change what the user decided (scope, fidelity, fixed design).
2. Fix the verified BLOCKER and MAJOR findings once. For the `plan` checkpoint this means changing
   `design.md` and the cards before the user sees them. A second correction round only if a fix
   broke something.
3. MINOR findings go to the report or become `todo` tasks.
4. In the task or plan report, one line: who reviewed (critic or self-review), how many findings by
   severity, what was fixed, what was left and why.
