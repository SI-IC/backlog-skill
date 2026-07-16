#!/usr/bin/env python3
"""Backlog engine — owns the docs/backlogs file format. Stdlib only."""

import argparse
import base64
import json
import os
import re
import shlex
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
    entries = _filter_status(load_all(dirpath), status)
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


def _filter_status(entries, status):
    """Keep entries matching `status`; "all" keeps everything."""
    if status == "all":
        return entries
    return [e for e in entries if e["meta"].get("status") == status]


def cmd_count(dirpath, status="open"):
    """Number of backlog entries, filtered by status ("all" = every status)."""
    return len(_filter_status(load_all(dirpath), status))


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


# --- statusline integration ---------------------------------------------------
# A statusLine in Claude Code is a single command in settings.json. There is no
# plugin contribution point, so install/uninstall edit the user's settings.json
# and manage a self-contained wrapper script living in a STABLE config dir (not
# the versioned plugin cache, which vanishes on plugin update). The wrapper reads
# stdin once, delegates to any pre-existing command (inner), and appends a badge.

WRAPPER_MARKER = "BACKLOG_STATUSLINE_WRAPPER"
WRAPPER_NAME = "backlog-statusline.sh"


def _config_dir():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.expanduser("~"), ".claude")


def _wrapper_text(inner_cmd):
    """Render the self-contained POSIX-sh wrapper embedding `inner_cmd`."""
    inner = inner_cmd or ""
    inner_q = shlex.quote(inner)
    inner_b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    return f"""#!/bin/sh
# {WRAPPER_MARKER} — managed by the backlog plugin. Do not edit by hand.
# Reinstall: /backlog:statusline-install   Remove: /backlog:statusline-uninstall
# BACKLOG_INNER_B64:{inner_b64}
INNER={inner_q}
input=$(cat)
if [ -n "$INNER" ]; then
  if command -v timeout >/dev/null 2>&1; then
    out=$(printf '%s' "$input" | timeout 5 sh -c "$INNER")
  else
    out=$(printf '%s' "$input" | sh -c "$INNER")
  fi
  [ -n "$out" ] && printf '%s\\n' "$out"
fi
_bl_get() {{
  printf '%s' "$1" | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p' | head -n 1
}}
proj=$(_bl_get "$input" project_dir)
[ -n "$proj" ] || proj=$(_bl_get "$input" current_dir)
[ -n "$proj" ] || proj=$(_bl_get "$input" cwd)
[ -n "$proj" ] || exit 0
# Only absolute POSIX paths — a relative or Windows-style path would loop forever
# in the dirname walk below (dirname stabilises at "." and never reaches "/").
case "$proj" in
  /*) ;;
  *) exit 0 ;;
esac
root=$proj
d=$proj
while [ "$d" != "/" ]; do
  if [ -e "$d/.git" ]; then root=$d; break; fi
  d=$(dirname "$d")
done
dir="$root/docs/backlogs"
[ -d "$dir" ] || exit 0
# sub(/\\r$/) tolerates CRLF entries authored on Windows.
count=$(awk 'FNR==1{{fm=0}} {{sub(/\\r$/,"")}} /^---$/{{fm++; next}} fm==1 && /^status:[[:space:]]*open[[:space:]]*$/{{c++}} END{{print c+0}}' "$dir"/*.md 2>/dev/null)
if [ "${{count:-0}}" -gt 0 ]; then
  # Wrap the badge in an OSC 8 hyperlink so Ctrl/Cmd-click opens the backlog dir.
  # BEL-terminated (\\007) form — terminals without OSC 8 support drop the escape
  # and still show the plain badge. Percent-encode URI-breaking chars in the path.
  uri=$(printf '%s' "$dir" | sed 's/%/%25/g; s/ /%20/g; s/#/%23/g; s/?/%3F/g')
  printf '\\033]8;;file://%s\\007\\360\\237\\223\\213 %s\\033]8;;\\007\\n' "$uri" "$count"
fi
exit 0
"""


def _read_inner_from_wrapper(wrapper_path):
    """Recover the original (inner) command stored in the wrapper, or ""."""
    try:
        with open(wrapper_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("# BACKLOG_INNER_B64:"):
                    b64 = line.split(":", 1)[1].strip()
                    return base64.b64decode(b64).decode("utf-8") if b64 else ""
    except OSError:
        pass
    return ""


def _points_to_our_wrapper(cmd, wrapper_path):
    """True when a statusLine command already runs our managed wrapper."""
    if not cmd:
        return False
    if os.path.abspath(wrapper_path) in cmd:
        return True
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    for t in toks:
        p = os.path.expanduser(t)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    if WRAPPER_MARKER in f.read(512):
                        return True
            except OSError:
                pass
    return False


def _load_settings(settings_path):
    """Parse settings.json; ABORT (ValueError) on malformed JSON — never clobber."""
    if not os.path.exists(settings_path):
        return {}, None
    with open(settings_path, encoding="utf-8") as f:
        raw = f.read()
    if not raw.strip():
        return {}, raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{settings_path} is not valid JSON ({e}); left untouched — "
            "fix or back it up manually, then retry."
        )
    if not isinstance(data, dict):
        raise ValueError(f"{settings_path}: expected a JSON object at the root")
    return data, raw


def _write_private(path, text):
    """Write text with 0600 perms — settings.json/its backup may hold secrets."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _write_settings(settings_path, settings, prev_raw):
    # Backup first (recovery net), then write via a temp file + atomic rename so an
    # OOM-kill mid-write can never leave settings.json truncated/invalid.
    if prev_raw is not None:
        _write_private(settings_path + ".bak-backlog", prev_raw)
    tmp = settings_path + ".tmp-backlog"
    _write_private(tmp, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, settings_path)


def statusline_install(config_dir=None):
    config_dir = config_dir or _config_dir()
    settings_path = os.path.join(config_dir, "settings.json")
    wrapper_path = os.path.join(config_dir, WRAPPER_NAME)

    settings, prev_raw = _load_settings(settings_path)  # aborts on bad JSON first

    current = settings.get("statusLine")
    inner = ""
    already = False
    if isinstance(current, dict) and current.get("type") == "command":
        cmd = current.get("command", "")
        if _points_to_our_wrapper(cmd, wrapper_path):
            already = True
        else:
            inner = cmd

    lost_inner = False
    if already:
        if os.path.isfile(wrapper_path):
            # Idempotent: keep the ORIGINAL inner we stored earlier, never re-wrap.
            inner = _read_inner_from_wrapper(wrapper_path)
        else:
            # settings.json points at a wrapper that was deleted by hand — the
            # statusLine is already broken and the wrapped command is unrecoverable.
            lost_inner = True
            inner = ""

    os.makedirs(config_dir, exist_ok=True)
    with open(wrapper_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_wrapper_text(inner))
    os.chmod(wrapper_path, 0o700)

    settings["statusLine"] = {"type": "command", "command": wrapper_path}
    _write_settings(settings_path, settings, prev_raw)

    if already:
        if lost_inner:
            return (
                "Wrapper был удалён — пересоздал; statusLine снова показывает бэйдж. "
                "Прежняя обёрнутая команда (если была) не восстановлена.\n"
                f"wrapper: {wrapper_path}"
            )
        return f"statusLine уже подключён к бэклогу; wrapper обновлён.\nwrapper: {wrapper_path}"
    if inner:
        return (
            "Бэйдж бэклога добавлен поверх существующего statusLine "
            "(старая команда сохранена как inner).\n"
            f"wrapper: {wrapper_path}\n"
            f"бэкап настроек: {settings_path}.bak-backlog"
        )
    return (
        "statusLine создан с бэйджем бэклога (📋 N) — кликабельный: Ctrl/Cmd+click "
        "открывает docs/backlogs.\n"
        f"wrapper: {wrapper_path}"
    )


def statusline_uninstall(config_dir=None):
    config_dir = config_dir or _config_dir()
    settings_path = os.path.join(config_dir, "settings.json")
    wrapper_path = os.path.join(config_dir, WRAPPER_NAME)

    if not os.path.exists(settings_path):
        removed = _rm(wrapper_path)
        return "settings.json не найден; " + (
            "wrapper удалён." if removed else "откатывать нечего."
        )

    settings, prev_raw = _load_settings(settings_path)
    current = settings.get("statusLine")
    ours = (
        isinstance(current, dict)
        and current.get("type") == "command"
        and _points_to_our_wrapper(current.get("command", ""), wrapper_path)
    )
    if not ours:
        return "Текущий statusLine не управляется бэклогом — оставляю как есть."

    inner = _read_inner_from_wrapper(wrapper_path)
    if inner:
        settings["statusLine"] = {"type": "command", "command": inner}
    else:
        settings.pop("statusLine", None)
    _write_settings(settings_path, settings, prev_raw)
    _rm(wrapper_path)

    if inner:
        return "Бэйдж бэклога убран; восстановлена прежняя statusLine-команда."
    return "Бэйдж бэклога убран; statusLine удалён (своей команды у тебя не было)."


def _rm(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


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

    pc = sub.add_parser("count")
    pc.add_argument("--status", default="open")
    pc.add_argument("--all", action="store_true")

    ps = sub.add_parser("statusline")
    ps.add_argument("action", choices=("install", "uninstall"))

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
        elif args.cmd == "count":
            status = "all" if args.all else args.status
            print(cmd_count(dirpath, status))
        elif args.cmd == "statusline":
            if args.action == "install":
                print(statusline_install())
            else:
                print(statusline_uninstall())
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
