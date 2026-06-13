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


def iso(dt):
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def cmd_add(dirpath, title, priority, body, now):
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    os.makedirs(dirpath, exist_ok=True)
    nid = next_id(dirpath)
    ts = iso(now)
    meta = {
        "id": nid,
        "title": title,
        "priority": priority,
        "status": "open",
        "created": ts,
        "updated": ts,
    }
    path = os.path.join(dirpath, f"{nid}-{slugify(title)}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(serialize_entry(meta, body))
    return nid


def age(created_str, now):
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
