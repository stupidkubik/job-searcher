# Raw inbox (`data/inbox/`)

`data/inbox/` — локальная очередь **неизменяемых** результатов discovery до
нормализации, фильтрации, дедупликации и проверки первоисточника. Это не второй
источник истины: canonical facts появляются только после следующего шага через
`scripts/jobs.py`.

Рабочие `*.jsonl` намеренно игнорируются Git. Для тестов допускаются только
небольшие обезличенные fixtures в `tests/fixtures/inbox/`.

## Lifecycle

1. Adapter записывает новый batch отдельным UTF-8 JSONL-файлом, например
   `himalayas-2026-08-11T090000Z.jsonl`.
2. Adapter больше не меняет этот файл. Повторный fetch создаёт новый batch.
3. Перед ingest файл проверяется командой ниже. Она только читает вход и не
   исправляет его на месте.
4. Phase 4 классифицирует записи и передаёт изменения в `scripts/jobs.py`.
   Нельзя писать из adapter напрямую в `data/jobs.csv` или
   `data/job_sources.csv`.

## Canonical record

Каждая непустая физическая строка должна быть одним JSON object в UTF-8 и иметь
ровно следующие обязательные поля:

```json
{"source":"Himalayas","source_job_id":"abc","company":"Example","role":"Frontend Developer","source_url":"https://...","application_url":"https://...","posted_at":"2026-08-11","raw_location":"Worldwide","found_at":"2026-08-11"}
```

| Поле | Правило |
|---|---|
| `source` | Непустая строка, имя включённого источника из `config/sources.toml`. |
| `source_job_id` | Непустой стабильный ID карточки внутри источника. |
| `company`, `role`, `raw_location` | Непустые строки как их отдал источник; не нормализовать в raw inbox. |
| `source_url`, `application_url` | Непустые абсолютные `http`/`https` URL; они ещё не подтверждают first-party status. |
| `posted_at`, `found_at` | Непустые даты строго формата `YYYY-MM-DD`. |
| `payload` | Необязательный JSON object для source-specific полей; других top-level полей нет. |

Не добавляйте `batch_id` в запись и тем более в `jobs.csv`. Валидатор вычисляет
его из SHA-256 точных байтов batch-файла и возвращает только в runtime summary:

```bash
python3 scripts/inbox.py validate data/inbox/himalayas-2026-08-11T090000Z.jsonl
```

Успешный вывод — один JSON object с `batch_id`, числом `records` и пустым
`errors`. Один и тот же неизменённый файл всегда даёт тот же `batch_id`.
