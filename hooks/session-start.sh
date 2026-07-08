#!/bin/sh
# SessionStart hook for the backlog plugin.
# Prints one reminder line so Claude keeps the narrow deferral reflex every session.
# Output goes to stdout and is injected into context (non-blocking).
echo "[backlog] Не пиши в бэклог сам по любому расхождению с задачей. Запись только: (1) юзер явно попросил; (2) по ходу заметил НЕсвязанный баг или побочную задачу вне scope — спроси «записать в бэклог?» и запиши после согласия; (3) фоновая/автономная сессия и нужно решение юзера, а спросить некого. Движок: scripts/backlog.py, хранилище: docs/backlogs/."
