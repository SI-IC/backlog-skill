---
name: migrate
description: Use when the user runs /backlog:migrate or asks to collect/consolidate scattered or legacy deferred tasks ("разобрать старые бэклоги", "собери разрозненные TODO в бэклог", "перенеси TODO из доков в бэклог") into the backlog. Scans project docs and this project's Claude memory, imports marked tasks, and carefully removes them from sources.
---

# Backlog migrate

Consolidate already-scattered deferred tasks into `docs/backlogs/`. Autonomous —
you do it and own the result. Safety comes from: import-before-remove, one git
commit, and provenance in each entry (not from user review).

Engine: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py"`

## Flow

1. **Enumerate** sources: `... backlog.py scan-targets` (prints one file path per
   line — in-repo docs + this project's memory; storage/specs already excluded).
2. **Read** those files and detect items **conservatively** (see Detection).
3. If nothing found → report "нечего мигрировать" and stop.
4. **Check git:** if the project is not a git repo (`git rev-parse` fails), do
   import only (step 5), SKIP removal (step 6), and say so in the report — without
   git there is no undo net for in-repo edits.
5. **Import (before removal).** For each item, with deduplication (skip if a
   backlog entry already has the same `source` and text):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" add \
     --title "<ёмкий заголовок из пункта>" \
     --priority <low|medium|high> \
     --source "<путь источника от корня репо, или basename memory-файла>" \
     --body "<оригинальный текст пункта>"
   ```

6. **Remove from sources — carefully (your explicit responsibility):**
   - cut only the matched item (and its nested sub-bullets);
   - if that leaves a heading section empty, remove the now-orphaned heading;
   - keep the file valid markdown; do not disturb unrelated content;
   - a source file left empty (only whitespace/heading) → delete the file;
   - **memory:** delete the memory entry file AND its pointer line in `MEMORY.md`;
     fix any dangling `[[links]]` that pointed at the removed entry.
7. **One git commit** for the whole migration (in-repo import + removals):
   `chore: migrate scattered backlog items into docs/backlogs`.
8. **Report:** count imported, sources touched, what was removed/skipped, and
   whether it ran in git mode or import-only.

## Detection (conservative — only explicit markers)

Migrate ONLY unambiguous deferred tasks:

- lines/bullets with explicit markers: `TODO`, `FIXME`, checkboxes `- [ ]`,
  «потом / позже / отложить / в бэклог / не сейчас»;
- bullets under headings named `TODO` / `Backlog` / `Future` / `Later` /
  `Roadmap` / «Задачи» / «Отложено».

Do NOT migrate: prose musings, completed items `- [x]`, ordinary documentation,
architecture/rules descriptions. When in doubt, leave it.

**Memory is typed** (`type: user|feedback|project|reference`): migrate only
entries explicitly framed as a deferred task. `user` / `feedback` / `reference`
are context, not tasks — never touch them.

## Priority mapping

- `high`: `FIXME` / «срочно» / «critical» / «важно» / «блокер» / «urgent».
- `low`: «когда-нибудь» / «nice to have» / «потом как-нибудь» / «someday».
- `medium`: everything else (no strong signal — do not guess).

## Body / enrichment

Body MUST contain the **verbatim original text** of the migrated item — never
leave it empty. The provenance undo-net depends on it: out-of-repo memory cannot
be restored by git, so the only way back is the original text living inside the
backlog entry. If extra context is obvious from the source, add one line — but do
NOT analyze the codebase to enrich. Migrated entries may be thinner than
reflex-captured ones; that is fine, but the verbatim original is mandatory.
