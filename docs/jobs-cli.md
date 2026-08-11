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
reference к уже существующей canonical вакансии. Команда идемпотентна. Если
нормализованный `source_url` уже привязан к другой вакансии, CLI завершится с
кодом `2`; `--force` — явное разрешение для shared discovery page.

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

`add`, `set`, `screen`, `verify`, `validate`, `dupes`, `ingest`, `stale`, `todo`
и `stats` поддерживают `--format text|json`; по умолчанию — `text`. Успешный
JSON-ответ состоит ровно из одного object с `ok`,
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

## Удалённые агенты и GitHub connector

GitHub connector может читать и изменять файлы, но не исполняет `jobs.py` в
checkout приватного репозитория. Поэтому он не является write path для
`data/jobs.csv` или `data/job_sources.csv`: прямой `update_file` обходил бы
dedupe, validation и атомарность. Удалённый агент может подготовить raw batch
или предложение изменения, а canonical write выполняет агент с рабочим
checkout через `jobs.py`; затем CI валидирует итоговый dataset. CI проверяет
состояние файлов, но не может доказать, какой инструмент их записал.

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
