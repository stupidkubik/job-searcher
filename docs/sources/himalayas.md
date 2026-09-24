# Himalayas search playbook

Checked: 2026-08-14

Official references:

- [Himalayas API](https://himalayas.app/api)
- [Remote Jobs API](https://himalayas.app/docs/remote-jobs-api)
- [OpenAPI schema](https://himalayas.app/docs/openapi.json)
- [Data dictionary](https://himalayas.app/docs/data-dictionary)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Машинные cadence,
geo, age windows и query sets определены в
[`config/sources.toml`](../../config/sources.toml).

## Роль и доступ

Himalayas — remote-job aggregator с публичным JSON API и локальным fetch-only
adapter. Для tracker использовать `source=Himalayas`; API и adapter дают только
discovery evidence. `applicationLink` не копируется в `original_url` до
first-party verification.

API обновляется примерно раз в сутки. Соблюдать rate limit и делать bounded
backoff при HTTP 429/temporary 5xx.

## Routes: narrow → broad

```text
GET https://himalayas.app/jobs/api?offset=<n>&limit=<max-20>
GET https://himalayas.app/jobs/api/search?q=<query>&page=<n>
```

Search поддерживает `country`, `worldwide`, `exclude_worldwide`, `seniority`,
`employment_type`, `company`, `timezone` и `sort=recent`. Boolean syntax внутри
`q` не считать поддержанной без новой документации.

Adapter [`scripts/import_himalayas.py`](../../scripts/import_himalayas.py):

- `--narrow` — default query set, 24-hour cadence, 7-day window;
- `--broad` — fallback set, 72-hour cadence, 30-day window;
- каждый query/geo pass начинается с page 1 и идёт до `totalCount`/`limit`;
- Serbia использует `country=Serbia&exclude_worldwide=true`, Worldwide —
  `worldwide=true`, Europe — unscoped pages с локальным geo filter;
- same-run records дедуплицируются по `guid`.

Adapter пишет только новый immutable JSONL в `data/inbox/` или read-only
artifact; canonical решение, geo screening и ingest он не выполняет.

`--artifact` сохраняет outcome даже при неуспешном запросе. `success` означает
завершённый проход с записями, `zero_results` — завершённый проход без
подходящих записей, `partial` — ошибки отдельных карточек. HTTP 401/403/429
получают `auth_required`/`blocked`/`rate_limited`; ошибки транспорта и 5xx —
`request_failed`, неверный ответ или pagination — `parse_error`. Неуспешный
проход выходит с кодом 1, а artifact помечает `complete=false`; `summary=null`
при ошибке до завершения сбора, поэтому ноль в нём не маскирует сбой.
Artifact также содержит выбранные запросы, версию адаптера, UTC-время и
длительность. Он остаётся discovery evidence и не меняет статус вакансий.

## Exact identity и original source

| Значение | Правило |
|---|---|
| stable `source_job_id` | `guid` |
| `source_url` | exact Himalayas job card |
| candidate employer URL | `applicationLink`, хранить отдельно как unverified |
| `original_url` | только проверенная exact employer/ATS listing |

Одна вакансия может появиться в нескольких query/geo passes. Совпадающий `guid`
— одна source card; разные GUID с одной подтверждённой requisition становятся
references одной canonical job.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| `pubDate` | source publication date | employer listing всё ещё open |
| `expiryDate` в будущем | source-side freshness hint | canonical open status |
| `applicationLink` | кандидат на Apply/original route | first-party ownership или live exact form |
| карточка отсутствует из feed | source-side removal | canonical employer closure без проверки |

Реальные false positives уже наблюдались: свежие worldwide cards с будущим
`expiryDate` вели к ролям, отсутствовавшим на текущей board работодателя.

## Trust и ловушки

- `locationRestrictions` и `timezoneRestriction` пригодны для discovery, но
  требуют сверки с описанием и employer form.
- `minSalary`/`maxSalary` использовать только вместе с currency и period.
- `description` может быть stale относительно first-party текста.
- API freshness и наличие ссылки не должны выставлять verification fields.
- Первый ingest каждого нового raw batch обязательно dry-run; fuzzy candidates
  требуют явного resolution по общему contract.

## Stop rule

Pass завершён после полной пагинации всех query × geo combinations из registry,
локального age filter и dedupe по `guid`. Search-source обработка завершена
только после immutable outcomes для всех открытых exact cards.
