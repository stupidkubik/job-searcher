# `jobs.py` CLI

`scripts/jobs.py` — единственный write path для canonical `data/jobs.csv` и
provenance-таблицы `data/job_sources.csv`.
Ручной CLI, JSON-ввод и будущие importers используют одинаковые функции
построения записи, проверки дублей, validation и атомарной записи.

## Коды завершения

| Код | Значение |
|---:|---|
| `0` | Команда успешно выполнена. |
| `1` | Некорректный ввод или данные не проходят validation. |
| `2` | Обнаружен неразрешённый duplicate; нужен явный `--duplicate-of` или `--force`. |

## Добавление из CLI

```bash
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source Manual \
  --application-status reviewing --listing-status open \
  --original-url "https://careers.example.com/jobs/frontend" \
  --first-party-verified yes --apply-verified yes
```

`--no-file`, `--force` и `--duplicate-of JOB_ID` — намеренные решения оператора;
они не принимаются через JSON. Для любого нового внешнего источника обязательны
`--source-url` или `--source-job-id`; исключение — только `Manual` и `Referral`.

`--duplicate-of JOB_ID` не создаёт новую строку вакансии: он добавляет source
reference к уже существующей canonical вакансии. Без `--found-at` новая
reference получает текущую tracker-дату в `Europe/Belgrade`, а не дату первого
обнаружения canonical вакансии. Команда идемпотентна. Если нормализованный
`source_url` уже привязан к другой вакансии, CLI завершится с кодом `2`;
`--force` — явное разрешение для shared discovery page.

## Structured input для `add`

Передать один JSON object можно файлом или stdin:

```bash
python3 scripts/jobs.py add --json tests/fixtures/job-input-valid.json --format json
printf '%s' '{"company":"ExampleCo","role":"Frontend Developer","source":"Manual"}' \
  | python3 scripts/jobs.py add --stdin --no-file --format json
```

`--json` и `--stdin` взаимоисключающие. Их нельзя смешивать с полями вакансии из
CLI, чтобы не было неявного merge. Управляющие флаги `--no-file`, `--force` и
`--duplicate-of` при structured input разрешены и остаются явными.

JSON должен быть UTF-8 object. Обязательные строковые поля:

```text
company, role, source
```

Допустимые необязательные поля:

```text
application_status, listing_status, first_party_verified, apply_verified,
level, remote_policy, original_url, source_url, source_job_id, location, stack, salary,
posted_at, found_at, match_score, decision_reason, notes
```

Все поля, кроме `match_score`, должны быть строками. `match_score` может быть
строкой или JSON number. Неизвестные поля отвергаются. В частности, importer не
может передать `id`, `last_update`, `verified_at`, `stage_reached`, `applied_at`
или любые другие canonical/derived поля: ID и timestamps назначает write path.

## Machine-readable output

`add`, `set`, `status`, `screen`, `verify`, `validate`, `render-tracker`, `dupes`, `ingest`,
`stale`, `todo`, `stats` и `repair-himalayas-screening` поддерживают
`--format text|json`; по умолчанию — `text`. Успешный JSON-ответ состоит ровно
из одного object с `ok`,
`command` и результатом команды. Например, `add` возвращает canonical `job`,
`warnings`, `source_reference` и путь к созданной application card (или `null`).

```json
{"application_path":"applications/job-0099-exampleco-frontend-developer.md","command":"add","job":{"id":"job-0099"},"ok":true,"source_reference":{"created":true},"warnings":[]}
```

При `add --format json` неразрешённый duplicate также возвращается JSON object с
`ok=false`, `error="unresolved_duplicate"` и списком кандидатов, затем завершает
процесс с кодом `2`. Validation-ошибки завершаются кодом `1`.

## Source references и backfill

`data/job_sources.csv` связывает canonical `job_id` с `source`, `source_url`,
`source_job_id` и `found_at`. Уникальная пара `source + source_job_id` не может
принадлежать двум вакансиям. `validate` всегда проверяет обе таблицы как единый
dataset.

Для разовой миграции legacy-данных используйте:

```bash
python3 scripts/jobs.py backfill-sources --check
python3 scripts/jobs.py backfill-sources
```

Первая команда ничего не меняет. Вторая создаёт references из прежних
`source_url`; legacy `duplicate_listing` перенаправляется на job ID оригинала из
`notes`. В отчёте отдельно показано, сколько shared discovery URL было явно
разрешено при backfill.

## Ingest raw batch

```bash
python3 scripts/jobs.py ingest data/inbox/himalayas-2026-08-11T090000Z.jsonl \
  --dry-run --format json
```

Ingest всегда сначала строит детерминированный plan. Для каждой JSONL-строки
JSON-ответ содержит `outcome` (`invalid`, `noise`, `skipped`, `duplicate` или
`pending`) и `reason`; summary удовлетворяет равенству
`input = invalid + noise + skipped + duplicates + pending`.

Порядок безопасного dedupe: `source + source_job_id`, candidate first-party URL,
source URL, нормализованные `company + role + location`, затем fuzzy candidate.
Детерминированный дубль добавляет source reference к canonical job. Fuzzy match
никогда не склеивается автоматически: команда печатает plan и завершается с
кодом `2` до явного resolution.

Для явного решения создайте рядом с batch локальный sidecar
`*.resolution.json`. Он привязан к SHA-256 exact bytes raw batch и сам также
игнорируется Git; raw JSONL не меняется. `candidate.line` ссылается на более
раннюю строку того же immutable batch, `candidate.job_id` — на уже существующую
canonical job. `separate` сохраняет новую самостоятельную вакансию, а
`duplicate` добавляет source reference к выбранной job.

```json
{
  "version": 1,
  "batch_id": "sha256:...",
  "resolutions": [
    {"line": 6, "candidate": {"line": 5}, "decision": "separate"},
    {"line": 12, "candidate": {"job_id": "job-0042"}, "decision": "duplicate"}
  ]
}
```

CLI отвергает sidecar с другим batch ID, повторной/неприменимой строкой или
кандидатом, которого нет в текущем fuzzy plan. Сначала всегда проверить:

```bash
python3 scripts/jobs.py ingest data/inbox/himalayas-2026-08-11T090000Z.jsonl \
  --resolutions data/inbox/himalayas-2026-08-11T090000Z.resolution.json \
  --dry-run --format json
```

Без `--dry-run` применяется только полностью валидный batch. Замена
`jobs.csv` и `job_sources.csv` выполняется одной rollback-able transaction; при
сбое dataset остаётся прежним. Непроверенная агрегаторная запись создаётся без
application card с `first_party_verified=unknown`, `apply_verified=unknown` и
`next_action=verify first-party`.

## Himalayas discovery

Adapter читает queries, cadence и age window только из `config/sources.toml`.
Он сохраняет один новый immutable raw batch, не вызывает `ingest` и не меняет
canonical CSV:

```bash
# Сначала посмотреть итог fetch без нового файла.
python3 scripts/import_himalayas.py --narrow --dry-run

# Read-only runner/connector artifact: records + run metadata, без canonical write.
python3 scripts/import_himalayas.py --narrow \
  --artifact /tmp/himalayas-discovery.json

# Затем явно сохранить raw batch для ручного контролируемого rollout.
python3 scripts/import_himalayas.py --narrow \
  --output data/inbox/himalayas-2026-08-11T090000Z.jsonl
python3 scripts/inbox.py validate data/inbox/himalayas-2026-08-11T090000Z.jsonl
python3 scripts/jobs.py ingest data/inbox/himalayas-2026-08-11T090000Z.jsonl \
  --dry-run --format json
```

`--broad` выбирает отдельный broad query set, его cadence и fallback age window.
`--output` должен быть новым файлом внутри `data/inbox/`: существующий raw
batch adapter никогда не перезаписывает. Full API job object сохраняется в
`payload.himalayas`; ни `guid`, ни `applicationLink`, ни freshness не считаются
доказательством открытой вакансии.

`--artifact` создаёт immutable JSON artifact в указанном пути и не меняет
checkout или canonical dataset. Он содержит normalized records, summary,
`run_started_at`/`run_finished_at` в UTC и `found_at` по календарю
`Europe/Belgrade`. Workflow `.github/workflows/source-discovery.yml` предоставляет
read-only `workflow_dispatch` для `narrow` и `broad` и загружает artifact на 14
дней.

## Завершённая verification

`verify` — выделенная операция для одной завершённой проверки: она одним
атомарным изменением ставит listing status, оба verification-флага и дату. В той
же операции можно записать подтверждённые `level`, `remote_policy`, `stack`,
`salary` и `match_score`; это безопасные enrichment-поля, не меняющие историю
отклика.
Для подтверждённой открытой вакансии команда переводит `not_started` в
`reviewing`, очищает `verify first-party` и создаёт/синхронизирует карточку:

```bash
python3 scripts/jobs.py verify job-0001 \
  --listing-status open --first-party-verified yes --apply-verified yes \
  --original-url "https://careers.example.com/jobs/frontend" \
  --level Junior --remote-policy Europe --stack "React; TypeScript" \
  --salary "1200 USD/month" --match-score 8.5 --format json
```

Для geo, work-authorization, seniority или другого hard blocker передайте
canonical `--decision-reason`; это сохраняет `not_started` и не создаёт новую
application card. `closed_before_application` требует `--listing-status closed`.

```bash
python3 scripts/jobs.py verify job-0001 \
  --listing-status open --first-party-verified yes --apply-verified yes \
  --original-url "https://careers.example.com/jobs/frontend" \
  --decision-reason geo_restriction
```

Для уже отправленной заявки команда может зафиксировать закрытие объявления
без изменения application history; в этом случае не указывайте
`--decision-reason`.

Если проверка подтверждает, что человек уже начал процесс, но фактической
отправки заявки ещё не было, `verify` может атомарно перевести запись в `apply`
и задать следующий шаг. Значение `applied` эта команда по-прежнему не принимает:

```bash
python3 scripts/jobs.py verify job-0001 \
  --listing-status open --first-party-verified yes --apply-verified yes \
  --application-status apply --next-action "complete AI interview"
```

## Screening decision без verification

`screen` фиксирует решение не откликаться, когда blocker уже виден в discovery
source и нет оснований утверждать, что официальный careers/ATS источник или
Apply были проверены:

```bash
python3 scripts/jobs.py screen job-0099 \
  --decision-reason geo_restriction \
  --notes "Himalayas restricts this role to Latin America." \
  --format json
```

Команда работает только до фактической отправки заявки, переводит запись в
`application_status=not_started`, записывает `decision_reason` и очищает
`next_action`/`next_action_date`. Она намеренно не меняет `listing_status`,
`verified_at`, `first_party_verified` и `apply_verified`. Причины
`closed_before_application` и `duplicate_listing` через `screen` запрещены.

## Подтверждённые lifecycle-события

`status` — ограниченная доменная команда для изменения `application_status`.
Она поддерживает все базовые состояния, управляет обязательными датами и
стадиями и не открывает произвольную запись protected-полей.

При `verify` и lifecycle-обновлениях существующая application card синхронизируется
с canonical записью. Если у legacy card есть корректно ограниченный `---` front
matter, но отсутствуют поля актуального шаблона, write path добавляет их
автоматически и сохраняет остальной текст карточки без изменений.

```bash
# Человек отправил заявку.
python3 scripts/jobs.py status job-0001 \
  --application-status applied --applied-at 2026-08-12 \
  --cv-version frontend-2026-08 --next-action follow-up --format json

# Пришёл отказ по уже существующей заявке.
python3 scripts/jobs.py status job-0001 \
  --application-status rejected --format json

# Начался технический этап.
python3 scripts/jobs.py status job-0001 \
  --application-status interviewing --stage "Tech interview" \
  --next-action "prepare technical interview" --format json
```

Для `applied` недостающий `applied_at` становится сегодняшней датой. Для
`interviewing`, `offer` и `rejected` недостающий `response_at` также становится
сегодняшней датой. Если post-application статус ставится на запись без истории
отклика, нужно явно передать `--applied-at`; это не позволяет случайно выдумать
предыдущую заявку. `ghosted` получает `decision_reason=no_response_timeout`, а
`withdrawn` — `withdrawn_by_me`. Terminal status очищает следующий шаг.

Возврат записи с заполненным `applied_at` в `not_started`, `reviewing` или
`apply` запрещён. Для pre-application отсева по-прежнему используется `screen`.

## Разовый repair старого Himalayas batch

Для 24 screening-записей `job-0099…job-0126`, кроме `job-0102`, `job-0110`,
`job-0111` и `job-0124`, есть отдельная строгая миграция:

```bash
python3 scripts/jobs.py repair-himalayas-screening --check --format json
python3 scripts/jobs.py repair-himalayas-screening --format json
```

Она заменяет только ошибочную verification-разметку `open/no/no/2026-08-11`
на `unknown/unknown/unknown/<empty>`. `decision_reason`, `notes` и все остальные
поля остаются без изменений; четыре исключения не меняются. Команда
идемпотентна, а при частично применённом или неожиданном состоянии прекращает
работу до записи.

## Daily queue, stale и stats

Все три команды только читают canonical dataset. Активной считается запись без
terminal decision, без `listing_status=closed` и без terminal application
outcome (`rejected`, `ghosted`, `withdrawn`). Поэтому legacy duplicates,
закрытые до отклика и pre-application skips не попадают в stale/verification
очереди.

```bash
# Active candidates без проверки или с проверкой старше 7 дней.
python3 scripts/jobs.py stale --days 7 --format json

# Ежедневная очередь; --date делает вывод воспроизводимым.
python3 scripts/jobs.py todo --date 2026-08-11 --format json

# Только Himalayas batch в заданном включительном диапазоне ID.
python3 scripts/jobs.py todo --source Himalayas --id-range job-0099:job-0126 --format json

# Структурированный срез для weekly review.
python3 scripts/jobs.py stats --date 2026-08-11 --format json

# Читаемый Markdown-отчёт из тех же полей.
python3 scripts/jobs.py report --date 2026-08-11
```

`todo` всегда выводит секции в одном порядке: overdue, today, follow-ups,
Apply not submitted, stale review, verification queue и upcoming interview/test.
Внутри секции сортировка стабильна: date → match score (higher first) → id.
По умолчанию stale review использует окно 7 дней; при необходимости его можно
сменить через `--stale-days N` в `todo`, `stats` и `report`.

`todo --source` фильтрует по primary `source` канонической записи; `--id-range`
принимает включительный диапазон `job-NNNN:job-NNNN`. Оба фильтра read-only и
могут использоваться одновременно.

## Browser tracker

`render-tracker` создаёт единственный generated browser view
[`docs/tracker.md`](tracker.md) из `data/jobs.csv`, `data/job_sources.csv` и
существующих application cards. Это read-only projection: команда не меняет
canonical CSV или cards, а сам Markdown нельзя редактировать вручную.

```bash
# Атомарно пересобрать canonical artifact.
python3 scripts/jobs.py render-tracker

# Проверить, что committed artifact совпадает с dataset, ничего не записывая.
python3 scripts/jobs.py render-tracker --check
python3 scripts/jobs.py render-tracker --check --format json
```

Перед рендером команда валидирует dataset. Каждая canonical вакансия попадает
ровно в одну из секций `Action now`, `Applications`, `To verify` или `Archive`;
неизвестная комбинация полей и несколько файлов `applications/<job-id>-*.md`
для одной вакансии — hard failure. `--check` завершится с кодом `1`, если
`docs/tracker.md` отсутствует или отличается хотя бы одним байтом. JSON-ответ
содержит один object с `ok`, `command`, `path`, `up_to_date` и counts секций.
Повторная генерация на тех же input bytes детерминирована, а запись проходит
через temporary file и `os.replace`.

## Удалённые агенты и GitHub connector

GitHub connector может создавать только один новый immutable request в
`data/operations/requests/` за commit. Он не является write path для
`data/jobs.csv`, `data/job_sources.csv`, application cards или
`docs/tracker.md`: прямой `update_file` обходил бы dedupe, validation,
атомарность и generated-view contract.

Trusted GitHub Actions runner принимает request только из `main` (после явной
команды пользователя) или `agent/*` (review mode), применяет его через
`scripts/agent_operations.py` и те же функции `jobs.py`, затем создаёт
immutable result. После strict validation runner пересобирает и exact-checks
`docs/tracker.md`, запускает unit tests, проверяет changed-file allowlist и
коммитит результат. В review mode он открывает PR в `main`. Полная схема,
allowed commands, optimistic locking и branch policy находятся в
[`data/operations/README.md`](../data/operations/README.md).

Операция завершена только после matching result и canonical diff/PR. Connector
не должен включать generated tracker в request: его создаёт только trusted
runner.

`stats --format json` — единственный структурированный источник weekly report:
он содержит основной `derived_state`, split application/listing statuses,
derived active/skipped/closed views, verification coverage, stale records,
funnel по `stage_reached` и response rate по `applied_at`, а также source и
CV-version breakdowns. `report` ничего не записывает: он только рендерит этот
snapshot в Markdown. В отчёте первым показывается человеческий derived state
(`Skipped: geo_restriction`, `Closed`, `Reviewing`, `Apply`, `Applied` и
остальные lifecycle states), а `listing_status` выводится отдельно как свойство
объявления.

## Примеры обновления и проверки

```bash
python3 scripts/jobs.py set job-0001 listing_status=closed --format json
python3 scripts/jobs.py validate --strict --format json
python3 scripts/jobs.py dupes --fail --format json
```
