---
description: Пометить задачу бэклога выполненной по её id.
allowed-tools: Bash(python3:*)
---

Ниже — ответ движка. Пользователь этот сырой вывод НЕ видит: передай его сам одной
строкой (напр. «#N → done» или текст ошибки движка). Не пиши «см. выше».

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" done $ARGUMENTS 2>&1 || true`
