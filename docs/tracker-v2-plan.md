# Tracker v2 — план реализации

Дата: 2026-08-11
Статус: готов к поэтапной реализации
Основание: [`tracker-v2-feedback.md`](tracker-v2-feedback.md)

Продуктовые решения из раздела 2 подтверждены владельцем репозитория
2026-08-11.

## 1. Цель и границы

Tracker v2 должен превратить текущий ручной журнал в надёжный ingestion pipeline,
не меняя базовую архитектуру `CSV + Markdown + scripts + Git`.

Целевой сценарий:

1. Источник сохраняет сырой результат в `data/inbox/`.
2. Importer отделяет нерелевантный API-шум, нормализует запись и применяет hard
   filters.
3. Все релевантные вакансии получают явный исход: кандидат, отсев или дубль.
4. Дубль связывается с существующей вакансией до создания новой строки.
5. Кандидат проходит проверку careers/ATS и Apply.
6. Только `scripts/jobs.py` изменяет canonical вакансии и source references.
7. `todo`, `stale` и отчёты строятся из структурированных полей без парсинга
   `notes`.

Не входят в v2:

- веб-интерфейс;
- SQLite/Postgres;
- автоматическая отправка откликов;
- конкурентная запись несколькими процессами;
- сложная система весов для `match_score`.

## 2. Результат анализа feedback

### 2.1. Подтверждённые базовые решения

- `data/jobs.csv` остаётся canonical реестром вакансий и заявок.
- Состояние объявления и состояние отклика разделяются.
- Проверка первоисточника и Apply становится структурированной.
- Внешние источники не пишут в CSV напрямую.
- Первым API-источником подключается Himalayas.
- UI и база данных откладываются до появления подтверждённой боли.
- `Skipped`, `Closed` и `Duplicate` остаются вычисляемыми представлениями, а не
  третьим lifecycle enum.
- Новые enum используют lowercase snake_case.
- Агент может проверять careers/ATS и обновлять verification-поля; только
  фактическая отправка отклика и переход в `applied` остаются действием человека.

### 2.2. Что уточняется

#### `Skipped`, `Closed` и `Duplicate` не являются application status

Предложенный split не содержит прямой замены для старых `Skipped` и `Duplicate`.
В v2 это не самостоятельные состояния отклика, а представления, вычисляемые из
полей:

| Представление | Условие |
|---|---|
| Duplicate (legacy job rows) | `decision_reason=duplicate_listing` |
| Closed before application | `listing_status=closed`, `application_status=not_started` |
| Skipped | `application_status=not_started` и заполнена причина отсева, кроме duplicate/closed |
| Active candidate | нет terminal decision, объявление не `closed` |

`decision_reason` поэтому сохраняется. Добавлять третий lifecycle enum только
ради UI-представления не нужно.

#### Исторические данные нельзя считать проверенными задним числом

При миграции старое значение `Reviewing` или `Applied` не доказывает, что
первоисточник открыт сейчас. Если нет структурированного доказательства, новые
verification-поля получают `unknown`, а `verified_at` остаётся пустым. Текст из
`notes` автоматически не интерпретируется.

#### Registry должен появиться до первого importer

Feedback ставит source registry после ingestion. Реализация меняет порядок:
сначала фиксируется общий контракт источников, затем importer использует его без
hardcoded cadence, age и verification policy.

#### Формат registry — TOML, не YAML

Текущий CLI использует только стандартную библиотеку, а CI работает на Python
3.12. Поэтому целевой файл — `config/sources.toml`, читаемый через `tomllib` без
новой зависимости. Если позже появится общий dependency management, формат можно
пересмотреть отдельно.

#### Граница между API-шумом и найденной вакансией

Правило «ни одна найденная вакансия не остаётся без записи» применяется после
базового relevance gate:

- очевидно посторонний результат, не являющийся целевой frontend-вакансией,
  учитывается только как `noise` в batch summary;
- релевантная frontend-вакансия с geo, work authorization, seniority или другим
  hard blocker обязательно записывается с `application_status=not_started` и
  `decision_reason`;
- непроверенный релевантный кандидат сразу создаётся в `jobs.csv` со значениями
  verification `unknown` и действием `verify first-party`; inbox не становится
  вторым источником истины;
- закрытый первоисточник меняет только `listing_status` и причину решения;
- прошедшая проверку запись переводится в `reviewing`.

Relevance gate обязан быть детерминированным и объяснимым. Его outcome и причина
попадают в summary, но API-шум не раздувает canonical CSV.

`--dry-run` ничего не меняет и печатает исход каждой входной строки. В рабочем
запуске все записи после relevance gate должны оказаться либо в canonical данных,
либо среди source references уже известной вакансии.

### 2.3. Одна вакансия — несколько source references

Для идемпотентного повторного импорта одного URL недостаточно. В v2 до первого
importer создаётся `data/job_sources.csv`: вспомогательная many-to-one таблица
provenance. Стабильный ID карточки хранится как `source_job_id`, а уникальность
проверяется по паре `source + source_job_id`, если ID присутствует.

`jobs.csv` остаётся источником истины для вакансии, решения и отклика;
`job_sources.csv` не содержит самостоятельных job/application facts и не может
существовать без ссылки на `jobs.csv`. Новый подтверждённый дубль не создаёт
вторую job-строку, а добавляет source reference к canonical `job_id`.

Историческая строка со старым `status=Duplicate` сохраняется при миграции ради
неизменяемости ID и audit trail. После появления `job_sources.csv` новые
duplicate-строки больше не создаются.

## 3. Целевая модель данных

### 3.1. Новые и переименованные поля `jobs.csv`

| Поле | Формат | Назначение |
|---|---|---|
| `application_status` | enum | Состояние нашего решения или отклика; заменяет `status`. |
| `listing_status` | enum | Состояние объявления независимо от отклика. |
| `verified_at` | `YYYY-MM-DD` | Последняя ручная/автоматическая проверка первоисточника. |
| `first_party_verified` | enum | Найден и проверен официальный careers/ATS источник. |
| `apply_verified` | enum | Проверено, что Apply доступен и принимает заявки. |

Остальные v1-поля сохраняются. Рекомендуемый порядок начала строки:

```text
id,application_status,listing_status,company,role,...
```

### 3.2. Вспомогательная таблица `job_sources.csv`

```text
job_id,source,source_url,source_job_id,found_at
```

| Поле | Правило |
|---|---|
| `job_id` | Обязательный foreign key на существующий `data/jobs.csv:id`. |
| `source` | Существующий source enum. |
| `source_url` | URL конкретной карточки или источника обнаружения. |
| `source_job_id` | Стабильный ID внутри источника, если доступен. |
| `found_at` | Дата первого обнаружения этой source reference. |

Хотя бы одно из `source_url` или `source_job_id` обязательно; `found_at` также
обязателен.

`source` и `source_url` в `jobs.csv` временно сохраняются как первичный источник
для совместимости текущих команд и отчётов. `job_sources.csv` содержит полный
набор ссылок и не дублирует lifecycle-поля.

### 3.3. Enum-значения

```text
listing_status:
  open
  closed
  unknown

application_status:
  not_started
  reviewing
  apply
  applied
  interviewing
  offer
  rejected
  ghosted
  withdrawn

first_party_verified / apply_verified:
  yes
  no
  unknown
```

Новые enum записываются lowercase snake_case. Существующие `stage_reached`,
`source`, `level` и `remote_policy` не переименовываются в рамках этой миграции.

### 3.4. Детерминированная миграция `status`

| v1 `status` | v2 `application_status` | v2 `listing_status` | Дополнительное правило |
|---|---|---|---|
| `New` | `not_started` | `unknown` | verification unknown |
| `Reviewing` | `reviewing` | `unknown` | не выводить `open` из старого статуса |
| `Apply` | `apply` | `unknown` | не выводить `open` из старого статуса |
| `Applied` | `applied` | `unknown` | сохранить `applied_at` |
| `Interviewing` | `interviewing` | `unknown` | сохранить даты и stage |
| `Offer` | `offer` | `unknown` | сохранить даты и stage |
| `Rejected` | `rejected` | `unknown` | сохранить историю отклика |
| `Ghosted` | `ghosted` | `unknown` | сохранить историю отклика |
| `Withdrawn` | `withdrawn` | `unknown` | сохранить `decision_reason` |
| `Skipped` | `not_started` | `unknown` | сохранить `decision_reason` |
| `Closed` | `not_started` | `closed` | сохранить `closed_before_application` |
| `Duplicate` | `not_started` | `unknown` | сохранить `duplicate_listing` и ссылку |

Для всех исторических строк:

```text
verified_at=""
first_party_verified=unknown
apply_verified=unknown
```

Повторная verification выполняется отдельной операционной задачей, а не частью
миграции.

### 3.5. Минимальные invariants v2

1. `applied|interviewing|offer|rejected|ghosted|withdrawn` требуют `applied_at`.
2. `interviewing|offer|rejected` требуют `response_at`.
3. `listing_status=closed` никогда автоматически не меняет
   `application_status` после отклика.
4. Любое изменение `listing_status` или verification-флагов через CLI обновляет
   `verified_at`; историческая миграция не выдумывает эту дату.
5. `first_party_verified=yes` требует непустой валидный `original_url`.
6. `apply_verified=yes` требует `first_party_verified=yes` и `verified_at`.
7. `first_party_verified=yes|no` или `apply_verified=yes|no` требует
   `verified_at`; оба `unknown` допустимы с пустой датой.
8. Aggregator importer не может выставить `first_party_verified=yes` или
   `apply_verified=yes`; это делает отдельный verification step.
9. Каждая строка `job_sources.csv` ссылается на существующий `jobs.csv:id`.
10. Пара `source + source_job_id` уникальна в `job_sources.csv`, если ID
    присутствует; нормализованный `source_url` также не дублируется молча.
11. Source reference требует `found_at` и хотя бы одно из `source_url` или
    `source_job_id`.
12. Каждая новая v2 job с внешним источником имеет хотя бы одну source reference.
13. Legacy `decision_reason=duplicate_listing` требует ID оригинала и
    `application_status=not_started`.
14. `decision_reason=closed_before_application` требует
    `listing_status=closed` и отсутствия `applied_at`.
15. Pre-application причины отсева требуют `application_status=not_started`.
16. `stage_reached` не понижается и остаётся независимой исторической метрикой.
17. Агент может изменять verification-поля после фактической проверки
    первоисточника и Apply.
18. `application_status=applied` ставится только после фактической отправки
    человеком.

## 4. Целевая архитектура

```text
config/profile.md              config/sources.toml
         │                              │
         └──────────────┬───────────────┘
                        ▼
external source → source adapter → data/inbox/*.jsonl
                                      │
                                      ▼
                            normalize + filter
                                      │
                                      ▼
                         deterministic/fuzzy dedupe
                                      │
                                      ▼
                            verification queue
                                      │
                                      ▼
                              scripts/jobs.py
                         ┌──────┼───────────┐
                         ▼      ▼           ▼
                data/jobs.csv  data/job_sources.csv
                         │                  applications/*.md
                         ▼
                todo / stale / reports
```

Граница ответственности:

- adapter получает данные и пишет raw JSONL;
- ingest нормализует, классифицирует и готовит изменения;
- verification подтверждает официальный URL и Apply;
- только `jobs.py` валидирует и согласованно записывает canonical jobs и
  auxiliary source references.

## 5. Порядок реализации

Каждый work package ниже является отдельной логической операцией и отдельным
коммитом. Следующий package начинается только после прохождения acceptance checks
предыдущего.

### Phase 0 — зафиксировать контракт v2

Цель: убрать неоднозначности до изменения данных.

#### WP0.1. Документация решений

Шаги:

1. Согласовать поля, enum и таблицу миграции из раздела 3.
2. Обновить `docs/roadmap.md`, сделав этот документ подробным roadmap v2.
3. Добавить ссылку на план в `README.md`.
4. Пометить `docs/tracker-v2-feedback.md` как исходную обратную связь, а не
   исполнимую спецификацию.

Артефакты:

- `docs/tracker-v2-plan.md`;
- `docs/tracker-v2-feedback.md`;
- `docs/roadmap.md`;
- `README.md`.

Готово, когда: в документах нет двух разных последовательностей реализации и
понятно, какой файл является нормативным планом.

### Phase 1 — data model и безопасная миграция

Цель: разделить состояния без потери 98 существующих записей.

#### WP1.1. Исполнимая спецификация схемы

Шаги:

1. Обновить список и порядок колонок в `data/schema.md`.
2. Описать все новые enum и derived views.
3. Добавить таблицу переходов v1 → v2.
4. Обновить примеры `add`, `set`, закрытия объявления и отклика.
5. Обновить `AGENTS.md`: заменить проверки старого `status`, сохранив запрет на
   автоматический `applied`.

Артефакты:

- `data/schema.md`;
- `AGENTS.md`;
- `README.md`.

Acceptance:

- каждое старое состояние имеет ровно одно детерминированное отображение;
- для `Skipped`, `Closed`, `Duplicate` описано вычисляемое представление;
- ни одно правило не требует извлекать данные из `notes`.

#### WP1.2. Migration tool и validation

Шаги:

1. В `scripts/jobs.py` добавить v2 `FIELDS`, enum и invariants.
2. Добавить одноразовую команду `migrate-v2 --check` и режим записи
   `migrate-v2`.
3. В `--check` загрузить v1 CSV, построить v2 rows в памяти и показать summary,
   не меняя файл.
4. В режиме записи повторно построить rows, провалидировать и атомарно заменить
   CSV существующим `save()`.
5. Не создавать committed backup: rollback обеспечивает Git; перед миграцией
   рабочее дерево должно быть чистым.
6. После успешной миграции обычный `load()` больше не принимает v1 header.

Артефакты:

- `scripts/jobs.py`;
- `data/jobs.csv`.

Acceptance:

```bash
python3 scripts/jobs.py migrate-v2 --check
python3 scripts/jobs.py migrate-v2
python3 scripts/jobs.py validate
git diff --check
```

Ожидаемые контрольные суммы по текущим данным:

- строк до и после: `98`;
- уникальных `id` до и после: `98`;
- откликов с `applied_at`: `17`;
- записей с `listing_status=closed`: `24`;
- записей с `decision_reason=duplicate_listing`: `1`.

#### WP1.3. Regression tests и документация карточки

Шаги:

1. Переписать существующие tests под `application_status`.
2. Добавить parameterized migration tests для всех 12 старых статусов.
3. Добавить tests на независимость `listing_status` после `applied`.
4. Добавить tests для verification invariants.
5. Обновить application template: структурированная дата проверки, официальный
   URL и результат Apply должны совпадать с CSV.

Артефакты:

- `tests/test_jobs.py`;
- `tests/fixtures/jobs-v1.csv`;
- `applications/_TEMPLATE.md`.

Acceptance:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/jobs.py validate --strict
```

### Phase 2 — единый write path и structured I/O

Цель: ручной CLI и будущие importers используют одну бизнес-логику.

#### WP2.1. Внутренний write service

Шаги:

1. Разделить parsing CLI, построение row, duplicate detection, validation и
   atomic save на отдельные функции внутри `jobs.py`.
2. Направить существующие `add` и `set` через эти функции.
3. Сохранить текущее безопасное поведение: ошибка не меняет CSV и не оставляет
   application file.
4. Зафиксировать exit codes: `0` success, `1` invalid input/data, `2` unresolved
   duplicate.

Артефакты:

- `scripts/jobs.py`;
- `tests/test_jobs.py`.

#### WP2.2. JSON input и machine-readable output

Шаги:

1. Добавить `jobs.py add --json PATH`.
2. Добавить `jobs.py add --stdin`; запретить одновременный `--json` и `--stdin`.
3. Определить JSON Schema-подобный контракт в документации CLI.
4. Добавить общий `--format text|json` для `add`, `set`, `validate`, `dupes` и
   будущего `ingest`.
5. Не принимать неизвестные JSON-поля молча.
6. Никогда не принимать `id` и `last_update` от importer как authoritative.
7. Сохранить `--no-file`, `--force` и `--duplicate-of` как явные решения.

Артефакты:

- `scripts/jobs.py`;
- `docs/jobs-cli.md`;
- `tests/fixtures/job-input-valid.json`;
- `tests/fixtures/job-input-invalid.json`;
- `tests/test_jobs.py`.

Acceptance:

```bash
python3 scripts/jobs.py add --json tests/fixtures/job-input-valid.json --format json
python3 -m unittest discover -s tests -v
```

Тест должен выполняться во временном repository fixture и не менять реальные
`data/jobs.csv` или `applications/`.

### Phase 3 — source registry, source references и inbox contract

Цель: определить стабильную границу между fetcher и canonical write path.

#### WP3.1. Registry источников

Шаги:

1. Создать `config/sources.toml`.
2. Для каждого источника хранить `enabled`, `type`, cadence, max age, geo,
   `aggregator`, обязательные verification gates и caveats.
3. Перенести Himalayas-параметры из документации в registry.
4. Добавить loader и validation registry.
5. Не переносить факты о кандидате из `config/profile.md`.

Артефакты:

- `config/sources.toml`;
- `scripts/jobs.py` или `scripts/source_config.py`;
- `tests/test_source_config.py`;
- обновлённый `docs/himalayas-api.md`.

Acceptance: неизвестный source type, неверный cadence или отсутствующая
verification policy дают понятную ошибку до сетевого запроса.

#### WP3.2. Source references

Шаги:

1. Создать `data/job_sources.csv` со схемой из раздела 3.2.
2. Добавить loader, validation foreign keys, URL normalization и uniqueness.
3. При создании новой вакансии с `source_url` в той же операции создавать её
   первичную source reference.
4. Backfill существующих строк с непустым `source_url` без изменения `jobs.csv`.
5. Для legacy Duplicate направлять source reference на ID оригинала из `notes`,
   сохраняя саму legacy job-строку без изменений.
6. Изменить `add --duplicate-of`: после переходного периода команда добавляет
   source reference к canonical job, а не выделяет новый `job-NNNN`.
7. Валидировать `jobs.csv` и `job_sources.csv` как один dataset.

Артефакты:

- `data/job_sources.csv`;
- `data/schema.md`;
- `AGENTS.md`;
- `scripts/jobs.py`;
- `tests/test_job_sources.py`;
- `docs/jobs-cli.md`.

Acceptance:

- все source references указывают на существующие jobs;
- повторное добавление одной пары `source + source_job_id` идемпотентно;
- новый подтверждённый дубль не увеличивает число строк `jobs.csv`;
- legacy Duplicate остаётся доступен по прежнему immutable ID.

#### WP3.3. Canonical raw record

Минимальный JSONL record:

```json
{"source":"Himalayas","source_job_id":"abc","company":"Example","role":"Frontend Developer","source_url":"https://...","application_url":"https://...","posted_at":"2026-08-11","raw_location":"Worldwide","found_at":"2026-08-11"}
```

Шаги:

1. Создать `data/inbox/README.md` с контрактом и lifecycle raw files.
2. Хранить рабочие `*.jsonl` локально и не коммитить их; committed fixtures
   находятся только в `tests/fixtures/inbox/`.
3. Валидировать UTF-8, одну JSON object на строку, обязательные поля, даты и URL.
4. Считать вход immutable: ingest не исправляет файл на месте.
5. Добавить `batch_id` в runtime result для повторяемого summary, не в
   `jobs.csv`.

Артефакты:

- `data/inbox/README.md`;
- `data/inbox/.gitignore`;
- `tests/fixtures/inbox/himalayas-small.jsonl`;
- `tests/test_ingest.py`.

### Phase 4 — универсальный ingestion engine

Цель: получить детерминированную классификацию без прямой записи fetcher → CSV.

#### WP4.1. Normalize, filter, dedupe

Шаги:

1. Добавить `jobs.py ingest PATH --dry-run --format json`.
2. Применить детерминированный relevance gate и пометить посторонние результаты
   как `noise` с явной причиной.
3. Нормализовать прошедшие relevance gate source fields в структуру
   `jobs.py add`.
4. Применить только детерминированные hard filters с enum-причинами.
5. Выполнить dedupe в порядке:
   `source+source_job_id` → canonical first-party URL → source URL → normalized
   company+role+location → fuzzy candidate.
6. Детерминированный дубль привязать к canonical job через `job_sources.csv`.
7. Никогда автоматически не склеивать fuzzy candidate.
8. Для каждой входной строки вернуть outcome и reason.
9. Summary должен сходиться:
   `input = invalid + noise + skipped + duplicates + pending`.

Артефакты:

- `scripts/jobs.py`;
- при росте файла — `scripts/ingestion.py`;
- `tests/test_ingest.py`;
- `tests/fixtures/inbox/*.jsonl`.

Acceptance cases:

- повторный импорт одного batch идемпотентен;
- ошибка строки содержит номер JSONL line;
- `--dry-run` оставляет Git working tree неизменным;
- aggregator record не получает verification `yes`;
- summary учитывает каждую входную строку ровно один раз.

#### WP4.2. Apply plan атомарно

Шаги:

1. Разделить ingest на `plan` и `apply` внутри кода.
2. Полностью валидировать batch до первой записи.
3. Подготовить временные версии `jobs.csv`, `job_sources.csv` и новых application
   files, затем валидировать cross-file invariants до замены.
4. Применять dataset transaction под одним lock; при ошибке замены восстановить
   уже заменённые файлы из временных копий.
5. Создавать непроверенные релевантные вакансии сразу в `jobs.csv` со значениями
   verification `unknown` и `next_action=verify first-party`.
6. Создавать application markdown только для записей, перешедших в
   `reviewing`; unverified и skipped записи используют `--no-file` semantics.
7. При fuzzy duplicate завершать batch с exit code `2`, пока решение не передано
   явным resolution-файлом или флагом.
8. После записи автоматически запускать dataset validation и печатать итоговый
   machine-readable summary.

Артефакты:

- `scripts/jobs.py` / `scripts/ingestion.py`;
- `docs/jobs-cli.md`;
- `tests/test_ingest.py`.

Acceptance: искусственный batch из 50 строк либо применяется целиком, либо не
меняет `jobs.csv`, `job_sources.csv` и `applications/`; injected failure между
заменами файлов проверяет rollback.

### Phase 5 — Himalayas adapter и контролируемый rollout

Цель: доказать pipeline на одном источнике до подключения остальных.

#### WP5.1. Fetcher

Шаги:

1. Создать `scripts/import_himalayas.py`.
2. Читать query, cadence и max age из `config/sources.toml`.
3. Поддержать `--narrow`, `--broad`, `--output PATH` и `--dry-run`.
4. Сохранять raw API fields без вывода о живости объявления.
5. Использовать Himalayas `guid` как `source_job_id`.
6. Добавить timeout, ограниченные retries и понятные сетевые ошибки.
7. Не вызывать `jobs.py ingest` автоматически в первой версии fetcher.

Артефакты:

- `scripts/import_himalayas.py`;
- `tests/test_import_himalayas.py`;
- `tests/fixtures/himalayas-api-response.json`;
- `docs/himalayas-api.md`.

#### WP5.2. Verification workflow

Шаги:

1. После ingest вывести очередь `verify first-party`.
2. Агент проверяет careers/ATS URL, ограничения geo/work authorization и Apply.
3. Обновить запись одной CLI-командой, которая синхронно задаёт
   `listing_status`, `verified_at`, `first_party_verified`, `apply_verified`.
4. При hard blocker сохранить причину и не создавать application markdown.
5. При успешной проверке выставить `application_status=reviewing` и создать
   карточку из template.
6. Первые три реальных запуска выполнять под ручным контролем и сравнивать
   dry-run/apply summaries; verification может выполнять агент, но batch apply
   явно подтверждает человек.

Артефакты:

- новая команда или preset в `scripts/jobs.py` (`verify` предпочтительнее набора
  независимых `field=value`);
- `applications/_TEMPLATE.md`;
- `docs/jobs-cli.md`;
- реальные строки `data/jobs.csv` только после ручной проверки.

Rollout gate: automatic batch apply разрешается только после трёх запусков без
потерянных строк, неверных дублей и расхождения summary.

### Phase 6 — daily UX и повторная проверка

Цель: сделать структурированные данные полезными в ежедневной работе.

#### WP6.1. `stale`

Шаги:

1. Добавить `jobs.py stale --days N --format text|json`.
2. Включать активные записи с пустым `verified_at` или проверкой старше cutoff.
3. Исключать terminal pre-application решения и дубли.
4. Не менять данные автоматически.

Артефакты: `scripts/jobs.py`, `tests/test_jobs.py`, `docs/jobs-cli.md`.

#### WP6.2. `todo`

Шаги:

1. Добавить секции overdue, today, follow-ups, Apply not submitted, stale review,
   verification queue и upcoming interview/test.
2. Определить стабильный порядок сортировки: date → priority → id.
3. Добавить `--date YYYY-MM-DD` для воспроизводимых tests.
4. Поддержать text и JSON output.

Артефакты: `scripts/jobs.py`, `tests/test_jobs.py`, `docs/jobs-cli.md`.

#### WP6.3. Reports и stats

Шаги:

1. Переписать status report на `application_status + listing_status`.
2. Добавить verification coverage и stale counts.
3. Сохранить funnel по `stage_reached` и response rate по `applied_at`.
4. Добавить `jobs.py stats --format json` как источник weekly report.
5. Не добавлять score breakdown в CSV до появления аналитической потребности.

Артефакты:

- `scripts/jobs.py`;
- `tests/test_jobs.py`;
- `templates/weekly-review.md`;
- `reports/weekly/README.md`;
- `docs/jobs-cli.md`.

### Phase 7 — расширение после стабилизации

Начинать только после минимум двух недель использования Himalayas pipeline.

Кандидаты:

1. следующие adapters: LinkedIn email, HiringCafe, Wellfound;
2. match-score breakdown в `applications/<id>.md`;
3. генерация `reports/weekly/YYYY-Www.md`;
4. отдельный модульный package вместо роста одного `jobs.py`.

Каждый пункт требует отдельного решения и не блокирует v2.

## 6. Матрица артефактов

| Артефакт | Phase | Действие | Роль |
|---|---:|---|---|
| `data/jobs.csv` | 1 | migrate | canonical job/application data |
| `data/schema.md` | 1, 3 | update | нормативная схема и cross-file invariants |
| `scripts/jobs.py` | 1–6 | refactor/extend | единственный write path |
| `tests/test_jobs.py` | 1–6 | extend | lifecycle и regression tests |
| `tests/test_ingest.py` | 3–4 | create | batch, idempotency, atomicity |
| `tests/test_job_sources.py` | 3 | create | provenance и foreign keys |
| `config/sources.toml` | 3 | create | политика внешних источников |
| `data/job_sources.csv` | 3 | create/backfill | auxiliary source provenance |
| `data/inbox/README.md` | 3 | create | raw JSONL contract |
| `data/inbox/.gitignore` | 3 | create | raw batches не попадают в Git |
| `scripts/import_himalayas.py` | 5 | create | только fetch + raw normalize |
| `docs/jobs-cli.md` | 2–6 | create/update | CLI/JSON contracts и examples |
| `docs/himalayas-api.md` | 3, 5 | update | source-specific facts/caveats |
| `applications/_TEMPLATE.md` | 1, 5 | update | verification и analysis card |
| `AGENTS.md` | 1, 3 | update | правила lifecycle, verification и duplicate refs |
| `README.md` | 0, 1 | update | ежедневный quick start |
| `docs/roadmap.md` | 0 | update | краткий индекс фаз |

## 7. Сквозные quality gates

После каждого work package:

```bash
python3 scripts/jobs.py validate --strict
python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Для ingestion дополнительно:

- dry-run не меняет filesystem;
- повторный batch не создаёт новые jobs или source references;
- invalid batch не даёт partial write;
- количество outcomes равно количеству input records;
- API-шум учитывается как `noise`, но не создаёт job/source rows;
- ни один aggregator record не становится verified без отдельного шага;
- закрытие listing после отклика сохраняет application history.

## 8. Definition of Done v2

v2 считается готовой, если воспроизводимо проходит сценарий:

1. Himalayas fetcher сохраняет 50 raw records в JSONL.
2. `ingest --dry-run --format json` классифицирует все 50 без записи.
3. Посторонний API-шум получает outcome `noise` и не попадает в canonical CSV.
4. Релевантные hard blockers получают явные причины, а не исчезают из pipeline.
5. Known jobs не создаются повторно: новая ссылка добавляется в
   `job_sources.csv`.
6. Неясные fuzzy matches требуют явного решения.
7. Непроверенные кандидаты сразу сохраняются в `jobs.csv` и появляются в
   verification queue со значениями `unknown`.
8. Агент проверяет первоисточник и переводит закрытые объявления в
   `listing_status=closed`, не имитируя отклик.
9. Прошедшие проверку записи переходят в `reviewing` и получают application card.
10. `todo` показывает следующие действия, а `stale` — просроченную verification.
11. После фактического отклика человек переводит запись в `applied`.
12. Позднее закрытие объявления меняет только `listing_status`.
13. Повторный импорт того же batch не меняет число canonical вакансий или source
    references.
14. `validate --strict`, все unit tests и `git diff --check` проходят.

## 9. Риски и защита

| Риск | Защита |
|---|---|
| Потеря истории при split status | детерминированная миграция, row-count checks, Git rollback |
| Ложное `open` для старых строк | миграция в `unknown`, затем отдельная verification |
| Частичная запись batch | dataset transaction, lock и rollback подготовленных файлов |
| Автоматическое ошибочное склеивание | fuzzy match только блокирует и просит решение |
| Прямой importer write | adapter пишет только JSONL; canonical write остаётся в `jobs.py` |
| Тихая потеря результатов | conservation equation; `noise` отделён от релевантных hard blockers |
| Расхождение двух CSV | cross-file validation, dataset lock и rollback при ошибке замены |
| Рост сложности CLI | общий write service, JSON contract, модульное выделение после стабилизации |
| Новая YAML dependency | TOML + `tomllib` из Python 3.12 |

## 10. Рекомендуемый первый implementation slice

Первый последующий рабочий цикл должен включать только Phase 1:

1. обновить схему и правила;
2. реализовать migration check;
3. добавить migration tests;
4. мигрировать 98 строк;
5. обновить CLI/tests/template;
6. прогнать quality gates;
7. сделать три логических commit по WP1.1, WP1.2 и WP1.3.

Не смешивать с этим циклом JSON input, inbox или Himalayas: сначала новая модель
должна стабильно работать в существующем ручном процессе.
