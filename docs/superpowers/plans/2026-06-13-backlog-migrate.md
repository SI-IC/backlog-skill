# Backlog Migrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/backlog:migrate` command that finds explicitly-marked deferred tasks scattered across project docs/memory, imports them into `docs/backlogs/` with provenance, and surgically removes them from sources — autonomously, with git + provenance as the safety net.

**Architecture:** Two deterministic engine additions (`scan-targets` subcommand that enumerates files to scan including the out-of-repo project memory dir; `--source` flag on `add` for provenance) plus an AI-driven skill (`skills/migrate/SKILL.md`) that does conservative detection and careful removal, driven by a prompt-style slash command. Engine parts are TDD'd; the judgment flow is verified by a headless smoke run.

**Tech Stack:** Python 3 stdlib, `unittest`, Markdown for skill/command.

---

## File Structure

```
scripts/backlog.py           # MODIFY: refactor resolve_dir→find_root; add scan_targets(); add source to add
tests/test_backlog.py        # MODIFY: tests for scan_targets, scan-targets CLI, --source
skills/migrate/SKILL.md      # CREATE: migration skill (detection + flow + careful removal)
commands/migrate.md          # CREATE: prompt-style slash command
README.md                    # MODIFY: document /backlog:migrate
.claude-plugin/plugin.json   # MODIFY: version bump
```

**Run engine tests:** `python3 -m unittest discover -s tests -v` (from repo root).

---

### Task 1: Refactor `resolve_dir` → `find_root` (no behavior change)

**Files:**

- Modify: `scripts/backlog.py`
- Test: `tests/test_backlog.py` (existing `TestResolveDir` must still pass)

- [ ] **Step 1: Run existing resolve_dir tests to confirm baseline green**

Run: `python3 -m unittest discover -s tests -k ResolveDir -v`
Expected: PASS (`test_prefers_git_root`, `test_falls_back_to_cwd`, `test_resolve_dir_worktree_git_file`).

- [ ] **Step 2: Extract `find_root`, keep `resolve_dir` as a thin wrapper**

In `scripts/backlog.py`, replace the existing `resolve_dir` function:

```python
def resolve_dir(start=None):
    cur = os.path.abspath(start or os.getcwd())
    d = cur
    while True:
        # os.path.exists, not isdir: in git worktrees ".git" is a file.
        if os.path.exists(os.path.join(d, ".git")):
            return os.path.join(d, "docs", "backlogs")
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.join(cur, "docs", "backlogs")
        d = parent
```

with:

```python
def find_root(start=None):
    cur = os.path.abspath(start or os.getcwd())
    d = cur
    while True:
        # os.path.exists, not isdir: in git worktrees ".git" is a file.
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return cur
        d = parent


def resolve_dir(start=None):
    return os.path.join(find_root(start), "docs", "backlogs")
```

- [ ] **Step 3: Run resolve_dir tests to confirm still green**

Run: `python3 -m unittest discover -s tests -k ResolveDir -v`
Expected: PASS (behavior unchanged — `resolve_dir` returns the same paths).

- [ ] **Step 4: Commit**

```bash
git add scripts/backlog.py
git commit -m "refactor: extract find_root from resolve_dir"
```

---

### Task 2: Engine — `scan_targets()`

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py` (before the `if __name__` line):

```python
class TestScanTargets(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, ".git"))
        self.home = tempfile.mkdtemp()

    def _w(self, rel, content="x"):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def _rel(self):
        return sorted(
            os.path.relpath(p, self.root)
            for p in backlog.scan_targets(self.root, self.home)
            if os.path.abspath(p).startswith(os.path.abspath(self.root))
        )

    def test_includes_named_and_docs(self):
        self._w("CLAUDE.md")
        self._w("TODO.md")
        self._w("docs/notes.md")
        self._w("src/CLAUDE.md")
        rel = self._rel()
        self.assertIn("CLAUDE.md", rel)
        self.assertIn("TODO.md", rel)
        self.assertIn(os.path.join("docs", "notes.md"), rel)
        self.assertIn(os.path.join("src", "CLAUDE.md"), rel)

    def test_excludes_own_storage_specs_and_random_files(self):
        self._w("docs/backlogs/1-x.md")
        self._w("docs/superpowers/specs/s.md")
        self._w("README.md")
        self._w("node_modules/pkg/CLAUDE.md")
        rel = self._rel()
        self.assertNotIn(os.path.join("docs", "backlogs", "1-x.md"), rel)
        self.assertNotIn(os.path.join("docs", "superpowers", "specs", "s.md"), rel)
        self.assertNotIn("README.md", rel)
        self.assertNotIn(os.path.join("node_modules", "pkg", "CLAUDE.md"), rel)

    def test_root_dump_files_not_nested(self):
        self._w("TODO.md")
        self._w("sub/TODO.md")
        rel = self._rel()
        self.assertIn("TODO.md", rel)
        self.assertNotIn(os.path.join("sub", "TODO.md"), rel)

    def test_includes_project_memory(self):
        enc = os.path.abspath(self.root).replace(os.sep, "-")
        mem = os.path.join(self.home, ".claude", "projects", enc, "memory")
        os.makedirs(mem)
        with open(os.path.join(mem, "MEMORY.md"), "w") as f:
            f.write("idx")
        with open(os.path.join(mem, "fact.md"), "w") as f:
            f.write("task")
        names = [os.path.basename(p) for p in backlog.scan_targets(self.root, self.home)]
        self.assertIn("MEMORY.md", names)
        self.assertIn("fact.md", names)

    def test_missing_memory_dir_no_error(self):
        self.assertIsInstance(backlog.scan_targets(self.root, self.home), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -k ScanTargets -v`
Expected: FAIL — `AttributeError: module 'backlog' has no attribute 'scan_targets'`.

- [ ] **Step 3: Write minimal implementation**

Add near the top of `scripts/backlog.py`, after the existing constants
(`FIELD_ORDER = ...`):

```python
ANYLEVEL_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
ROOT_DUMP_FILES = ("TODO.md", "TODOS.md", "NOTES.md", "BACKLOG.md",
                   "ROADMAP.md", "FIXME.md")
SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "target",
             ".next", ".venv", "venv", "__pycache__"}
```

Add these functions (anywhere after `find_root`, e.g. just below it):

```python
def _within(path, base):
    path = os.path.abspath(path)
    base = os.path.abspath(base)
    return path == base or path.startswith(base + os.sep)


def scan_targets(start=None, home=None):
    """Existing files to scan for scattered backlog items.

    In-repo: CLAUDE/AGENTS/GEMINI.md at any level, root-level dump files,
    docs/**/*.md — excluding our own storage and spec/plan dirs. Out-of-repo:
    this project's Claude memory dir only.
    """
    root = find_root(start)
    home = home or os.path.expanduser("~")
    backlogs_dir = os.path.join(root, "docs", "backlogs")
    superpowers_dir = os.path.join(root, "docs", "superpowers")
    docs_dir = os.path.join(root, "docs")
    targets = []

    for name in ROOT_DUMP_FILES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            targets.append(p)

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if _within(dirpath, backlogs_dir) or _within(dirpath, superpowers_dir):
            dirnames[:] = []
            continue
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if fn in ANYLEVEL_FILES:
                targets.append(full)
            elif fn.endswith(".md") and _within(dirpath, docs_dir):
                targets.append(full)

    enc = os.path.abspath(start or os.getcwd()).replace(os.sep, "-")
    mem_dir = os.path.join(home, ".claude", "projects", enc, "memory")
    if os.path.isdir(mem_dir):
        for fn in sorted(os.listdir(mem_dir)):
            if fn.endswith(".md"):
                targets.append(os.path.join(mem_dir, fn))

    seen, out = set(), []
    for p in targets:
        rp = os.path.abspath(p)
        if rp not in seen and os.path.isfile(rp):
            seen.add(rp)
            out.append(rp)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -k ScanTargets -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: scan_targets enumerates files to scan for migration"
```

---

### Task 3: Engine — `add --source` provenance field

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py`:

```python
class TestSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_add_with_source_writes_field(self):
        nid = backlog.cmd_add(self.tmp, "t", "low", "body", NOW, source="CLAUDE.md")
        self.assertEqual(backlog.find_entry(self.tmp, nid)["meta"]["source"], "CLAUDE.md")

    def test_add_without_source_has_no_field(self):
        nid = backlog.cmd_add(self.tmp, "t", "low", "body", NOW)
        self.assertNotIn("source", backlog.find_entry(self.tmp, nid)["meta"])

    def test_source_round_trips(self):
        text = backlog.serialize_entry(
            {"id": 1, "title": "t", "source": "docs/x.md"}, "b")
        self.assertIn("source: docs/x.md", text)
        self.assertEqual(backlog.parse_entry(text)["meta"]["source"], "docs/x.md")

    def test_add_source_via_cli(self):
        r = subprocess.run(
            [sys.executable, SCRIPT, "--dir", self.tmp, "add", "--title", "t",
             "--priority", "low", "--source", "CLAUDE.md", "--body", "b"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        r2 = subprocess.run([sys.executable, SCRIPT, "--dir", self.tmp, "show", "1"],
                            capture_output=True, text=True)
        self.assertIn("source: CLAUDE.md", r2.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -k Source -v`
Expected: FAIL — `cmd_add() got an unexpected keyword argument 'source'`.

- [ ] **Step 3: Write minimal implementation**

(a) Extend `FIELD_ORDER` in `scripts/backlog.py`:

```python
FIELD_ORDER = ("id", "title", "priority", "status", "created", "updated", "source")
```

(b) Change `cmd_add` signature and meta construction. Replace:

```python
def cmd_add(dirpath, title, priority, body, now):
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    title = sanitize_oneline(title)
    os.makedirs(dirpath, exist_ok=True)
    ts = iso(now)
    # Exclusive create with retry: two concurrent adds must never silently
    # overwrite each other's file.
    for _ in range(100):
        nid = next_id(dirpath)
        meta = {
            "id": nid,
            "title": title,
            "priority": priority,
            "status": "open",
            "created": ts,
            "updated": ts,
        }
        path = os.path.join(dirpath, f"{nid}-{slugify(title)}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(serialize_entry(meta, body))
            return nid
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a backlog id")
```

with (adds the `source` parameter and conditional field):

```python
def cmd_add(dirpath, title, priority, body, now, source=None):
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    title = sanitize_oneline(title)
    os.makedirs(dirpath, exist_ok=True)
    ts = iso(now)
    # Exclusive create with retry: two concurrent adds must never silently
    # overwrite each other's file.
    for _ in range(100):
        nid = next_id(dirpath)
        meta = {
            "id": nid,
            "title": title,
            "priority": priority,
            "status": "open",
            "created": ts,
            "updated": ts,
        }
        if source:
            meta["source"] = sanitize_oneline(source)
        path = os.path.join(dirpath, f"{nid}-{slugify(title)}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(serialize_entry(meta, body))
            return nid
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a backlog id")
```

(c) Wire `--source` into the CLI. In `main`, find the `add` subparser block:

```python
    pa = sub.add_parser("add")
    pa.add_argument("--title", required=True)
    pa.add_argument("--priority", default="medium")
    pa.add_argument("--body", default=None)
```

add one line:

```python
    pa.add_argument("--source", default=None)
```

and in the `add` dispatch branch, replace:

```python
        if args.cmd == "add":
            body = args.body
            if body is None and not sys.stdin.isatty():
                body = sys.stdin.read()
            print(cmd_add(dirpath, args.title, args.priority, body or "", now))
```

with:

```python
        if args.cmd == "add":
            body = args.body
            if body is None and not sys.stdin.isatty():
                body = sys.stdin.read()
            print(cmd_add(dirpath, args.title, args.priority, body or "", now,
                          source=args.source))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -k Source -v`
Expected: PASS (4 tests). Then full suite: `python3 -m unittest discover -s tests` → OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: add --source provenance field to backlog add"
```

---

### Task 4: Engine — `scan-targets` CLI subcommand

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py`:

```python
class TestScanTargetsCLI(unittest.TestCase):
    def test_scan_targets_cli_lists_files(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        with open(os.path.join(root, "CLAUDE.md"), "w") as f:
            f.write("x")
        r = subprocess.run([sys.executable, SCRIPT, "scan-targets"],
                           capture_output=True, text=True, cwd=root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("CLAUDE.md", r.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -k ScanTargetsCLI -v`
Expected: FAIL — argparse errors on unknown subcommand `scan-targets` (non-zero exit).

- [ ] **Step 3: Write minimal implementation**

In `main`, register the subparser. After the `update` subparser block
(`pu.add_argument("--body", default=None)`), add:

```python
    sub.add_parser("scan-targets")
```

In the dispatch chain, after the `add` branch (before `list`), add:

```python
        elif args.cmd == "scan-targets":
            for p in scan_targets():
                print(p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -k ScanTargetsCLI -v`
Expected: PASS. Full suite: `python3 -m unittest discover -s tests` → OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: scan-targets CLI subcommand"
```

---

### Task 5: Migration skill

**Files:**

- Create: `skills/migrate/SKILL.md`

- [ ] **Step 1: Create the skill**

Create `skills/migrate/SKILL.md`:

````markdown
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

Body = the original item text (it is also the provenance). If context is obvious
from the source, add one line — but do NOT analyze the codebase to enrich.
Migrated entries may be thinner than reflex-captured ones; that is fine.
````

- [ ] **Step 2: Commit**

```bash
git add skills/migrate/SKILL.md
git commit -m "feat: migration skill (detect + import + careful removal)"
```

---

### Task 6: Slash command

**Files:**

- Create: `commands/migrate.md`

- [ ] **Step 1: Create the command**

Create `commands/migrate.md`:

```markdown
---
description: Собрать разрозненные/легаси отложенные задачи из доков и памяти проекта в бэклог (импорт + аккуратное удаление из источников, один git-коммит).
---

Выполни миграцию бэклога по скиллу `migrate`. Поток: `scan-targets` → консервативно
найти помеченные задачи (TODO/FIXME/чекбоксы/«потом» и буллеты под TODO/Backlog/
Future/Roadmap-заголовками) → импортировать в бэклог с `--source` (импорт раньше
удаления) → аккуратно вычистить из источников (осиротевшие заголовки, sync
`MEMORY.md`, починка `[[links]]`) → один git-коммит → отчёт. Нет git → только импорт,
без удаления. Консервативно: сомнение — не трогай.

Доп. указания пользователя: $ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git add commands/migrate.md
git commit -m "feat: /backlog:migrate slash command"
```

---

### Task 7: README + version bump + headless smoke verification

**Files:**

- Modify: `README.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Document the command in README**

In `README.md`, in the "## Использование" command table, add a row after the
`/backlog:cancel <id>` row:

```markdown
| `/backlog:migrate` | собрать разрозненные/легаси TODO из доков и памяти проекта в бэклог |
```

- [ ] **Step 2: Bump version**

In `.claude-plugin/plugin.json`, change `"version": "0.1.2"` to `"version": "0.2.0"`
(new feature → minor bump).

- [ ] **Step 3: Validate manifests**

Run: `claude plugin validate .`
Expected: `✔ Validation passed`.

- [ ] **Step 4: Full engine regression**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (all tests green, including the new scan_targets / source ones).

- [ ] **Step 5: Reinstall the updated plugin**

```bash
claude plugin uninstall backlog@backlog
claude plugin marketplace update backlog
claude plugin install backlog@backlog
```

Expected: installed version `0.2.0`.

- [ ] **Step 6: Headless smoke on a fixture project**

```bash
T=$(mktemp -d); cd "$T" && git init -q
printf '# Project\n\n## TODO\n- TODO: вынести retry в декоратор (api/client.py:88)\n- [x] уже сделано\n\nОбычная документация, не задача.\n' > CLAUDE.md
printf '# Tasks\n\n- FIXME: переписать auth на проверенную JWT-либу\n' > TODO.md
claude -p "/backlog:migrate" --permission-mode bypassPermissions 2>&1 | tail -8
echo "=== backlog entries ==="; cat docs/backlogs/*.md
echo "=== CLAUDE.md after ==="; cat CLAUDE.md
echo "=== TODO.md after (expect: gone) ==="; cat TODO.md 2>&1
echo "=== git log ==="; git log --oneline | head -3
cd /Users/alex/Documents/backlog-skill; rm -rf "$T"
```

Expected:

- `docs/backlogs/` has two entries, each with a `source:` field (`CLAUDE.md`, `TODO.md`)
  and original text in the body; `FIXME` item is `priority: high`.
- `CLAUDE.md`: the `TODO:` bullet is removed; the `- [x]` completed line and the
  "Обычная документация" line are untouched.
- `TODO.md`: deleted (it became empty after its only task migrated).
- `git log`: a single `chore: migrate scattered backlog items...` commit.

- [ ] **Step 7: Commit**

```bash
git add README.md .claude-plugin/plugin.json
git commit -m "docs: document /backlog:migrate; bump 0.2.0"
```

---

## Final Verification (after all tasks)

- [ ] `python3 -m unittest discover -s tests -v` — full suite green.
- [ ] `sh hooks/session-start.test.sh` — hook test green (unchanged).
- [ ] Headless smoke (Task 7 Step 6) behaves as specified.
- [ ] Installed plugin is `0.2.0`; `/backlog:migrate` is listed and runs.
