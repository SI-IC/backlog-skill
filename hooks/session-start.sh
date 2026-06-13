#!/bin/sh
# SessionStart hook for the backlog plugin.
# Prints one reminder line so Claude keeps the deferral reflex alive every session.
# Output goes to stdout and is injected into context (non-blocking).
echo "[backlog] Если задача откладывается ЗА ПРЕДЕЛЫ текущего плана — не бросай её в память/случайный файл, запиши через скилл backlog (движок: scripts/backlog.py, хранилище: docs/backlogs/). Деферрал внутри scope открытого плана остаётся в трекинге плана, не в бэклоге."
