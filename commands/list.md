---
description: Показать бэклог проекта (по умолчанию open, сортировка важность→дата). Аргументы прокидываются в backlog.py list (напр. --all, --sort date, --priority high).
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" list $ARGUMENTS`
