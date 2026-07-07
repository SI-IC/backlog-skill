---
description: Отменить задачу бэклога по её id (статус cancelled).
allowed-tools: Bash(python3:*)
---

Ниже — ответ движка. Пользователь этот сырой вывод НЕ видит: передай его сам одной
строкой (напр. «#N → cancelled» или текст ошибки движка). Не пиши «см. выше».

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py" cancel $ARGUMENTS 2>&1 || true`
