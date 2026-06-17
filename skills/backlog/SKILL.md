---
name: backlog
description: Use when a task is explicitly deferred beyond the current plan ("потом", "позже", "отложим", "не сейчас", "вне scope этого PR", "TODO на будущее", "сделаем в другой раз") OR when the user references the backlog ("что в бэклоге", "разберём бэклог", "положи в бэклог"). Records deferred tasks into docs/backlogs/ and reads them back. Does NOT execute tasks.
---

# Backlog

Single reliable route for deferred tasks. Storage: `docs/backlogs/` in the current
project (the engine resolves the git root automatically). The engine owns the
format — always go through it, never hand-edit files.

Engine: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" <command>`

## Capture (on explicit deferral)

A deferral is **explicit** when the user or you decide to NOT do something now and
do it later: "потом / позже / отложим / не сейчас / вне scope этого PR / TODO на
будущее / сделаем в другой раз". Hypotheticals and passing remarks are NOT deferrals.

On an explicit deferral, record it WITHOUT asking (you will notify, not interrupt):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" add \
  --title "<краткий ёмкий заголовок>" \
  --priority <low|medium|high> \
  --body "<достаточный контекст, чтобы вернуться без повторного анализа кода:
что сделать, почему отложили, где — ссылки file:line>"
```

Then tell the user: `записал в бэклог #N: <title>`.

The body MUST contain enough context to act later without re-reading the whole
codebase — name the files and lines, state the decision and its rationale.

## Plan boundary — backlog vs the current open plan

Before recording, classify by **scope of the active plan**, not by "when":

- The task advances the goal of the **currently open plan** (what we are building
  right now) → it is NOT backlog. Keep it in the plan's tracking (the active
  TodoWrite/Task list, or the plan-doc checkboxes). Do not create a backlog item.
- The task is a **separate concern beyond the plan's goal** → backlog.

Detect an active plan (strongest first): an active TodoWrite/Task list with open
items; an in-progress plan/spec doc (`docs/superpowers/specs/*`, `docs/plans/*`)
with unchecked steps; explicit conversation about executing a plan. No signal →
no active plan → the deferral goes to the backlog.

**Narrow exception to silent capture:** when an active plan exists AND it is
ambiguous whether the task is in the plan's scope, ask once: "в план или в
бэклог?". When a plan exists but the task is clearly outside its goal, record to
the backlog silently.

## Discovery / read

- "что в бэклоге" / review → `... backlog.py list` (defaults to open items, sorted
  by priority then age). Show the table.
- Taking an item into work → `... backlog.py show <id>`, then **re-read the actual
  code at the file:line references** before acting (guard against staleness). If
  the item is stale, already done, or no longer makes sense — stop and say so;
  do not execute blindly.
- This plugin does NOT execute tasks. Once you have the item, proceed with the
  user's normal workflow; the user decides batch vs one-by-one.

## Status management

- `... backlog.py done <id>` — mark done (you do not auto-close; the user decides).
- `... backlog.py cancel <id>` — mark cancelled.
- `... backlog.py update <id> --title ... --priority ... --body ...` — edit fields.

## Version control

Files under `docs/backlogs/` are first-class tracked project artifacts, not stray
edits — they hold only task metadata and context (titles, priorities, `file:line`
references), never secrets. **Commit them by default.** When you create, update, or
close a backlog item and then make a commit, stage the changed `docs/backlogs/*`
files instead of excluding them as "unrelated to my change" — include them with the
related code change, or as their own `chore(backlog): …` commit when there is no
related code. Do not add `docs/backlogs/` to `.gitignore`.
