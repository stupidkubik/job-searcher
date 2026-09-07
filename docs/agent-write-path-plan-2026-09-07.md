# План: исправление write path и бутстрапа агента

Статус: **план работ** — 2026-09-07. Основание:
[`agent-ergonomics-analysis-2026-09-07.md`](agent-ergonomics-analysis-2026-09-07.md).
План описывает, что менять, в каком порядке и по какому критерию считать этап
закрытым. Он не заменяет [`AGENTS.md`](../AGENTS.md): контракт меняется только
теми коммитами, которые перечислены в этапах.

## 0. Свежие цифры и почему тянуть нельзя

Аудит считал метрики на checkout'е, отстающем от `origin/main` на 15 коммитов.
Пересчёт на актуальном `main` (2026-09-07, после `git pull`):

| Метрика | В аудите | Сейчас | Динамика |
|---|---:|---:|---|
| строк в `data/jobs.csv` | 394 | **409** | +15 |
| запросов в `requests/` | 137 | **148** | +11 |
| результатов в `results/` | 110 | **116** | +6 |
| **запросов без результата** | 27 | **32** | **+5** |
| результатов `status: conflict` | 12 | **13** | +1 |
| строк с пустым `original_url` | 267 | **281** | +14 |
| строк с placeholder-компанией | 25 | **26** | +1 |
| `not_started` в датасете | 338 (86%) | **348 (85%)** | — |

За 11 новых запросов агент получил 6 результатов. Доля «немых» операций растёт
быстрее, чем доля успешных: проблема не стабилизировалась, она масштабируется
вместе с темпом работы.

## 1. Принятые решения по серым зонам

Ниже — фиксация выбора по G-1…G-15 из аудита. Где план отходит от рекомендации
аудита, это помечено и обосновано.

| Зона | Решение | Отличие от аудита |
|---|---|---|
| G-1 язык | A: всё агентское (контракты и **все** сообщения об ошибках) — английский; человеческое (`profile.md`, `reports/`, CLI-вывод для человека) — русский | — |
| G-2 источник истины по полям | A: таблица генерируется из кода, тест-гвардия сверяет | — |
| G-3 как агент узнаёт об ошибке | A: всегда `results/<id>.json`; ретрай — только новый `operation_id`, `rejected` result immutable. Вариант B (`workflow_dispatch` dry-run) — парковка до подтверждения прав connector'а на dispatch | — |
| G-4 атомарность batch | A: разрешить `atomic: false` с per-child статусами. **Плюс**: жёсткий лимит 10 children для `atomic: true` и 100 для `atomic: false` | лимит зависит от режима, а не общий |
| G-5 fuzzy-дедуп | D: исключить placeholder-компании + отдать агенту read-only индекс | — |
| G-6 бутстрап | В1: генерируемые индексы в `data/index/` | — |
| G-7 пустой `original_url` | C: требовать при `first_party_verified=yes` (в `add` **и в `verify`** — сейчас `verify` не требует) + одноразовый backfill | добавлен `verify`: это дыра, которой в аудите нет |
| G-8 push race | A, но **не rebase, а повторное применение операции на свежем `main`** | rebase по `data/jobs.csv` даёт конфликты слияния; см. Э3 |
| G-9 разбиение `jobs.py` | B, отдельным последним этапом, **с явным предварительным условием**: сначала централизовать пути (`jobs.ROOT`/`CSV_PATH` патчатся тестами и runner'ом) | добавлено предусловие |
| G-10 тулинг | A: `pyproject.toml` + ruff + lint-шаг; mypy не включать | — |
| G-11 два Telegram-скрипта | B: оставить оба, задокументировать разделение | — |
| G-12 одноразовые миграции | A: перенести в `scripts/maintenance/` | — |
| G-13 исторические доки | A: баннер + тест-гвардия | — |
| G-14 `docs/tracker.md` | A: оставить, записать в контракт «агент tracker не читает» | — |
| G-15 темп операций | Целевой темп — единицы-десятки в день; P8/G-8 всё равно делаем, потому что цена этапа мала, а потеря операции немая | — |

Три спорных пункта, выходящих за рамки G-1…G-15, подтверждены владельцем
2026-09-07 и зафиксированы ниже:

| Пункт | Решение | Этап |
|---|---|---|
| значение `Lead` в `jobs.LEVELS` | **добавить** как каноническое значение enum'а | Э5 |
| исход прогона при `status: rejected` | результат коммитится и пушится, **job завершается ненулевым кодом** | Э1 |
| разбиение `scripts/jobs.py` (G-9B) | **делать**, после Э1–Э7 и только после централизации путей | Э10 |

## 2. Что план не трогает

Это сильные части архитектуры; ни один этап не имеет права их ослабить.
Проверка — существующие 177 тестов плюс новые гвардии.

- immutable request/result, `operation_id` в имени файла, запрет перезаписи
  результата;
- optimistic locking через `expected` и `precondition_mismatches`;
- `apply_dataset_transaction` и временный workspace для batch;
- changed-path allowlist в runner'е и запрет request-provided shell;
- `data/jobs.csv` — единственный структурированный источник истины
  (вариант В4 из аудита отклонён);
- `docs/tracker.md` — генерируемый, руками не правится;
- `applied` и другие lifecycle-события ставит только человек
  (`confirmed_by_user=true`);
- zero-dependency runtime (ruff появляется только как CI/dev-инструмент).

---

## 3. Этапы

Каждый этап — одна логическая операция и один коммит (или явно перечисленная
короткая серия), формат сообщения — по `AGENTS.md`. В каждом этапе указано, что
обновляется по «матрице обновлений» из [`README.md`](README.md).

### Э0. Baseline и регистрация документов

**Цель.** Сделать прогресс измеримым и ввести оба документа в индекс.

**Изменения.**
- `scripts/maintenance/ops_health.py` — read-only отчёт (без сети): запросов,
  результатов, запросов без результата, распределение `status` в результатах,
  пустой `original_url`, placeholder-компании, побайтовый вес boot-набора.
  `--format json` для сравнения между этапами.
- `docs/README.md`: анализ — в «Исследования и предложения», этот план — в
  действующие документы; после закрытия всех этапов оба уезжают в Historical.

**DoD.** `python3 scripts/maintenance/ops_health.py --format json` печатает
таблицу раздела 0; `python3 -m unittest discover -s tests` зелёный
(`test_documentation` проверяет живые ссылки индекса).

**Риск.** Нет. Этап read-only.

---

### Э1. Каждая операция оставляет машиночитаемый результат (P4, G-3A)

Самый важный этап: он превращает все остальные ошибки в самообъяснимые и снимает
зависимость от логов GHA, которые агент не читает.

**Корневая причина.** `agent_operations.py` при любой `OperationError` уходит в
`die()` → `SystemExit(1)`; result-файл не пишется, шаг workflow падает, агент
видит только «упало». 32 таких запроса лежат в репозитории без объяснения.
Отдельно: `jobs.py` содержит 85 вызовов `die()`, и часть из них достижима из
connector-пути — это второй канал немого падения.

**Дизайн.**

1. Структурированная ошибка в `agent_operations.py`:

   ```python
   class OperationError(ValueError):
       def __init__(self, message, *, code="contract_violation", field=None,
                    allowed=None, hint=None, layer="operations"):
   ```

   и хелпер `contract_error(...)`. Существующая сигнатура
   `OperationError(message)` сохраняется — это позволяет переводить call sites
   волнами, не ломая тесты за один коммит.

2. Таксономия `code` (закрытый набор, проверяется тестом):
   `invalid_json`, `request_too_large`, `filename_mismatch`,
   `unsupported_command`, `unknown_top_level_fields`, `missing_top_level_fields`,
   `unknown_args`, `missing_args`, `bad_type`, `bad_enum_value`, `bad_format`,
   `duplicate_add_extra_fields`, `invariant_violation`, `unknown_job`,
   `result_exists`, `batch_not_atomic`.

3. Волна 1 покрывает ровно те классы, которые дали 35 падений:
   `validate_add_args` (unknown/missing args, enum, `duplicate_of`),
   `validate_verify_args` (`listing_status`), `validate_status_args`,
   `validate_operation` (top-level, `atomic`), `load_operation` (JSON, размер,
   имя файла).

4. `rejected` result. `execute()` оборачивается так, что **любая**
   `OperationError` **и любой `SystemExit` из слоя `jobs`** дают файл:

   ```json
   {
     "version": 1,
     "operation_id": "jaabz-20260907-frontend-pass-004",
     "status": "rejected",
     "command": "add",
     "executed_at": "2026-09-07T12:34:56Z",
     "risk": "none",
     "error": {
       "code": "unknown_args",
       "layer": "operations",
       "field": "args.next_action",
       "message": "add does not accept next_action",
       "allowed": ["company", "role", "source", "..."],
       "hint": "create the job first, then send a separate set operation with next_action"
     }
   }
   ```

5. `operation_id` для пути результата берётся **из имени файла запроса**, а не из
   его содержимого: при `invalid_json` или несовпадении имени содержимому верить
   нельзя, а имя runner уже провалидировал регуляркой. `command` при
   нераспознанном запросе — `"unknown"`.

6. Безопасность записи: `rejected` пишется только когда canonical данные не
   изменены. Для `add` это гарантировано разделением `prepare_add` /
   `persist_add` (валидация целиком до записи). Для `verify`/`status`/`set`/
   `screen` и batch нужен явный аудит достижимых `die()`: те, что достижимы из
   connector-пути, переводятся в `jobs.ValidationError` (исключение, а не
   `SystemExit`) в этом же этапе; те, что не достижимы, остаются как есть и
   покрываются тестом «connector-путь не вызывает `die()`».

7. `--format json` для `apply` при отказе печатает `{"ok": false, ...}` и
   выходит с ненулевым кодом — контракт CLI сохраняется.

8. Workflow `agent-operations.yml`:
   - `status` расширяется до `{completed, conflict, rejected}`, `risk` — до
     `{low, medium, none}`;
   - шаг «Validate resulting tracker state» получает
     `if: steps.operation.outputs.status != 'rejected'` (экономит 21 с тестов на
     отказе; датасет при отказе не менялся);
   - шаг allowlist при `rejected` требует ровно один изменённый путь —
     `data/operations/results/<id>.json`;
   - коммит и push выполняются **и при `rejected`** (сообщение
     `jobs: reject agent operation <id>`);
   - последний шаг при `rejected` завершает job'у ненулевым кодом: агент читает
     файл, человек видит красный прогон. Решение подтверждено: история прогонов
     должна быть честной, а «зелёный прогон с отказом внутри» скрывает от
     человека то, что агент уже видит в результате.

**Тесты.** `tests/test_agent_operations.py`: на каждый `code` — отказ пишет
result с ожидаемыми `code`/`field`; `result_exists` не перезаписывается;
`SystemExit` из `jobs` конвертируется в `invariant_violation`; canonical CSV
после отказа побайтово не изменился. Новый тест на закрытость набора `code`.

**DoD.** Ни один путь `agent_operations.py apply` не завершается без файла в
`results/`; ручной прогон трёх исторических «немых» запросов даёт валидные
`rejected`-результаты.

**Риск.** Средний: меняются сообщения об ошибках, часть существующих тестов
сверяет текст. Митигация — волновой перевод call sites и сохранение старой
сигнатуры конструктора.

**Обновить в том же коммите.** `data/operations/README.md` (раздел Runner
contract: три возможных `status`, форма `error`, правило «ретрай = новый
`operation_id`»), `docs/agent-operations.md`, `AGENTS.md` (абзац про connector),
тесты.

---

### Э1b. Backfill 32 «немых» запросов и инвариант «у каждого запроса есть результат»

**Цель.** Сделать правду о прошлом читаемой и запретить её повторение.

**Изменения.**
- `scripts/maintenance/backfill_missing_results.py`: для каждого запроса без
  результата выполняет `agent_operations.py validate` локально и пишет
  `results/<id>.json` со `status: "rejected"`, `error.code` из валидатора и
  маркером `"backfilled": true` (плюс `"executed_at"` — дата backfill'а, не
  фальсифицированная дата прогона). Для запросов, которые проходят валидацию
  (потеря на push, RC-9), — `error.code: "lost_before_apply"` c пояснением.
- Тест-гвардия: множество имён в `requests/` равно множеству имён в `results/`.

**DoD.** `requests` = `results` по именам; `ops_health` показывает «запросов без
результата: 0».

**Риск.** Низкий, но заметный: гвардия падает, если запрос закоммичен, а прогон
ещё не завершён. В workflow это безопасно (тесты идут после apply), но локально
до `git pull` возможен ложный красный — тест должен формулировать это в
сообщении.

---

### Э2. Генерируемая таблица «поле × команда» (P1, P2, G-2A)

**Корневая причина.** RC-1/RC-3/RC-4: `data/schema.md` перечисляет 31 canonical
столбец, но нигде не сказано, какие из них принимает какая команда.
`next_action` и `verified_at` — 17 из 35 падений; `verified_at` не принимает
**ни одна** команда, его вычисляет runner.

**Дизайн.**
- Единый источник — код. Спека собирается из `agent_operations`
  (`ADD_ALLOWED_ARGS`, `ADD_REQUIRED_ARGS`, `ADD_DUPLICATE_ARGS`,
  `VERIFY_*`, `SET_ALLOWED_ARGS`, `SCREEN_*`, `STATUS_*`) и `jobs`
  (`FIELDS`, `ENUMS`, форматы дат/URL, диапазон `match_score`).
- Новая подкоманда `python3 scripts/agent_operations.py render-contract`
  с `--check`, вывод — `data/operations/contract.md`. Файл зависит только от
  кода, поэтому `--check` живёт в `validate.yml`, а не в операционном workflow:
  в diff операций он не появляется.
- Разделы файла: по одной таблице на `add`, `add + duplicate_of`, `verify`,
  `screen`, `set`, `status`, batch child (`add` c `client_ref` / job-child с
  `expected`); колонки: поле, тип, допустимые значения, required, примечание.
  Плюс два вычисляемых раздела:
  - **«Никакая команда не принимает»** = `FIELDS` минус объединение всех
    allowlist'ов (сюда автоматически попадают `id`, `verified_at`,
    `last_update`, `stage_reached` и остальные runner-computed);
  - **«Инварианты между полями»** — текстом: `first_party_verified=yes` требует
    `original_url`; `apply_verified=yes` требует `first_party_verified=yes`;
    `listing_status=closed` до отклика требует
    `decision_reason=closed_before_application`; `application_status=apply`
    требует пройденной verification и непустого `next_action`.
- Устранить расхождение одноимённых констант: `agent_operations`
  `ADD_APPLICATION_STATUSES` → `CONNECTOR_ADD_APPLICATION_STATUSES` с
  комментарием, почему `apply` исключён (поведение не меняется).
- `data/operations/README.md`: happy-path пример `add` дополняется явным
  предупреждением про `duplicate_of` (только required + source-reference, любое
  каноническое поле рядом = отказ) и ссылкой на `contract.md`.
- `data/schema.md`: у каждого поля — кто его пишет (агент через команду X /
  runner / человек), либо строка-ссылка на `contract.md` для write-права.

**Тесты (P2).** Новый `tests/test_contract.py`: (1) `render-contract --check`
чист; (2) каждое поле каждого allowlist'а присутствует в таблице своей команды;
(3) каждое значение каждого enum'а из `jobs.ENUMS` присутствует; (4) каждое поле
`FIELDS` либо в какой-то команде, либо в разделе runner-computed; (5) каждый
инвариант из списка упомянут.

**DoD.** Агент, прочитавший только `contract.md`, не может собрать `add.args` с
`next_action`/`verified_at`, не увидев запрета. Дока не может разойтись с кодом
незаметно.

**Обновить в том же коммите.** `data/operations/contract.md` (генерируется),
`data/operations/README.md`, `data/schema.md`, `docs/agent-operations.md`,
`docs/README.md` (матрица обновлений: «изменился allowlist команды → перегенерить
`contract.md`»), `.github/workflows/validate.yml`, тесты.

---

### Э3. Путь доставки: запрет PR и устранение push race (P9, P8)

Два независимых изменения в одном этапе — оба касаются только runner'а и не
трогают Python-контракт.

**P9, запрет PR.** Все 6 падений на шаге «Find the one new request» — merge-
коммиты PR'ов, где diff содержит больше одного файла.
- Новый job в `validate.yml` (или отдельный `agent-operations-guard.yml`) на
  событие `pull_request`: если PR меняет `data/operations/requests/**`, шаг
  падает с текстом «this delivery path is not supported: commit the request
  directly to main». Агент узнаёт о запрете до merge, а не после.
- В push-job добавить явную проверку «HEAD не merge-коммит»
  (`git rev-list --parents -n 1 HEAD` содержит один parent) с тем же текстом —
  сейчас ошибка выглядит как невнятное `main must add exactly one …`.

**P8, push race.** Последний шаг — `git push origin HEAD:main` без обновления
базы; при двух операциях подряд вторая теряется (`! [rejected] … fetch first`),
уже применившись локально. `concurrency` сериализует прогоны, но не обновляет
checkout.
- **Не rebase.** `data/jobs.csv`, `data/job_sources.csv` и `docs/tracker.md`
  дописываются обеими операциями; rebase даёт конфликт слияния в canonical
  данных — худший из возможных исходов.
- Вместо этого — **повторное применение на свежем `main`** (до 3 попыток):
  1. `git fetch origin main`;
  2. `git reset --hard origin/main`;
  3. удалить локальный `results/<id>.json` (иначе `write_result` откажет по
     `result_exists`);
  4. заново `agent_operations.py apply` → `validate --strict` →
     `render-tracker` → `render-tracker --check` → тесты → allowlist;
  5. commit и push.
- Повторное применение — это ещё и корректная повторная проверка optimistic
  lock: если за это время строка изменилась, агент получит честный
  `conflict`-результат вместо тихой перезаписи.
- Все шаги пути apply→push выносятся в `scripts/ci/apply_operation.sh` (или в
  composite action), чтобы retry-петля не дублировала YAML.

**Тесты.** Логика retry живёт в shell, поэтому проверяется вручную:
подготовленная пара запросов, закоммиченных с интервалом < длительности прогона;
ожидаемо — два результата и два canonical коммита. Сценарий записать в
`docs/current-architecture.md` как проверку runner'а.

**DoD.** Пара быстрых последовательных запросов даёт два результата; PR с
запросом падает на `pull_request`-проверке с явным текстом.

**Обновить в том же коммите.** `.github/workflows/agent-operations.yml`,
`.github/workflows/validate.yml` (или новый guard), `docs/current-architecture.md`,
`data/operations/README.md` (Runner contract), `AGENTS.md` (одна строка: PR-путь
не поддерживается, узнать об этом можно на `pull_request`-проверке).

---

### Э4. Batch: выбор атомарности и готовый фрагмент ретрая (P6, P5, G-4A)

**Корневая причина.** RC-7: `atomic: true` обязателен, а fuzzy-дедуп
(`company ≥ 0.85` И `role ≥ 0.75`) непредсказуем для агента. 10 из 13
конфликтов — откат целого batch из-за одного child; худший случай —
конфликт на child #26.

**Дизайн.**
- `validate_operation` принимает `atomic: false`. Лимиты по режиму:
  `atomic: true` — не более **10** children (риск потери всей работы растёт
  линейно с размером); `atomic: false` — прежние 100.
- Статическая валидация остаётся всеобщей: невалидный по контракту child
  отклоняет весь запрос (`rejected`) в любом режиме. Частичность касается только
  runtime-исходов: `unresolved_duplicate`, `source_reference_conflict`,
  `stale_operation`.
- Исполнение `atomic: false`: те же temp-workspace и одна транзакция, но
  падающий child не поднимает `BatchConflict`, а записывается со своим статусом
  и исключается из применяемого набора. Итоговый `status` результата:
  `completed` (все прошли), **`partial`** (часть), `conflict` (не прошёл ни
  один). `partial` добавляется в enum статусов workflow.
- Per-child запись результата: `client_ref`/`job_id`, `command`, `status`,
  `outcome` либо `conflict`.
- **P5 — фрагмент ретрая.** Для каждого конфликтного child в результат
  добавляется готовый к отправке JSON:

  ```json
  "retry": {
    "as_duplicate": {"command": "add", "client_ref": "jaabz-014",
                     "args": {"company": "...", "role": "...", "source": "Jaabz",
                              "source_url": "...", "duplicate_of": "job-0231"}},
    "as_separate": {"command": "add", "client_ref": "jaabz-014",
                    "args": {"...": "...", "force": true}}
  }
  ```

  Для `stale_operation` — фрагмент с актуальными значениями `expected`.
  Тот же блок добавляется в single-операции `add` (там сейчас только список
  кандидатов).

**Тесты.** `tests/test_agent_batch_operations.py`: `atomic: false` с одним
конфликтным child применяет остальных и даёт `partial`; `atomic: true` с 11
children отклоняется по контракту; фрагменты `retry` валидны как самостоятельные
запросы (пропускаются через `validate_operation`) — это сильная гвардия, она не
даёт сгенерировать «совет», который не примет валидатор.

**DoD.** Discovery-pass из 27 вакансий с одним ложным дублем записывает 26 строк
и объясняет 27-ю фрагментом ретрая.

**Обновить в том же коммите.** `data/operations/README.md` (Phase B),
`data/operations/contract.md` (перегенерация), `docs/agent-operations.md`,
`AGENTS.md` (сейчас там «`batch` только с `atomic=true`» — формулировка меняется
на два режима с лимитами), `.github/workflows/agent-operations.yml` (статус
`partial`), тесты.

---

### Э5. Enum-guidance, качество дедупа и `original_url` (P3, P7, G-5, G-7)

**Изменения.**

1. **Enum-guidance (P3).** В `contract.md` рядом с `remote_policy` — строка:
   «источник пишет просто “Remote” без списка стран → `Unclear`; `Remote` не
   является значением enum'а». Фактически прислано: `"Remote"` ×4,
   `"Worldwide remote-first"` ×1, `level: "Lead"` ×2.
2. **`Lead` в `LEVELS` — добавляем.** Значение вставляется между `Senior` и
   `Unknown`, чтобы порядок enum'а оставался по возрастанию сеньорности с
   `Unknown` в конце. Изменение схемы, поэтому `scripts/jobs.py` (`LEVELS`),
   `data/schema.md`, тесты и перегенерация `data/operations/contract.md` — **в
   одном коммите** (правило `AGENTS.md`). Существующие строки не переписываются:
   backfill'а нет, `Lead` появляется только у новых записей. Отбор Lead-вакансий
   по-прежнему выражается `decision_reason=seniority_too_high` — `level`
   описывает вакансию, а не решение по ней.
3. **Placeholder-компании (P7).** 26 строк вида `Undisclosed …` / `Unknown …`
   дают company-score 1.00 друг против друга и работают генератором ложных
   дублей. В `find_duplicate_candidates`: если хотя бы одна сторона —
   placeholder (`^(undisclosed|unknown|confidential|n/?a)\b`, регистр не
   важен), fuzzy-сравнение company/role не применяется; такая пара считается
   кандидатом только при совпадении `norm_url(original_url)` или
   `source + source_job_id`.
4. **Read-only индекс нормализованных ключей (G-5C).** Реализуется в Э6 как
   `data/index/known.tsv`: агент может сам свериться до отправки, вместо
   попыток воспроизвести `SequenceMatcher` по 206 КБ CSV.
5. **`original_url` (G-7).** (A) `validate_verify_args` получает то же правило,
   что уже есть в `add`: `first_party_verified=yes` требует непустой
   `original_url` — сейчас `verify` его не требует, и это основной источник
   пополнения 281 пустой ячейки. (B) `scripts/maintenance/backfill_original_url.py`:
   для строк с пустым `original_url`, где источник и есть первоисточник
   (`Company Careers` и аналогичные из `SOURCES`), `original_url := source_url`;
   применяется одним локальным коммитом с отчётом «сколько строк затронуто».

**Тесты.** Фикстуры с двумя `Undisclosed`-строками разных вакансий не дают
кандидата; те же строки с совпадающим `source_job_id` — дают. `verify` без
`original_url` при `first_party_verified=yes` отклоняется. Backfill
идемпотентен и не трогает непустые значения.

**DoD.** Доля ложных `unresolved_duplicate` на исторических конфликтах
пересчитана: ожидаемо 9 из 10 batch-конфликтов больше не воспроизводятся.
`ops_health` показывает падение числа пустых `original_url`.

**Обновить в том же коммите.** `data/schema.md`, `data/operations/contract.md`,
`data/operations/README.md`, `docs/jobs-cli.md`, тесты.

---

### Э6. Компактный бутстрап: генерируемые индексы (В1, G-6)

**Корневая причина.** Промпт требует читать `data/jobs.csv` (206 543 Б) и
`data/job_sources.csv` (44 392 Б) целиком — ~70K токенов, из которых 35.7% веса
CSV даёт колонка `notes`, не участвующая ни в дедупе, ни в решении «разбирать
заново или нет».

**Дизайн.**
- Новая подкоманда `python3 scripts/jobs.py render-index` с `--check`
  (тот же контракт exact-freshness, что у `render-tracker`). Три артефакта:

  | Файл | Содержимое | Замер |
  |---|---|---:|
  | `data/index/known.tsv` | `id, company, role, application_status, listing_status, decision_reason` (без URL) | ~29 КБ |
  | `data/index/keys.tsv` | `source` → `source_job_id`/URL, сгруппировано по источнику с вырезанным общим префиксом | ~13 КБ |
  | `data/index/active.csv` | активный срез (`reviewing`/`apply`/`applied`/`interviewing`/`offer` + `not_started` без `decision_reason`), все канонические поля | ~30 КБ |

- Детерминированность: сортировка по `id`, `\n`, без BOM — иначе `--check`
  станет источником ложных падений.
- `config/profile-digest.md` (~3 КБ, пишется руками): гео, уровень, стек,
  минимальная компенсация, work authorization, красные флаги. Дрейф от
  `config/profile.md` (12.7 КБ) сдерживается строкой в матрице обновлений и
  тестом на наличие обязательных ключей.
- Runner: `data/index/*` добавляются в changed-path allowlist и в `git add`;
  в операционный workflow добавляются `render-index` и `render-index --check`
  рядом с tracker'ом; в `validate.yml` — `render-index --check`.
- Цена: +3 генерируемых файла в diff каждой операции (осознанный минус В1).
  Выигрыш: boot ~85K → ~24K токенов (~3.5×), на данных ~6×.

**Тесты.** `render-index --check` падает после ручной правки индекса; активный
срез содержит ровно ожидаемые статусы; `known.tsv` не содержит `http`;
детерминированность при повторном рендере.

**DoD.** Бутстрап по индексам достаточен для дедупа и выбора работы; полный CSV
читается только по явной необходимости, и промпт требует объяснить причину.

**Обновить в том же коммите.** `scripts/jobs.py`, `.github/workflows/*`,
`data/schema.md` (раздел «Вычисляемые представления»),
`docs/current-architecture.md`, `docs/jobs-cli.md`, `docs/README.md`, тесты.

---

### Э7. `AGENTS.md` и launch prompt (раздел 2.5 аудита)

Выполняется после Э2 (есть `contract.md`) и Э6 (есть индексы), иначе промпт
будет ссылаться на несуществующие файлы.

**Изменения в `AGENTS.md`.**
- Блок «Перед любым поиском вакансий»: вместо «прочитать `data/jobs.csv`
  целиком» — порядок чтения `config/profile-digest.md` → `data/index/known.tsv`
  → `data/index/keys.tsv` → `data/index/active.csv` →
  `docs/sources/README.md` → названный им playbook. Полные CSV — только по
  явной необходимости, с объяснением причины.
- Новый абзац «Контракт полей»: до сборки request прочитать
  `data/operations/contract.md`; поля вне таблицы и значения вне enum'а
  отклоняются runner'ом. До Э2 — временная строка про `next_action`/`verified_at`
  (это половина падений и её можно снять одной строкой в первый же день).
- Правило ожидания результата: операция не завершена, пока нет
  `results/<operation_id>.json`; при `rejected`/`conflict` — исправить причину и
  создать **новый** `operation_id`, никогда не переписывать существующий request.
- Явный запрет PR и multi-file коммита (сейчас правило есть только в
  `data/operations/README.md`).
- Лимиты batch по режиму атомарности (из Э4).
- «`docs/tracker.md` — только для человека: агент его не читает и не включает
  в request» (G-14).
- `docs/sources/README.md` называется явно как точка входа в playbook'и.

**Изменения в launch prompt** (`docs/agent-operations.md`): черновик из раздела
2.5 аудита, с заполненными `<...>`: `data/operations/contract.md`,
`data/index/*`, `config/profile-digest.md`, лимиты batch, правило нового
`operation_id`.

**Тесты.** `tests/test_documentation.py` в стиле уже существующих проверок
фраз: `AGENTS.md` содержит запрет PR, правило ожидания результата, ссылку на
`contract.md` и на индексы; промпт и `AGENTS.md` не содержат требования читать
`data/jobs.csv` целиком.

**DoD.** Новый прогон агента с нуля не читает полные CSV и не отправляет поля
вне таблицы.

---

### Э8. Единый язык и адресация ошибок (P10, G-1A)

**Корневая причина.** RC-5: `agent_operations.py` — английский, 0 строк с
кириллицей; `jobs.py` — 238 строк с кириллицей, и его сообщения советуют
CLI-флаги (`используйте --force`, `нужен --decision-reason`,
`требует --applied-at`). У connector'а нет CLI: он получает невыполнимый совет
на другом языке, чем контракт.

**Дизайн.** Не «перевести `jobs.py`», а разделить адресатов:

```python
class ValidationError(Exception):
    def __init__(self, code, message_en, *, field=None, allowed=None,
                 agent_hint=None, cli_hint_ru=None):
```

- CLI ловит и печатает русский текст с флагами — человеку удобно, регрессии нет;
- `agent_operations` сериализует `code` + `message_en` + `agent_hint` в
  `error` (Э1), без упоминания флагов;
- переводятся только `die()`, достижимые из connector-пути (подмножество из 85);
  остальные остаются CLI-функцией.

**Тесты.** Для каждого connector-достижимого инварианта: CLI печатает русский
текст, connector-результат содержит английский `message` без символов `--`.
Гвардия: значения `error.message` и `error.hint` не содержат `--<flag>`.

**DoD.** Ни одно сообщение, адресованное connector'у, не советует
несуществующий у него интерфейс.

---

### Э9. Гигиена (G-10, G-12, G-13, G-11)

Четыре независимых мелких коммита. Выполнять после Э1–Э5, чтобы
format-прогон не конфликтовал с содержательными правками.

1. **Тулинг (G-10).** `pyproject.toml` + ruff (lint + format, line-length
   разумный для текущего стиля), шаг lint в `validate.yml`. mypy не включаем.
   Отдельно отметить: `ruff format` перепишет плотный стиль
   `agent_operations.py` (111 строк длиннее 100 символов, конкатенация через
   `;`) — это большой diff, но именно из этого файла генерируется контракт,
   и читаемость там ценнее стабильности diff'а. Форматирование — отдельным
   коммитом от изменения правил, чтобы обзор был возможен.
2. **Одноразовые миграции (G-12).** `migrate-v2`,
   `repair-himalayas-screening`, `backfill-sources` → `scripts/maintenance/`,
   убрать из основного `--help`. Обязательно обновить `AGENTS.md`: сейчас они
   перечислены в списке разрешённых команд write-path.
3. **Исторические доки (G-13).** Баннер
   `> Historical record. Not a contract.` в начало
   `architecture.md`, `setup-plan.md`, `tracker-v2-plan.md`,
   `tracker-browser-view-plan.md`, `tracker-v2-feedback.md`,
   `tracker-status-audit-2026-08-12.md`,
   `telegram-source-integration-plan.md`,
   `telegram-source-integration-analysis.md` + гвардия в
   `test_documentation.py` (каждый файл из Historical-раздела индекса содержит
   баннер). Плюс вычистить мусор `fileciteturn1file0` в `architecture.md`.
4. **Telegram (G-11).** В `docs/sources/telegram.md` — раздел о разделении
   ответственности `import_telegram.py` (790 стр.) и `telegram_leads.py`
   (800 стр.), 26% кодовой базы. Оба остаются.

Плюс мелкий дрейф: `docs/agent-operations.md` всё ещё упоминает «canonical
diff/PR», хотя PR-путь отменён — правится в Э3 или здесь.

---

### Э10. Разбиение `scripts/jobs.py` (G-9B) — отдельный и последний

3 195 строк / 140 КБ, 136 функций, 0 аннотаций типов, docstring'и 32/136;
`agent_operations.py` — 0/31. Этап подтверждён, но он не устраняет ни одного из
описанных в аудите падений: его цель — чтобы контракт впредь можно было узнать
из кода, а не из 140 КБ неаннотированного модуля. Поэтому он идёт последним,
после Э1–Э7.

**Предусловие, без которого рефакторинг сломает тесты и runner.** Сейчас
`temporary_tracker_workspace()` в `agent_operations.py` **патчит модульные
глобали** `jobs.ROOT`, `jobs.CSV_PATH`, `jobs.JOB_SOURCES_PATH`,
`jobs.APPS_DIR`, `jobs.TEMPLATE_PATH`; тесты делают то же. Если константы
переедут в подмодуль, патч shim'а перестанет влиять на реальные чтения.
Поэтому первый коммит этапа — централизация путей в один изменяемый объект
(`tracker.paths`) с обновлением всех патчеров, и только потом деление на
`schema` / `validate` / `write` / `render` / `ingest` / `cli` под уже
существующими 177 тестами. `scripts/jobs.py` остаётся тонким entry point'ом,
все документированные команды и `import jobs` продолжают работать.

**DoD.** Ни один тест не изменён по смыслу; `python3 scripts/jobs.py --help`
показывает тот же набор команд; аннотации типов добавлены хотя бы у публичных
функций write-path; в `agent_operations.py` появились docstring'и.

---

## 4. Порядок и зависимости

```text
Э0 ─┬─> Э1 ─┬─> Э1b
    │       ├─> Э2 ──> Э7
    │       ├─> Э4        ^
    │       └─> Э8        │
    ├─> Э3                │
    ├─> Э5                │
    └─> Э6 ───────────────┘
                          Э9 ──> Э10
```

- **Э1 — первый и один.** Пока каждая третья операция немая, любой другой этап
  проверяется вслепую.
- Э3, Э5, Э6 не зависят от Э1 и могут идти параллельно, если работает несколько
  сессий; Э3 не трогает Python-контракт вовсе.
- Э7 — последний содержательный: он фиксирует в промпте то, что уже существует.
- Э9 и Э10 — после того, как контракт устоялся.

Быстрая победа, которую можно сделать до Э1 отдельной строкой: стоп-лист
`next_action` / `verified_at` в `AGENTS.md` и в промпте. Это половина падений
и один абзац правки.

## 5. Метрики закрытия плана

Считаются `scripts/maintenance/ops_health.py` (Э0) до и после.

| Метрика | Сейчас | Цель | Закрывает |
|---|---:|---:|---|
| запросов без результата | 32 | **0** | Э1, Э1b |
| падений по контракту полей (`next_action`/`verified_at`) | 17 из 35 | 0 новых | Э2, Э7 |
| откатов batch из-за одного child | 10 из 13 | 0 | Э4, Э5 |
| падений на merge-коммите PR | 6 | 0 | Э3 |
| операций, потерянных на push | 2 | 0 | Э3 |
| boot-набор, токенов | ~85K | ~24K | Э6 |
| строк с пустым `original_url` | 281 | < 150 | Э5 |
| доля упавших прогонов workflow | 35% | < 10% | всё вместе |

Отдельно: после Э1 «упавший прогон» перестаёт означать «потерянную работу» —
отказ становится нормальным, читаемым исходом, поэтому доля красных прогонов
может остаться высокой, а стоимость ретрая упадёт.

## 6. Подтверждённые решения (2026-09-07)

Спорных пунктов, блокирующих старт этапов, не осталось. Владелец подтвердил:

1. **`Lead` добавляется в `LEVELS`** (Э5) — между `Senior` и `Unknown`, одним
   коммитом со схемой, тестами и перегенерацией контракта; существующие строки
   не переписываются.
2. **При `rejected` прогон остаётся красным** (Э1) — результат коммитится и
   пушится, job завершается ненулевым кодом.
3. **Э10 выполняется** — после Э1–Э7 и только после централизации путей
   (`jobs.ROOT`/`CSV_PATH`/`APPS_DIR` сейчас патчатся тестами и runner'ом).

Если в ходе работы появится новый спорный пункт, он дописывается сюда вместе с
этапом, который его ждёт, а не решается по ходу реализации.

## 7. Что сознательно не входит в план

- **В4** — вынос архива отсева в `data/screened.csv`: ломает «единственный
  источник истины», требует миграции схемы и переписывания валидаторов и
  тестов. Возвращаться к нему только если после Э6 бутстрап всё ещё дорог.
- **G-3B** — `workflow_dispatch` dry-run для предварительной проверки request'а:
  парковка до подтверждения, что у connector'а есть право на dispatch. После Э1
  ценность невелика.
- **mypy** — не включаем (G-10A).
- **Переписывание `jobs.py` с нуля** (G-9C).
- **Автоматическое слияние дублей**: `dupes` остаётся отчётом.
- **Любая автоматизация отправки заявок и постановки `applied`.**
