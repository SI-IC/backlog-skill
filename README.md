# backlog — Claude Code plugin

Единый надёжный маршрут для отложенных задач. Когда задача откладывается за
пределы текущего плана, Claude записывает её в `docs/backlogs/` проекта в
фиксированном формате; команды позволяют смотреть и вести статус. **Исполнения
нет** — работу делает твой обычный workflow.

## Поля записи

`id`, `title`, `priority` (`low`/`medium`/`high`), `status` (`open`/`done`/
`cancelled`), `created`, `updated` (даты ведёт движок автоматически).

## Команды

- `/backlog:list [--all] [--sort date] [--priority high]` — список (по умолчанию open).
- `/backlog:add <запрос>` — добавить вручную.
- `/backlog:done <id>` / `/backlog:cancel <id>` — статус.

## Хранилище

Файлы `docs/backlogs/<id>-<slug>.md` в корне git-репо проекта. Человекочитаемо,
версионируется, грепается.

## Ограничения

- Параллельные сессии могут сгенерировать одинаковый `id` (редко для личного
  использования); текстовый формат делает merge-конфликт разрешимым вручную.
- Движок требует `python3` (stdlib, без зависимостей).

## Тесты

```bash
python3 -m unittest discover -s tests -v   # движок (47 тестов)
sh hooks/session-start.test.sh             # SessionStart-хук
```
