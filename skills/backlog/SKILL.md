---
name: backlog
description: Use when the user asks to record or read the backlog ("положи в бэклог", "запиши на потом", "отложим это", "что в бэклоге", "разберём бэклог") OR when you (Claude) noticed — while working — an unrelated bug or an out-of-scope side task and want, WITH the user's consent, to defer it OR when running autonomously in the background and a task needs the user's decision. Records deferred tasks into docs/backlogs/ and reads them back. Never captures silently on your own; does NOT execute tasks.
---

# Backlog

Single reliable route for deferred tasks. Storage: `docs/backlogs/` in the current
project (the engine resolves the git root automatically). The engine owns the
format — always go through it, never hand-edit files.

Engine: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" <command>`

## When to record — three cases only

**You NEVER capture silently on your own.** Noticing that something diverges a
little from the current task is NOT a trigger. There are exactly three cases where
a backlog entry is created; outside them, do not touch the backlog:

1. **The user tells you to.** Explicit instruction to defer/record: "положи в
   бэклог / запиши на потом / отложим это / вне scope этого PR — в бэклог". Record
   right away, no re-confirmation.
2. **You noticed something while working — WITH the user's consent.** During the
   task you find either (a) a **bug unrelated to the current task** that cannot or
   should not be fixed in passing this session, or (b) an **out-of-scope side task**
   (refactor, extraction, improvement) beyond what you were asked to do. Do NOT
   record it yourself. Mention it and **ask once**: "записать в бэклог?" — record
   only after the user agrees. If they say no, drop it.
3. **You are running autonomously in the background** (circle/worktree/loop, a
   detached session, a subagent with no interactive user) AND a task genuinely
   needs the user's decision that you cannot make and cannot ask for right now.
   Record it so the decision is not lost — this is the ONLY path where you write
   without an explicit user go-ahead, and it exists precisely because no human is
   here to be asked.

Hypotheticals, passing remarks, and tasks that advance the current goal are not
backlog material. A task that belongs to the **currently open plan** stays in the
plan's own tracking (the active TodoWrite/Task list or the plan-doc checkboxes) —
never mirror it into the backlog.

### How to record (once one of the three cases applies)

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
