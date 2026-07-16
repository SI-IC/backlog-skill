import json
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

    def test_all_flag_shows_done(self):
        self._run("add", "--title", "Done one", "--priority", "low", "--body", "x")
        self._run("done", "1")
        self.assertNotIn("Done one", self._run("list").stdout)
        self.assertIn("Done one", self._run("list", "--all").stdout)

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


class TestStatuslineWrapper(unittest.TestCase):
    """Run the generated POSIX-sh wrapper through /bin/sh and inspect its bytes."""

    OSC = b"\x1b]8;;"  # OSC 8 hyperlink introducer
    BEL = b"\x07"  # BEL terminator
    BADGE = b"\xf0\x9f\x93\x8b"  # 📋 (U+1F4CB) in UTF-8

    def _run(self, project_dir):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        os.makedirs(os.path.join(project_dir, "docs", "backlogs"), exist_ok=True)
        wrapper = os.path.join(root, "wrapper.sh")
        with open(wrapper, "w", encoding="utf-8", newline="\n") as f:
            f.write(backlog._wrapper_text(""))
        os.chmod(wrapper, 0o700)
        payload = json.dumps({"project_dir": project_dir}).encode("utf-8")
        return subprocess.run(
            ["sh", wrapper], input=payload, capture_output=True
        ).stdout

    def _seed_open(self, project_dir, n=1):
        d = os.path.join(project_dir, "docs", "backlogs")
        os.makedirs(d, exist_ok=True)
        for i in range(1, n + 1):
            with open(os.path.join(d, f"{i}-x.md"), "w", encoding="utf-8") as f:
                f.write(f"---\nid: {i}\ntitle: x\npriority: low\nstatus: open\n---\nb\n")

    def test_badge_wrapped_in_osc8_hyperlink(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        self._seed_open(root, 2)
        out = self._run(root)
        target = os.path.join(root, "docs", "backlogs").encode("utf-8")
        # Opening sequence: ESC]8;;file://<dir>BEL, then the badge + count.
        self.assertIn(self.OSC + b"file://" + target + self.BEL, out)
        self.assertIn(self.BADGE + b" 2", out)
        # Closing sequence: ESC]8;;BEL terminates the hyperlink.
        self.assertTrue(out.rstrip(b"\n").endswith(self.OSC + self.BEL))

    def test_path_with_space_is_percent_encoded(self):
        # A space in the path would break the OSC 8 URI unless encoded to %20.
        root = tempfile.mkdtemp(prefix="a b ")
        os.makedirs(os.path.join(root, ".git"))
        self._seed_open(root, 1)
        out = self._run(root)
        uri = os.path.join(root, "docs", "backlogs").replace(" ", "%20")
        self.assertIn(b"file://" + uri.encode("utf-8") + self.BEL, out)
        # No raw space must survive inside the URI segment.
        seg = out.split(b"file://", 1)[1].split(self.BEL, 1)[0]
        self.assertNotIn(b" ", seg)

    def test_no_badge_when_zero_open(self):
        # Empty state: no open tasks → no badge and no escape sequence at all.
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        os.makedirs(os.path.join(root, "docs", "backlogs"))
        out = self._run(root)
        self.assertNotIn(self.OSC, out)
        self.assertNotIn(self.BADGE, out)


class TestHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_newline_title_no_field_injection(self):
        nid = backlog.cmd_add(self.tmp, "x\nstatus: done\nevil: yes", "low", "b", NOW)
        e = backlog.find_entry(self.tmp, nid)
        self.assertEqual(e["meta"]["status"], "open")
        self.assertNotIn("evil", e["meta"])
        self.assertNotIn("\n", e["meta"]["title"])

    def test_injected_delimiter_does_not_break_format(self):
        nid = backlog.cmd_add(self.tmp, "a\n---\ntrailer: x", "low", "", NOW)
        out = backlog.cmd_list(self.tmp, now=NOW)  # must not raise
        self.assertIn(str(nid), out)
        self.assertIn("created", backlog.find_entry(self.tmp, nid)["meta"])

    def test_list_survives_missing_created(self):
        with open(os.path.join(self.tmp, "1-x.md"), "w", encoding="utf-8") as f:
            f.write("---\nid: 1\ntitle: x\npriority: low\nstatus: open\n---\nb\n")
        out = backlog.cmd_list(self.tmp, now=NOW)
        self.assertIn("x", out)

    def test_update_rejects_engine_fields(self):
        nid = backlog.cmd_add(self.tmp, "t", "low", "", NOW)
        for bad in ({"id": 9}, {"status": "done"}, {"created": "x"}):
            with self.assertRaises(ValueError):
                backlog.cmd_update(self.tmp, nid, bad, None, NOW)

    def test_serialize_rejects_newline_field(self):
        with self.assertRaises(ValueError):
            backlog.serialize_entry({"id": 1, "title": "a\nb"}, "")

    def test_parse_crlf(self):
        parsed = backlog.parse_entry("---\r\nid: 1\r\ntitle: t\r\n---\r\nbody\r\n")
        self.assertEqual(parsed["meta"]["id"], 1)
        self.assertEqual(parsed["meta"]["title"], "t")

    def test_next_id_reads_frontmatter_id(self):
        with open(os.path.join(self.tmp, "2-x.md"), "w", encoding="utf-8") as f:
            f.write(
                backlog.serialize_entry({"id": 7, "title": "x", "status": "open"}, "")
            )
        self.assertEqual(backlog.next_id(self.tmp), 8)

    def test_add_does_not_overwrite_existing(self):
        backlog.cmd_add(self.tmp, "dup", "low", "first", NOW)
        nid2 = backlog.cmd_add(self.tmp, "dup", "low", "second", NOW)
        self.assertEqual(nid2, 2)
        self.assertEqual(backlog.find_entry(self.tmp, 1)["body"].strip(), "first")

    def test_resolve_dir_worktree_git_file(self):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, ".git"), "w") as f:
            f.write("gitdir: /somewhere\n")
        sub = os.path.join(root, "a")
        os.makedirs(sub)
        self.assertEqual(
            backlog.resolve_dir(sub), os.path.join(root, "docs", "backlogs")
        )


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
        names = [
            os.path.basename(p) for p in backlog.scan_targets(self.root, self.home)
        ]
        self.assertIn("MEMORY.md", names)
        self.assertIn("fact.md", names)

    def test_missing_memory_dir_no_error(self):
        self.assertIsInstance(backlog.scan_targets(self.root, self.home), list)


class TestSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_add_with_source_writes_field(self):
        nid = backlog.cmd_add(self.tmp, "t", "low", "body", NOW, source="CLAUDE.md")
        self.assertEqual(
            backlog.find_entry(self.tmp, nid)["meta"]["source"], "CLAUDE.md"
        )

    def test_add_without_source_has_no_field(self):
        nid = backlog.cmd_add(self.tmp, "t", "low", "body", NOW)
        self.assertNotIn("source", backlog.find_entry(self.tmp, nid)["meta"])

    def test_source_round_trips(self):
        text = backlog.serialize_entry(
            {"id": 1, "title": "t", "source": "docs/x.md"}, "b"
        )
        self.assertIn("source: docs/x.md", text)
        self.assertEqual(backlog.parse_entry(text)["meta"]["source"], "docs/x.md")

    def test_add_source_via_cli(self):
        r = subprocess.run(
            [
                sys.executable,
                SCRIPT,
                "--dir",
                self.tmp,
                "add",
                "--title",
                "t",
                "--priority",
                "low",
                "--source",
                "CLAUDE.md",
                "--body",
                "b",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        r2 = subprocess.run(
            [sys.executable, SCRIPT, "--dir", self.tmp, "show", "1"],
            capture_output=True,
            text=True,
        )
        self.assertIn("source: CLAUDE.md", r2.stdout)


class TestScanTargetsCLI(unittest.TestCase):
    def test_scan_targets_cli_lists_files(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        with open(os.path.join(root, "CLAUDE.md"), "w") as f:
            f.write("x")
        r = subprocess.run(
            [sys.executable, SCRIPT, "scan-targets"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("CLAUDE.md", r.stdout)


class TestCommandGuardrails(unittest.TestCase):
    """Regress the invisible-output bug: `!`-inline command output is NOT shown to
    the user, so the command file must (a) surface engine errors instead of
    swallowing them on non-zero exit, and (b) for `list`, force the model to render
    the backlog itself and never claim it was "shown above"."""

    CMD_DIR = os.path.join(os.path.dirname(__file__), "..", "commands")

    def _read(self, name):
        with open(os.path.join(self.CMD_DIR, name), encoding="utf-8") as f:
            return f.read()

    def test_inline_commands_surface_errors(self):
        # `2>&1 || true` keeps stderr text and forces exit 0 so Claude Code injects
        # the output even when the engine exits non-zero (e.g. bad id).
        for name in ("list.md", "done.md", "cancel.md"):
            body = self._read(name)
            self.assertIn("2>&1 || true", body, f"{name} must surface engine errors")

    def test_list_forbids_shown_above(self):
        body = self._read("list.md")
        self.assertIn("показан выше", body)  # the forbidden phrase, called out
        self.assertRegex(body, r"НИКОГДА не пиши")

    def test_empty_backlog_reported_without_table(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".git"))
            r = subprocess.run(
                [sys.executable, SCRIPT, "list"],
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("Бэклог пуст", r.stdout)

    def test_bad_id_error_goes_to_stderr_nonzero(self):
        # Engine contract the command relies on: error → stderr + exit 1.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".git"))
            r = subprocess.run(
                [sys.executable, SCRIPT, "cancel", "99"],
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("error", r.stderr)


class TestCount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_is_zero(self):
        self.assertEqual(backlog.cmd_count(self.tmp), 0)

    def test_counts_only_open_by_default(self):
        backlog.cmd_add(self.tmp, "a", "high", "", NOW)
        backlog.cmd_add(self.tmp, "b", "low", "", NOW)
        c = backlog.cmd_add(self.tmp, "c", "low", "", NOW)
        backlog.cmd_set_status(self.tmp, c, "done", NOW)
        self.assertEqual(backlog.cmd_count(self.tmp), 2)

    def test_status_all_counts_everything(self):
        backlog.cmd_add(self.tmp, "a", "high", "", NOW)
        c = backlog.cmd_add(self.tmp, "c", "low", "", NOW)
        backlog.cmd_set_status(self.tmp, c, "cancelled", NOW)
        self.assertEqual(backlog.cmd_count(self.tmp, status="all"), 2)

    def test_cli_prints_integer(self):
        backlog.cmd_add(self.tmp, "a", "high", "", NOW)
        r = subprocess.run(
            [sys.executable, SCRIPT, "--dir", self.tmp, "count"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "1")


class TestStatuslineInstall(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.settings = os.path.join(self.cfg, "settings.json")
        self.wrapper = os.path.join(self.cfg, "backlog-statusline.sh")

    def _write_settings(self, obj_or_text):
        with open(self.settings, "w", encoding="utf-8") as f:
            if isinstance(obj_or_text, str):
                f.write(obj_or_text)
            else:
                json.dump(obj_or_text, f)

    def _read_settings(self):
        with open(self.settings, encoding="utf-8") as f:
            return json.load(f)

    def test_fresh_install_creates_statusline(self):
        backlog.statusline_install(self.cfg)
        s = self._read_settings()
        self.assertEqual(s["statusLine"]["type"], "command")
        self.assertEqual(s["statusLine"]["command"], self.wrapper)
        self.assertTrue(os.path.isfile(self.wrapper))
        self.assertTrue(os.access(self.wrapper, os.X_OK))
        with open(self.wrapper, encoding="utf-8") as f:
            self.assertIn(backlog.WRAPPER_MARKER, f.read())

    def test_install_preserves_existing_command_as_inner(self):
        self._write_settings(
            {"statusLine": {"type": "command", "command": "jq -r '.model.display_name'"}}
        )
        backlog.statusline_install(self.cfg)
        s = self._read_settings()
        self.assertEqual(s["statusLine"]["command"], self.wrapper)
        self.assertEqual(
            backlog._read_inner_from_wrapper(self.wrapper), "jq -r '.model.display_name'"
        )

    def test_double_install_is_idempotent(self):
        self._write_settings(
            {"statusLine": {"type": "command", "command": "echo hi"}}
        )
        backlog.statusline_install(self.cfg)
        backlog.statusline_install(self.cfg)
        s = self._read_settings()
        self.assertEqual(s["statusLine"]["command"], self.wrapper)
        # inner must still be the ORIGINAL, never the wrapper itself
        self.assertEqual(backlog._read_inner_from_wrapper(self.wrapper), "echo hi")

    def test_install_aborts_on_invalid_json(self):
        self._write_settings('{ // a JSONC comment\n  "x": 1,\n}')
        with open(self.settings, encoding="utf-8") as f:
            before = f.read()
        with self.assertRaises(ValueError):
            backlog.statusline_install(self.cfg)
        with open(self.settings, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(self.wrapper))

    def test_install_backs_up_existing_settings(self):
        self._write_settings({"other": True})
        backlog.statusline_install(self.cfg)
        self.assertTrue(os.path.exists(self.settings + ".bak-backlog"))
        s = self._read_settings()
        self.assertTrue(s["other"])  # unrelated keys preserved

    def test_uninstall_restores_inner(self):
        self._write_settings(
            {"statusLine": {"type": "command", "command": "echo orig"}}
        )
        backlog.statusline_install(self.cfg)
        backlog.statusline_uninstall(self.cfg)
        s = self._read_settings()
        self.assertEqual(s["statusLine"], {"type": "command", "command": "echo orig"})
        self.assertFalse(os.path.exists(self.wrapper))

    def test_uninstall_removes_statusline_when_no_inner(self):
        backlog.statusline_install(self.cfg)
        backlog.statusline_uninstall(self.cfg)
        s = self._read_settings()
        self.assertNotIn("statusLine", s)
        self.assertFalse(os.path.exists(self.wrapper))

    def test_uninstall_leaves_foreign_statusline_untouched(self):
        self._write_settings(
            {"statusLine": {"type": "command", "command": "my-own-thing"}}
        )
        backlog.statusline_uninstall(self.cfg)
        s = self._read_settings()
        self.assertEqual(s["statusLine"]["command"], "my-own-thing")

    def test_uninstall_without_settings_is_safe_noop(self):
        # No settings.json at all, with and without an orphan wrapper present.
        msg = backlog.statusline_uninstall(self.cfg)
        self.assertIn("settings.json", msg)
        with open(self.wrapper, "w", encoding="utf-8") as f:
            f.write("orphan")
        backlog.statusline_uninstall(self.cfg)
        self.assertFalse(os.path.exists(self.wrapper))

    def test_backup_and_settings_are_private(self):
        self._write_settings({"env": {"SECRET": "x"}})
        backlog.statusline_install(self.cfg)
        for p in (self.settings, self.settings + ".bak-backlog"):
            mode = os.stat(p).st_mode & 0o777
            self.assertEqual(mode, 0o600, f"{p} must be 0600, got {oct(mode)}")


class TestStatuslineWrapperExecution(unittest.TestCase):
    """Run the generated wrapper as a real shell script with sample stdin JSON."""

    def _run_wrapper(self, wrapper_path, project_dir):
        payload = json.dumps({"workspace": {"project_dir": project_dir}})
        return subprocess.run(
            ["sh", wrapper_path],
            input=payload,
            capture_output=True,
            text=True,
        )

    def test_badge_and_inner_output(self):
        cfg = tempfile.mkdtemp()
        # inner echoes a marker line; wrapper must pass it through
        text = backlog._wrapper_text("echo INNERLINE")
        wp = os.path.join(cfg, "backlog-statusline.sh")
        with open(wp, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(wp, 0o755)
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, ".git"))
        bl = os.path.join(repo, "docs", "backlogs")
        backlog.cmd_add(bl, "one", "high", "", NOW)
        b = backlog.cmd_add(bl, "two", "low", "", NOW)
        backlog.cmd_add(bl, "three", "low", "", NOW)
        backlog.cmd_set_status(bl, b, "done", NOW)  # 2 open remain
        r = self._run_wrapper(wp, repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("INNERLINE", r.stdout)
        self.assertIn("📋 2", r.stdout)

    def test_degrade_to_empty_without_backlog_dir(self):
        cfg = tempfile.mkdtemp()
        text = backlog._wrapper_text("")  # no inner
        wp = os.path.join(cfg, "backlog-statusline.sh")
        with open(wp, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(wp, 0o755)
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, ".git"))  # no docs/backlogs
        r = self._run_wrapper(wp, repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("📋", r.stdout)

    def _wrapper_for(self, cfg):
        wp = os.path.join(cfg, "backlog-statusline.sh")
        with open(wp, "w", encoding="utf-8", newline="\n") as f:
            f.write(backlog._wrapper_text(""))
        os.chmod(wp, 0o755)
        return wp

    def _repo_with_open(self, n):
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, ".git"))
        bl = os.path.join(repo, "docs", "backlogs")
        for i in range(n):
            backlog.cmd_add(bl, f"t{i}", "medium", "", NOW)
        return repo

    def test_relative_project_dir_does_not_hang(self):
        # A relative path must degrade to empty fast, never loop in the dirname walk.
        wp = self._wrapper_for(tempfile.mkdtemp())
        payload = json.dumps({"workspace": {"project_dir": "relative/path"}})
        r = subprocess.run(
            ["sh", wp], input=payload, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("📋", r.stdout)

    def test_counts_crlf_frontmatter(self):
        # Entry files authored on Windows (CRLF) must still be counted.
        wp = self._wrapper_for(tempfile.mkdtemp())
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, ".git"))
        bl = os.path.join(repo, "docs", "backlogs")
        os.makedirs(bl)
        crlf = "---\nid: 1\ntitle: t\npriority: high\nstatus: open\n---\nbody\n"
        crlf = crlf.replace("\n", "\r\n")
        with open(os.path.join(bl, "1-t.md"), "w", encoding="utf-8", newline="") as f:
            f.write(crlf)
        r = subprocess.run(
            ["sh", wp],
            input=json.dumps({"workspace": {"project_dir": repo}}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("📋 1", r.stdout)

    def test_works_without_python3_in_path(self):
        # The wrapper must not depend on python3 at render time (many runtimes lack it).
        import shutil

        wp = self._wrapper_for(tempfile.mkdtemp())
        repo = self._repo_with_open(2)
        # Build a minimal PATH with exactly the tools the wrapper needs, no python3.
        bindir = tempfile.mkdtemp()
        needed = ["sh", "sed", "awk", "head", "cat", "dirname", "printf", "command"]
        for tool in needed:
            src = shutil.which(tool)
            if src:
                try:
                    os.symlink(src, os.path.join(bindir, tool))
                except OSError:
                    pass
        env = {"PATH": bindir}
        probe = subprocess.run(
            ["sh", "-c", "command -v python3 || echo NONE"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertIn("NONE", probe.stdout, "python3 leaked into the sandbox PATH")
        r = subprocess.run(
            ["sh", wp],
            input=json.dumps({"workspace": {"project_dir": repo}}),
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("📋 2", r.stdout)


class TestStatuslineCommandFiles(unittest.TestCase):
    CMD_DIR = os.path.join(os.path.dirname(__file__), "..", "commands")

    def test_command_files_exist_and_surface_output(self):
        for name in ("statusline-install.md", "statusline-uninstall.md"):
            path = os.path.join(self.CMD_DIR, name)
            self.assertTrue(os.path.isfile(path), f"{name} missing")
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn("2>&1 || true", body, f"{name} must surface engine errors")


if __name__ == "__main__":
    unittest.main()
