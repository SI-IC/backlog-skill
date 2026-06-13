# Backlog Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin `backlog` that gives Claude a reliable reflex to record deferred tasks into `docs/backlogs/` of the current project, plus commands to list and manage them.

**Architecture:** Three layers. A zero-dependency Python CLI engine (`scripts/backlog.py`) owns the file format, id generation, timestamps, sorting. A skill (`skills/backlog/SKILL.md`) is the forcing function — it triggers on explicit deferrals and on backlog references, and calls the engine. Thin slash-commands wrap the engine. A minimal SessionStart hook keeps the reflex alive every session.

**Tech Stack:** Python 3 (stdlib only — no pip deps), `unittest` for tests (stdlib), POSIX `sh` for the hook, Markdown for skill/commands, JSON for plugin/hook manifests.

---

## File Structure

```
backlog/                              (= repo root /Users/alex/Documents/backlog-skill)
  .claude-plugin/plugin.json          # plugin manifest
  scripts/backlog.py                  # CLI engine (all format logic)
  tests/test_backlog.py               # unittest suite for the engine
  skills/backlog/SKILL.md             # forcing-function skill
  commands/list.md  add.md  done.md  cancel.md
  hooks/hooks.json                    # SessionStart registration
  hooks/session-start.sh              # prints the reflex reminder
  README.md
```

Engine responsibilities are split into small pure functions (`slugify`, `parse_entry`, `serialize_entry`, `next_id`, `load_all`, `find_entry`, `cmd_add`, `cmd_list`, `cmd_show`, `cmd_set_status`, `cmd_update`, `resolve_dir`, `main`) so each is testable in isolation. Tests inject a temp `--dir` and a fixed `now`, so no test touches a real clock or a real project.

**Run tests with:** `python3 -m unittest discover -s tests -v` (from repo root).

---

### Task 1: Plugin scaffold + manifest

**Files:**

- Create: `.claude-plugin/plugin.json`
- Create: `scripts/.gitkeep`, `tests/.gitkeep` (placeholders so dirs exist)

- [ ] **Step 1: Create the plugin manifest**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "backlog",
  "description": "Project backlog manager — gives Claude a reliable reflex to record deferred tasks (out-of-plan only) into docs/backlogs/, with commands to list and manage them. Files-based, in-repo, no execution engine.",
  "version": "0.1.0"
}
```

- [ ] **Step 2: Create placeholder dirs**

```bash
mkdir -p scripts tests skills/backlog commands hooks
touch scripts/.gitkeep tests/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json scripts/.gitkeep tests/.gitkeep
git commit -m "feat: plugin scaffold and manifest"
```

---

### Task 2: Engine — slugify + parse/serialize round-trip

**Files:**

- Create: `scripts/backlog.py`
- Create: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_backlog.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import backlog  # noqa: E402

NOW = datetime(2026, 6, 13, 12, 30, 0, tzinfo=timezone.utc)


class TestSlugify(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(backlog.slugify("Add user validation"), "add-user-validation")

    def test_cyrillic_preserved(self):
        # Russian titles must survive — not collapse to "task"
        self.assertEqual(backlog.slugify("Вынести валидацию"), "вынести-валидацию")

    def test_punctuation_and_spaces_collapse(self):
        self.assertEqual(backlog.slugify("Fix:  the //bug!!"), "fix-the-bug")

    def test_empty_falls_back(self):
        self.assertEqual(backlog.slugify("!!!"), "task")

    def test_truncated(self):
        self.assertEqual(len(backlog.slugify("a" * 200)), 50)


class TestParseSerialize(unittest.TestCase):
    def test_round_trip(self):
        meta = {
            "id": 5, "title": "Hello", "priority": "medium",
            "status": "open", "created": "2026-06-13T12:30:00Z",
            "updated": "2026-06-13T12:30:00Z",
        }
        body = "Line one.\nLine two.\n"
        text = backlog.serialize_entry(meta, body)
        parsed = backlog.parse_entry(text)
        self.assertEqual(parsed["meta"]["id"], 5)
        self.assertEqual(parsed["meta"]["title"], "Hello")
        self.assertEqual(parsed["meta"]["priority"], "medium")
        self.assertEqual(parsed["body"].strip(), "Line one.\nLine two.")

    def test_body_with_dashes_preserved(self):
        # A body containing '---' must not break parsing
        text = backlog.serialize_entry({"id": 1, "title": "t"}, "before\n---\nafter\n")
        parsed = backlog.parse_entry(text)
        self.assertIn("---", parsed["body"])

    def test_missing_frontmatter_raises(self):
        with self.assertRaises(ValueError):
            backlog.parse_entry("no frontmatter here")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backlog'` (file not yet created).

- [ ] **Step 3: Write minimal implementation**

Create `scripts/backlog.py`:

```python
#!/usr/bin/env python3
"""Backlog engine — owns the docs/backlogs file format. Stdlib only."""
import argparse
import os
import re
import sys
from datetime import datetime, timezone

PRIORITIES = ("low", "medium", "high")
STATUSES = ("open", "done", "cancelled")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
FIELD_ORDER = ("id", "title", "priority", "status", "created", "updated")


def slugify(title, maxlen=50):
    s = title.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    s = s[:maxlen].strip("-")
    return s or "task"


def serialize_entry(meta, body):
    lines = ["---"]
    for k in FIELD_ORDER:
        if k in meta:
            lines.append(f"{k}: {meta[k]}")
    fm = "\n".join(lines) + "\n---\n"
    body = (body or "").strip("\n")
    return fm + (body + "\n" if body else "\n")


def parse_entry(text):
    if not text.startswith("---"):
        raise ValueError("missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("malformed frontmatter")
    meta = {}
    for line in parts[1].strip().splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"bad meta line: {line!r}")
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    if "id" in meta:
        meta["id"] = int(meta["id"])
    body = parts[2].lstrip("\n")
    return {"meta": meta, "body": body}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS for `TestSlugify` and `TestParseSerialize` (8 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog engine slugify + frontmatter parse/serialize"
```

---

### Task 3: Engine — next_id + load_all (empty dir, malformed skip)

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py` (before the `if __name__` line):

```python
import tempfile  # noqa: E402


class TestNextIdLoadAll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_next_id_empty_dir_is_one(self):
        self.assertEqual(backlog.next_id(self.tmp), 1)

    def test_next_id_nonexistent_dir_is_one(self):
        self.assertEqual(backlog.next_id(os.path.join(self.tmp, "nope")), 1)

    def test_next_id_uses_max_plus_one_not_gap(self):
        self._write("1-a.md", "---\nid: 1\n---\n")
        self._write("4-b.md", "---\nid: 4\n---\n")
        # gap at 2,3 must NOT be reused
        self.assertEqual(backlog.next_id(self.tmp), 5)

    def test_load_all_skips_malformed(self):
        self._write("1-ok.md", backlog.serialize_entry(
            {"id": 1, "title": "ok", "status": "open"}, "body"))
        self._write("2-bad.md", "this is not valid frontmatter")
        entries = backlog.load_all(self.tmp)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["meta"]["id"], 1)

    def test_load_all_empty_dir(self):
        self.assertEqual(backlog.load_all(self.tmp), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `AttributeError: module 'backlog' has no attribute 'next_id'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/backlog.py`:

```python
def next_id(dirpath):
    if not os.path.isdir(dirpath):
        return 1
    max_id = 0
    for name in os.listdir(dirpath):
        if not name.endswith(".md"):
            continue
        m = re.match(r"(\d+)-", name)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1


def load_all(dirpath):
    entries = []
    if not os.path.isdir(dirpath):
        return entries
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(dirpath, name)
        try:
            with open(path, encoding="utf-8") as f:
                entry = parse_entry(f.read())
            entry["path"] = path
            entries.append(entry)
        except (ValueError, OSError) as e:
            print(f"warning: skipping {name}: {e}", file=sys.stderr)
    return entries


def find_entry(dirpath, id_):
    for e in load_all(dirpath):
        if e["meta"].get("id") == id_:
            return e
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (5 new tests green, all prior still green).

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog engine next_id + load_all with malformed-skip"
```

---

### Task 4: Engine — cmd_add (creates file, validates priority)

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py`:

```python
class TestAdd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_add_creates_file_with_id_one(self):
        nid = backlog.cmd_add(self.tmp, "First task", "high", "do the thing", NOW)
        self.assertEqual(nid, 1)
        files = os.listdir(self.tmp)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("1-"))

    def test_add_sets_required_fields(self):
        nid = backlog.cmd_add(self.tmp, "Task", "low", "ctx", NOW)
        e = backlog.find_entry(self.tmp, nid)
        m = e["meta"]
        self.assertEqual(m["status"], "open")
        self.assertEqual(m["priority"], "low")
        self.assertEqual(m["created"], "2026-06-13T12:30:00Z")
        self.assertEqual(m["created"], m["updated"])
        self.assertEqual(e["body"].strip(), "ctx")

    def test_add_creates_missing_dir(self):
        nested = os.path.join(self.tmp, "docs", "backlogs")
        nid = backlog.cmd_add(nested, "T", "medium", "", NOW)
        self.assertEqual(nid, 1)
        self.assertTrue(os.path.isdir(nested))

    def test_add_increments_id(self):
        backlog.cmd_add(self.tmp, "A", "low", "", NOW)
        nid = backlog.cmd_add(self.tmp, "B", "low", "", NOW)
        self.assertEqual(nid, 2)

    def test_add_rejects_bad_priority(self):
        with self.assertRaises(ValueError):
            backlog.cmd_add(self.tmp, "T", "urgent", "", NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `AttributeError: module 'backlog' has no attribute 'cmd_add'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/backlog.py`:

```python
def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def cmd_add(dirpath, title, priority, body, now):
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    os.makedirs(dirpath, exist_ok=True)
    nid = next_id(dirpath)
    ts = iso(now)
    meta = {"id": nid, "title": title, "priority": priority,
            "status": "open", "created": ts, "updated": ts}
    path = os.path.join(dirpath, f"{nid}-{slugify(title)}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(serialize_entry(meta, body))
    return nid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (5 new tests green).

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog engine cmd_add"
```

---

### Task 5: Engine — cmd_list (filter, sort, age, table)

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py`:

```python
from datetime import timedelta  # noqa: E402


class TestList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_message(self):
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("пуст", out.lower())

    def test_default_hides_done_and_cancelled(self):
        a = backlog.cmd_add(self.tmp, "open one", "medium", "", NOW)
        b = backlog.cmd_add(self.tmp, "done one", "medium", "", NOW)
        backlog.cmd_set_status(self.tmp, b, "done", NOW)
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("open one", out)
        self.assertNotIn("done one", out)

    def test_status_all_shows_everything(self):
        backlog.cmd_add(self.tmp, "open one", "medium", "", NOW)
        b = backlog.cmd_add(self.tmp, "done one", "medium", "", NOW)
        backlog.cmd_set_status(self.tmp, b, "done", NOW)
        out = backlog.cmd_list(self.tmp, status="all", now=NOW)
        self.assertIn("done one", out)

    def test_priority_sort_high_first_then_oldest(self):
        # created at different times to assert intra-priority ordering
        backlog.cmd_add(self.tmp, "low task", "low", "", NOW)
        backlog.cmd_add(self.tmp, "high newer", "high", "", NOW)
        # force an older high by writing directly
        older = backlog.serialize_entry({
            "id": 99, "title": "high older", "priority": "high",
            "status": "open", "created": "2026-06-01T00:00:00Z",
            "updated": "2026-06-01T00:00:00Z"}, "")
        with open(os.path.join(self.tmp, "99-high-older.md"), "w",
                  encoding="utf-8") as f:
            f.write(older)
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertLess(out.index("high older"), out.index("high newer"))
        self.assertLess(out.index("high newer"), out.index("low task"))

    def test_age_days(self):
        created = NOW - timedelta(days=2)
        path = os.path.join(self.tmp, "1-x.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(backlog.serialize_entry({
                "id": 1, "title": "x", "priority": "low", "status": "open",
                "created": backlog.iso(created), "updated": backlog.iso(created)}, ""))
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("2d", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `cmd_list` / `cmd_set_status` not defined yet.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/backlog.py`:

```python
def age(created_str, now):
    created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    secs = int((now - created).total_seconds())
    if secs < 3600:
        return f"{max(secs // 60, 0)}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def cmd_list(dirpath, status="open", sort="priority", priority=None, now=None):
    entries = load_all(dirpath)
    if status != "all":
        entries = [e for e in entries if e["meta"].get("status") == status]
    if priority:
        entries = [e for e in entries if e["meta"].get("priority") == priority]
    if sort == "priority":
        entries.sort(key=lambda e: (PRIORITY_ORDER.get(e["meta"].get("priority"), 9),
                                    e["meta"].get("created", "")))
    else:
        entries.sort(key=lambda e: e["meta"].get("created", ""))
    if not entries:
        return "Бэклог пуст (нет задач по текущему фильтру)."
    rows = [("#", "PRI", "STATUS", "AGE", "TITLE")]
    for e in entries:
        m = e["meta"]
        rows.append((str(m.get("id", "?")), m.get("priority", "?"),
                     m.get("status", "?"), age(m.get("created"), now),
                     m.get("title", "")))
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    out = []
    for r in rows:
        cols = "  ".join(r[i].ljust(widths[i]) for i in range(4))
        out.append(f"{cols}  {r[4]}")
    return "\n".join(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (5 new tests green). Note: `cmd_set_status` is used by these tests and is implemented in Task 6 — if running this task in isolation, implement Task 6's `cmd_set_status` first, or run the full suite after Task 6. Recommended: implement Task 5 and Task 6 code together, then run.

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog engine cmd_list with filter/sort/age"
```

---

### Task 6: Engine — show / set_status / update (missing-id errors)

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py`:

```python
class TestMutations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.id = backlog.cmd_add(self.tmp, "Task", "medium", "context", NOW)

    def test_show_returns_full_entry(self):
        out = backlog.cmd_show(self.tmp, self.id)
        self.assertIn("title: Task", out)
        self.assertIn("context", out)

    def test_show_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            backlog.cmd_show(self.tmp, 999)

    def test_done_sets_status_and_bumps_updated(self):
        later = NOW + timedelta(hours=1)
        backlog.cmd_set_status(self.tmp, self.id, "done", later)
        e = backlog.find_entry(self.tmp, self.id)
        self.assertEqual(e["meta"]["status"], "done")
        self.assertEqual(e["meta"]["updated"], backlog.iso(later))
        self.assertEqual(e["meta"]["created"], "2026-06-13T12:30:00Z")  # unchanged

    def test_set_status_rejects_invalid(self):
        with self.assertRaises(ValueError):
            backlog.cmd_set_status(self.tmp, self.id, "wip", NOW)

    def test_set_status_missing_raises(self):
        with self.assertRaises(KeyError):
            backlog.cmd_set_status(self.tmp, 999, "done", NOW)

    def test_update_title_and_priority_bumps_updated(self):
        later = NOW + timedelta(hours=2)
        backlog.cmd_update(self.tmp, self.id, {"title": "New", "priority": "high"},
                           None, later)
        e = backlog.find_entry(self.tmp, self.id)
        self.assertEqual(e["meta"]["title"], "New")
        self.assertEqual(e["meta"]["priority"], "high")
        self.assertEqual(e["meta"]["updated"], backlog.iso(later))

    def test_update_body(self):
        backlog.cmd_update(self.tmp, self.id, {}, "new body", NOW)
        e = backlog.find_entry(self.tmp, self.id)
        self.assertEqual(e["body"].strip(), "new body")

    def test_update_rejects_bad_priority(self):
        with self.assertRaises(ValueError):
            backlog.cmd_update(self.tmp, self.id, {"priority": "x"}, None, NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `cmd_show` / `cmd_set_status` / `cmd_update` not defined (or partially, if Task 5 already added `cmd_set_status` — in that case implement the remaining two).

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/backlog.py`:

```python
def _write_entry(entry):
    with open(entry["path"], "w", encoding="utf-8") as f:
        f.write(serialize_entry(entry["meta"], entry["body"]))


def cmd_show(dirpath, id_):
    e = find_entry(dirpath, id_)
    if not e:
        raise KeyError(f"no backlog item with id {id_}")
    return serialize_entry(e["meta"], e["body"])


def cmd_set_status(dirpath, id_, status, now):
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    e = find_entry(dirpath, id_)
    if not e:
        raise KeyError(f"no backlog item with id {id_}")
    e["meta"]["status"] = status
    e["meta"]["updated"] = iso(now)
    _write_entry(e)


def cmd_update(dirpath, id_, fields, body, now):
    if "priority" in fields and fields["priority"] not in PRIORITIES:
        raise ValueError(f"invalid priority: {fields['priority']}")
    e = find_entry(dirpath, id_)
    if not e:
        raise KeyError(f"no backlog item with id {id_}")
    e["meta"].update(fields)
    if body is not None:
        e["body"] = body
    e["meta"]["updated"] = iso(now)
    _write_entry(e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — full suite green (all tasks 2-6).

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog engine show/set_status/update with missing-id errors"
```

---

### Task 7: Engine — CLI (argparse, resolve_dir, stdin body)

**Files:**

- Modify: `scripts/backlog.py`
- Modify: `tests/test_backlog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backlog.py` (subprocess test — exercises the real CLI end-to-end):

```python
import subprocess  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "backlog.py")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, SCRIPT, "--dir", self.tmp, *args],
            capture_output=True, text=True, input=stdin)

    def test_add_then_list(self):
        r = self._run("add", "--title", "CLI task", "--priority", "high",
                      "--body", "ctx")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "1")
        r2 = self._run("list")
        self.assertIn("CLI task", r2.stdout)
        self.assertIn("high", r2.stdout)

    def test_add_body_from_stdin(self):
        r = self._run("add", "--title", "T", "--priority", "low", stdin="piped body")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("show", "1")
        self.assertIn("piped body", r2.stdout)

    def test_done_missing_id_nonzero_exit(self):
        r = self._run("done", "42")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr.lower())

    def test_bad_priority_nonzero_exit(self):
        r = self._run("add", "--title", "T", "--priority", "urgent")
        self.assertNotEqual(r.returncode, 0)


class TestResolveDir(unittest.TestCase):
    def test_prefers_git_root(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        sub = os.path.join(root, "a", "b")
        os.makedirs(sub)
        self.assertEqual(backlog.resolve_dir(sub),
                         os.path.join(root, "docs", "backlogs"))

    def test_falls_back_to_cwd(self):
        plain = tempfile.mkdtemp()
        self.assertEqual(backlog.resolve_dir(plain),
                         os.path.join(plain, "docs", "backlogs"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `resolve_dir` missing and the script has no `__main__` CLI yet.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/backlog.py`:

```python
def resolve_dir(start=None):
    cur = os.path.abspath(start or os.getcwd())
    d = cur
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return os.path.join(d, "docs", "backlogs")
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.join(cur, "docs", "backlogs")
        d = parent


def main(argv=None):
    p = argparse.ArgumentParser(prog="backlog")
    p.add_argument("--dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add")
    pa.add_argument("--title", required=True)
    pa.add_argument("--priority", default="medium")
    pa.add_argument("--body", default=None)

    pl = sub.add_parser("list")
    pl.add_argument("--status", default="open")
    pl.add_argument("--sort", default="priority")
    pl.add_argument("--priority", default=None)

    for name in ("show", "done", "cancel"):
        sp = sub.add_parser(name)
        sp.add_argument("id", type=int)

    pu = sub.add_parser("update")
    pu.add_argument("id", type=int)
    pu.add_argument("--title", default=None)
    pu.add_argument("--priority", default=None)
    pu.add_argument("--body", default=None)

    args = p.parse_args(argv)
    dirpath = args.dir or resolve_dir()
    now = datetime.now(timezone.utc)
    try:
        if args.cmd == "add":
            body = args.body
            if body is None and not sys.stdin.isatty():
                body = sys.stdin.read()
            print(cmd_add(dirpath, args.title, args.priority, body or "", now))
        elif args.cmd == "list":
            print(cmd_list(dirpath, args.status, args.sort, args.priority, now))
        elif args.cmd == "show":
            print(cmd_show(dirpath, args.id), end="")
        elif args.cmd == "done":
            cmd_set_status(dirpath, args.id, "done", now)
            print(f"#{args.id} → done")
        elif args.cmd == "cancel":
            cmd_set_status(dirpath, args.id, "cancelled", now)
            print(f"#{args.id} → cancelled")
        elif args.cmd == "update":
            fields = {}
            if args.title is not None:
                fields["title"] = args.title
            if args.priority is not None:
                fields["priority"] = args.priority
            cmd_update(dirpath, args.id, fields, args.body, now)
            print(f"#{args.id} updated")
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — entire suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/backlog.py tests/test_backlog.py
git commit -m "feat: backlog CLI entrypoint + resolve_dir"
```

---

### Task 8: Skill — the forcing function

**Files:**

- Create: `skills/backlog/SKILL.md`

- [ ] **Step 1: Create the skill**

Create `skills/backlog/SKILL.md` (no test — verified by the install smoke check in Task 11):

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add skills/backlog/SKILL.md
git commit -m "feat: backlog forcing-function skill"
```

---

### Task 9: Slash commands

**Files:**

- Create: `commands/list.md`, `commands/add.md`, `commands/done.md`, `commands/cancel.md`

- [ ] **Step 1: Create `commands/list.md`**

```markdown
---
description: Показать бэклог проекта (по умолчанию open, сортировка важность→дата). Аргументы прокидываются в backlog.py list (напр. --all, --sort date, --priority high).
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" list $ARGUMENTS`
```

- [ ] **Step 2: Create `commands/add.md`**

````markdown
---
description: Добавить задачу в бэклог вручную. Используй когда пользователь явно просит записать в бэклог.
---

Добавь задачу в бэклог проекта через движок. Сформируй ёмкий заголовок и body с
достаточным контекстом (что сделать, почему, где — ссылки file:line), затем вызови:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" add --title "<...>" --priority <low|medium|high> --body "<...>"
```
````

Запрос пользователя: $ARGUMENTS

После создания сообщи: «записал в бэклог #N: <title>».

````

- [ ] **Step 3: Create `commands/done.md`**

```markdown
---
description: Пометить задачу бэклога выполненной по её id.
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" done $ARGUMENTS`
````

- [ ] **Step 4: Create `commands/cancel.md`**

```markdown
---
description: Отменить задачу бэклога по её id (статус cancelled).
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" cancel $ARGUMENTS`
```

- [ ] **Step 5: Commit**

```bash
git add commands/
git commit -m "feat: backlog slash commands (list/add/done/cancel)"
```

---

### Task 10: SessionStart hook (E2 — keep the reflex alive)

**Files:**

- Create: `hooks/hooks.json`
- Create: `hooks/session-start.sh`

- [ ] **Step 1: Create `hooks/session-start.sh`**

```sh
#!/bin/sh
# SessionStart hook for the backlog plugin.
# Prints one reminder line so Claude keeps the deferral reflex alive every session.
# Output goes to stdout and is injected into context (non-blocking).
echo "[backlog] Если задача откладывается ЗА ПРЕДЕЛЫ текущего плана — не бросай её в память/случайный файл, запиши через скилл backlog (движок: scripts/backlog.py, хранилище: docs/backlogs/). Деферрал внутри scope открытого плана остаётся в трекинге плана, не в бэклоге."
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x hooks/session-start.sh
```

- [ ] **Step 3: Create `hooks/hooks.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "sh \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh\""
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Verify the hook runs and prints the line**

Run: `sh hooks/session-start.sh`
Expected: prints the `[backlog] …` reminder line, exit 0.

- [ ] **Step 5: Commit**

```bash
git add hooks/
git commit -m "feat: SessionStart hook keeps backlog reflex alive (E2)"
```

---

### Task 11: README + install smoke test

**Files:**

- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# backlog — Claude Code plugin

Единый надёжный маршрут для отложенных задач. Когда задача откладывается за
пределы текущего плана, Claude записывает её в `docs/backlogs/` проекта в
фиксированном формате; команды позволяют смотреть и вести статус. **Исполнения
нет** — работу делает твой обычный workflow.

## Поля записи

`id`, `title`, `priority` (`low`/`medium`/`high`), `status` (`open`/`done`/
`cancelled`), `created`, `updated` (даты ведёт движок автоматически).

## Команды

- `/backlog:list [--all] [--sort date] [--priority high]` — список (по умолчанию open).
- `/backlog:add <запрос>` — добавить вручную.
- `/backlog:done <id>` / `/backlog:cancel <id>` — статус.

## Хранилище

Файлы `docs/backlogs/<id>-<slug>.md` в корне git-репо проекта. Человекочитаемо,
версионируется, грепается.

## Ограничения

- Параллельные сессии могут сгенерировать одинаковый `id` (редко для личного
  использования); текстовый формат делает merge-конфликт разрешимым вручную.
- Движок требует `python3` (stdlib, без зависимостей).

## Тесты

```bash
python3 -m unittest discover -s tests -v
```
````

- [ ] **Step 2: Full engine test run (regression gate)**

Run: `python3 -m unittest discover -s tests -v`
Expected: entire suite PASS.

- [ ] **Step 3: End-to-end smoke test in a throwaway repo**

```bash
T=$(mktemp -d); ( cd "$T" && git init -q )
python3 scripts/backlog.py --dir "$T/docs/backlogs" add --title "Пробная задача" --priority high --body "контекст: file.py:10"
python3 scripts/backlog.py --dir "$T/docs/backlogs" list
python3 scripts/backlog.py --dir "$T/docs/backlogs" done 1
python3 scripts/backlog.py --dir "$T/docs/backlogs" list --status all
ls "$T/docs/backlogs"
rm -rf "$T"
```

Expected: add prints `1`; first list shows the high-priority open task; `done 1`
prints `#1 → done`; `list --status all` shows it as done; the dir contains
`1-пробная-задача.md`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README and install/smoke instructions"
```

---

## Final Verification (after all tasks)

- [ ] `python3 -m unittest discover -s tests -v` — full suite green.
- [ ] Smoke test (Task 11 Step 3) passes.
- [ ] Plugin loads: install locally (`/plugin marketplace add /Users/alex/Documents/backlog-skill` then enable), run `/backlog:list` in a project — confirms manifest, command wiring, and `${CLAUDE_PLUGIN_ROOT}` resolution.
- [ ] New session shows the `[backlog]` reminder line (confirms the SessionStart hook is registered).
