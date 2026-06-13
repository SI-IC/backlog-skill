import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import backlog  # noqa: E402

NOW = datetime(2026, 6, 13, 12, 30, 0, tzinfo=timezone.utc)
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "backlog.py")


class TestSlugify(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(backlog.slugify("Add user validation"), "add-user-validation")

    def test_cyrillic_preserved(self):
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
            "id": 5,
            "title": "Hello",
            "priority": "medium",
            "status": "open",
            "created": "2026-06-13T12:30:00Z",
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
        text = backlog.serialize_entry({"id": 1, "title": "t"}, "before\n---\nafter\n")
        parsed = backlog.parse_entry(text)
        self.assertIn("---", parsed["body"])

    def test_missing_frontmatter_raises(self):
        with self.assertRaises(ValueError):
            backlog.parse_entry("no frontmatter here")


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
        self.assertEqual(backlog.next_id(self.tmp), 5)

    def test_load_all_skips_malformed(self):
        self._write(
            "1-ok.md",
            backlog.serialize_entry({"id": 1, "title": "ok", "status": "open"}, "body"),
        )
        self._write("2-bad.md", "this is not valid frontmatter")
        entries = backlog.load_all(self.tmp)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["meta"]["id"], 1)

    def test_load_all_empty_dir(self):
        self.assertEqual(backlog.load_all(self.tmp), [])


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


class TestList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_message(self):
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("пуст", out.lower())

    def test_default_hides_done_and_cancelled(self):
        backlog.cmd_add(self.tmp, "open one", "medium", "", NOW)
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
        backlog.cmd_add(self.tmp, "low task", "low", "", NOW)
        backlog.cmd_add(self.tmp, "high newer", "high", "", NOW)
        older = backlog.serialize_entry(
            {
                "id": 99,
                "title": "high older",
                "priority": "high",
                "status": "open",
                "created": "2026-06-01T00:00:00Z",
                "updated": "2026-06-01T00:00:00Z",
            },
            "",
        )
        with open(
            os.path.join(self.tmp, "99-high-older.md"), "w", encoding="utf-8"
        ) as f:
            f.write(older)
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertLess(out.index("high older"), out.index("high newer"))
        self.assertLess(out.index("high newer"), out.index("low task"))

    def test_age_days(self):
        created = NOW - timedelta(days=2)
        path = os.path.join(self.tmp, "1-x.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                backlog.serialize_entry(
                    {
                        "id": 1,
                        "title": "x",
                        "priority": "low",
                        "status": "open",
                        "created": backlog.iso(created),
                        "updated": backlog.iso(created),
                    },
                    "",
                )
            )
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("2d", out)


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
        self.assertEqual(e["meta"]["created"], "2026-06-13T12:30:00Z")

    def test_set_status_rejects_invalid(self):
        with self.assertRaises(ValueError):
            backlog.cmd_set_status(self.tmp, self.id, "wip", NOW)

    def test_set_status_missing_raises(self):
        with self.assertRaises(KeyError):
            backlog.cmd_set_status(self.tmp, 999, "done", NOW)

    def test_update_title_and_priority_bumps_updated(self):
        later = NOW + timedelta(hours=2)
        backlog.cmd_update(
            self.tmp, self.id, {"title": "New", "priority": "high"}, None, later
        )
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


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, SCRIPT, "--dir", self.tmp, *args],
            capture_output=True,
            text=True,
            input=stdin,
        )

    def test_add_then_list(self):
        r = self._run(
            "add", "--title", "CLI task", "--priority", "high", "--body", "ctx"
        )
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
        self.assertEqual(
            backlog.resolve_dir(sub), os.path.join(root, "docs", "backlogs")
        )

    def test_falls_back_to_cwd(self):
        plain = tempfile.mkdtemp()
        self.assertEqual(
            backlog.resolve_dir(plain), os.path.join(plain, "docs", "backlogs")
        )


if __name__ == "__main__":
    unittest.main()
