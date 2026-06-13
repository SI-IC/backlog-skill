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
FIELD_ORDER = ("id", "title", "priority", "status", "created", "updated", "source")
ANYLEVEL_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
ROOT_DUMP_FILES = (
    "TODO.md",
    "TODOS.md",
    "NOTES.md",
    "BACKLOG.md",
    "ROADMAP.md",
    "FIXME.md",
)
SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "target",
    ".next",
    ".venv",
    "venv",
    "__pycache__",
}


def slugify(title, maxlen=50):
    s = title.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    s = s[:maxlen].strip("-")
    return s or "task"


def sanitize_oneline(s):
    """Collapse newlines/tabs/control chars to single spaces.

    Frontmatter values must stay on one line; a multi-line title (pasted text
    or hostile input) would otherwise inject fake meta fields or break the
    format and crash listing. Body is exempt — it lives below the frontmatter.
    """
    s = "".join(" " if ord(ch) < 32 else ch for ch in s)
    return re.sub(r" +", " ", s).strip()


def serialize_entry(meta, body):
    lines = ["---"]
    for k in FIELD_ORDER:
        if k in meta:
            v = str(meta[k])
            if "\n" in v or "\r" in v:
                raise ValueError(f"newline in frontmatter field {k!r}")
            lines.append(f"{k}: {v}")
    fm = "\n".join(lines) + "\n---\n"
    body = (body or "").strip("\n")
    return fm + (body + "\n" if body else "\n")


def parse_entry(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter")
    meta = {}
    i = 1
    closed = False
    while i < len(lines):
        if lines[i].strip() == "---":
            closed = True
            i += 1
            break
        line = lines[i]
        if line.strip():
            if ":" not in line:
                raise ValueError(f"bad meta line: {line!r}")
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
        i += 1
    if not closed:
        raise ValueError("malformed frontmatter")
    if "id" in meta:
        meta["id"] = int(meta["id"])
    body = "\n".join(lines[i:]).lstrip("\n")
    return {"meta": meta, "body": body}


def next_id(dirpath):
    if not os.path.isdir(dirpath):
        return 1
    max_id = 0
    # Consider both the filename prefix (covers malformed files we cannot parse)
    # and the frontmatter id (covers files renamed away from their id) so the
    # two sources of truth can never let an id be reused.
    for name in os.listdir(dirpath):
        if not name.endswith(".md"):
            continue
        m = re.match(r"(\d+)-", name)
        if m:
            max_id = max(max_id, int(m.group(1)))
    for e in load_all(dirpath):
        eid = e["meta"].get("id")
        if isinstance(eid, int):
            max_id = max(max_id, eid)
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
            with open(path, encoding="utf-8-sig") as f:
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


def iso(dt):
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


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


def age(created_str, now):
    if not created_str:
        return "?"
    created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
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
        entries.sort(
            key=lambda e: (
                PRIORITY_ORDER.get(e["meta"].get("priority"), 9),
                e["meta"].get("created", ""),
            )
        )
    else:
        entries.sort(key=lambda e: e["meta"].get("created", ""))
    if not entries:
        return "Бэклог пуст (нет задач по текущему фильтру)."
    rows = [("#", "PRI", "STATUS", "AGE", "TITLE")]
    for e in entries:
        m = e["meta"]
        rows.append(
            (
                str(m.get("id", "?")),
                m.get("priority", "?"),
                m.get("status", "?"),
                age(m.get("created"), now),
                m.get("title", ""),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    out = []
    for r in rows:
        cols = "  ".join(r[i].ljust(widths[i]) for i in range(4))
        out.append(f"{cols}  {r[4]}")
    return "\n".join(out)


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


UPDATABLE_FIELDS = ("title", "priority")


def cmd_update(dirpath, id_, fields, body, now):
    # Whitelist: id / status / created / updated are engine-managed and must
    # not be rewritten through update.
    bad = set(fields) - set(UPDATABLE_FIELDS)
    if bad:
        raise ValueError(f"cannot update fields: {sorted(bad)}")
    if "priority" in fields and fields["priority"] not in PRIORITIES:
        raise ValueError(f"invalid priority: {fields['priority']}")
    e = find_entry(dirpath, id_)
    if not e:
        raise KeyError(f"no backlog item with id {id_}")
    if "title" in fields:
        fields = {**fields, "title": sanitize_oneline(fields["title"])}
    e["meta"].update(fields)
    if body is not None:
        e["body"] = body
    e["meta"]["updated"] = iso(now)
    _write_entry(e)


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


def main(argv=None):
    p = argparse.ArgumentParser(prog="backlog")
    p.add_argument("--dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add")
    pa.add_argument("--title", required=True)
    pa.add_argument("--priority", default="medium")
    pa.add_argument("--body", default=None)
    pa.add_argument("--source", default=None)

    pl = sub.add_parser("list")
    pl.add_argument("--status", default="open")
    pl.add_argument("--all", action="store_true")
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

    sub.add_parser("scan-targets")

    args = p.parse_args(argv)
    dirpath = args.dir or resolve_dir()
    now = datetime.now(timezone.utc)
    try:
        if args.cmd == "add":
            body = args.body
            if body is None and not sys.stdin.isatty():
                body = sys.stdin.read()
            print(
                cmd_add(
                    dirpath,
                    args.title,
                    args.priority,
                    body or "",
                    now,
                    source=args.source,
                )
            )
        elif args.cmd == "scan-targets":
            for target in scan_targets():
                print(target)
        elif args.cmd == "list":
            status = "all" if args.all else args.status
            print(cmd_list(dirpath, status, args.sort, args.priority, now))
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
