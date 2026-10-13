---
name: ludovanta-feedback
description: Record what gets in the user's way in the project's friction log (docs/feedback-log.md) and show the log for the weekly review. Use when the user says "запиши, что неудобно", "запиши в журнал", "это бесит", "опять мешает", "note this", "this is annoying" about the tools, the platform or how the agents work, or asks what got in the way this week.
---

# Friction log

The friction log is how the user tells the platform's author what to fix next. It is a plain table in
`docs/feedback-log.md` in the project (committed). One entry: date, what the user was doing, what got in
the way, how badly. It is read at the weekly review, so concrete entries are worth much more than
polite ones.

## Recording an entry

```
python3 .ludovanta/ludovanta.py feedback add "<what got in the way>" --doing "<what the user was doing>" --severity 1|2|3
```

On Windows use `python` (or `py -3`) if `python3` is not available. The command creates the file the
first time.

- **What got in the way**: close to the user's own words, plus the concrete fact behind it, in the
  user's language. "Codex rewrote the fare tests three times, they are still red" is useful;
  "tests are bad" is not. If the user only said "запиши, что неудобно", write what just happened in
  this session that they are reacting to, and say what you wrote.
- **Doing**: the task or the moment (`T-012 fare meter`, `installing Unity MCP`, `reviewing M1`).
- **Severity**: 1 annoying, 2 slowed the work down, 3 blocked it or needed outside help. Judge from
  the user's words; when unsure, 2.
- One entry per problem. Two different complaints are two entries.

Then confirm in one short line (for example «Записал в журнал трения (сила 2)») and carry on with
what you were doing. Do not argue, justify or apologise at length, and do not start fixing the
platform unless the user asks: the entry is the point.

If the user is clearly frustrated with the tools or the way agents work (not with the game itself)
but did not ask, you may offer once in a session: «Записать это в журнал трения?». Record only
after a yes.

## Weekly review

```
python3 .ludovanta/ludovanta.py feedback show [--days 7] [--json]   # --days 0 for the whole log
```

It lists the entries of the period, most severe first. When the user asks what got in the way this
week, group similar entries and show the top three in a few lines: what happened, how often, how
badly. Do not propose fixes for the platform itself unless asked.

## Rules

- The log belongs to the project and only grows: add rows at the end, never edit or delete old ones.
  The user may edit it by hand.
- Do not put secrets, tokens or personal data in it.
- Entries written in parallel worktrees merge without conflicts (`merge=union` in `.gitattributes`).
