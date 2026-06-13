# backlog

Менеджер бэклога проекта для Claude Code — даёт Claude надёжный рефлекс
записывать отложенные задачи в `docs/backlogs/` проекта в фиксированном формате.
Файловое хранилище, в репозитории, **без движка исполнения**.

## Что делает

Закрывает дыру: у Claude Code нет единого подхода к отложенным задачам — они
оседают то в памяти, то в случайных файлах, то теряются. Плагин даёт один маршрут:

1. **Capture** — при явном деферрале («потом / отложим / вне scope этого PR / TODO
   на будущее») Claude автоматически пишет запись с достаточным контекстом и
   сообщает «записал в бэклог #N». Только за пределами текущего открытого плана —
   задачи внутри scope плана остаются в его трекинге.
2. **Discovery** — Claude знает, где бэклог и как его читать; перед взятием задачи
   в работу перечитывает реальный код (защита от протухания).
3. **Management** — просмотр с сортировкой и ведение статуса через команды.

Исполнение задач — НЕ в плагине: взятую из бэклога задачу делает твой обычный
workflow, плагин лишь направляет к хранилищу.

Полные правила рефлекса: [`skills/backlog/SKILL.md`](skills/backlog/SKILL.md).

## Установка

На любой машине с Claude Code:

```bash
claude plugin marketplace add SI-IC/backlog-skill
claude plugin install backlog@backlog
```

Первая команда регистрирует репозиторий как marketplace Claude Code, вторая ставит
плагин `backlog` из него (`<плагин>@<marketplace>`). Per-project конфиг не нужен —
папка `docs/backlogs/` создаётся в проекте при первой записи.

## Использование

| Команда                                     | Действие                                                            |
| ------------------------------------------- | ------------------------------------------------------------------- |
| `/backlog:list`                             | список задач (по умолчанию только `open`, сортировка важность→дата) |
| `/backlog:list --all`                       | включая `done` / `cancelled`                                        |
| `/backlog:list --sort date --priority high` | флаги прокидываются в движок                                        |
| `/backlog:add <запрос>`                     | добавить вручную                                                    |
| `/backlog:done <id>`                        | пометить выполненной                                                |
| `/backlog:cancel <id>`                      | отменить                                                            |
| `/backlog:migrate`                          | собрать разрозненные/легаси TODO из доков и памяти проекта в бэклог |

Автоматический capture-рефлекс работает без команд — Claude сам кладёт явные
деферралы в бэклог. SessionStart-хук печатает короткое напоминание в начале каждой
сессии, чтобы рефлекс не «забывался».

### Формат записи

Один файл на задачу: `docs/backlogs/<id>-<slug>.md`. Плоский frontmatter:

```markdown
---
id: 5
title: Вынести валидацию формы в useFormValidation
priority: medium
status: open
created: 2026-06-13T12:30:00Z
updated: 2026-06-13T12:30:00Z
---

<body: достаточный контекст — что сделать, почему, где (ссылки file:line)>
```

- `priority`: `low` / `medium` / `high`
- `status`: `open` / `done` / `cancelled`
- `created` / `updated` — UTC ISO 8601, ведутся движком автоматически.

## Обновление

**Мейнтейнер** (при правке плагина в этом репозитории):

1. Правишь `SKILL.md` / `backlog.py` / команды / что угодно.
2. **Бампишь `version` в [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json)**
   (patch-инкремент — `0.1.2` → `0.1.3`). **Без бампа версии Claude Code не обновит
   закэшированную копию плагина на машинах-потребителях** — это обязательный шаг.
3. Commit + push.

**Потребитель.** В отличие от `main-skill`, у `backlog` нет авто-апдейта: его
SessionStart-хук только печатает напоминание и НЕ ходит в remote. Поэтому
обновление ручное:

```bash
claude plugin update backlog@backlog
```

(подтянет новую версию только если она бампнута). Если marketplace-метаданные
устарели — сначала `claude plugin marketplace update backlog`, затем update.

> Если захочется авто-апдейт как в `main-skill` — в `hooks/session-start.sh`
> можно добавить дешёвый `git ls-remote` + `claude plugin update` на старте сессии.
> Сейчас сознательно не сделано, чтобы хук оставался нулевой стоимости.

## Ограничения

- Параллельные сессии могут сгенерировать одинаковый `id` (редко для личного
  использования); `cmd_add` использует exclusive-create, так что молчаливой
  перезаписи файла не будет, а текстовый формат делает merge-конфликт разрешимым.
- Движок требует `python3` (stdlib, без зависимостей).

## Тесты

```bash
python3 -m unittest discover -s tests -v   # движок (57 тестов)
sh hooks/session-start.test.sh             # SessionStart-хук
```

## Структура

```
backlog-skill/
├── .claude-plugin/
│   ├── plugin.json         # манифест плагина (version бампается при апдейтах)
│   └── marketplace.json    # манифест marketplace (делает репо устанавливаемым)
├── skills/
│   ├── backlog/
│   │   └── SKILL.md        # forcing function: capture + plan-boundary + discovery
│   └── migrate/
│       └── SKILL.md        # миграция: детекция + импорт + аккуратное удаление
├── commands/
│   ├── list.md  add.md  done.md  cancel.md  migrate.md
├── scripts/
│   └── backlog.py          # CLI-движок (Python stdlib): формат, id, сортировка, scan-targets
├── hooks/
│   ├── hooks.json          # регистрация SessionStart-хука
│   ├── session-start.sh    # печатает напоминание о рефлексе
│   └── session-start.test.sh
├── tests/
│   └── test_backlog.py     # unittest-сьют движка (57 тестов)
├── docs/
│   └── superpowers/        # спека и план реализации
└── README.md
```
