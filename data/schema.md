# Схема `jobs.csv` (Tracker v2)

`data/jobs.csv` — canonical источник истины: одна строка = одна уникальная
вакансия и история нашей работы с ней. `data/job_sources.csv` — вспомогательная
many-to-one таблица provenance; она не содержит самостоятельных job/application
facts и не существует без строки в `jobs.csv`. Все значения в CSV пишутся на
английском, кроме `company` и `role` — они сохраняются как в первоисточнике
(см. таблицу полей ниже). Обе таблицы проверяются
`python3 scripts/jobs.py validate`.

Первые три колонки — `id`, `application_status`, `listing_status`: состояние
нашей заявки и состояние объявления хранятся независимо.

## Порядок колонок

```text
id,application_status,listing_status,company,role,level,original_url,source_url,source,location,remote_policy,stack,salary,posted_at,found_at,match_score,stage_reached,decision_reason,applied_at,response_at,next_action,next_action_date,cv_version,cover_letter,contact_name,contact_url,verified_at,first_party_verified,apply_verified,last_update,notes
```

## Обязательные поля

`id`, `company`, `role`, `source`, `found_at`, `application_status`,
`listing_status`, `stage_reached`, `first_party_verified`, `apply_verified`,
`last_update`.

## Поля

| Поле | Формат | Правило |
|---|---|---|
| `id` | `job-NNNN` | Неизменяемый идентификатор; выдаётся `jobs.py add`. |
| `application_status` | enum | Состояние нашего решения или отклика; не описывает доступность объявления. |
| `listing_status` | enum | Состояние объявления на момент последней проверки; не затирает историю отклика. |
| `company`, `role`, `location`, `salary` | текст | Компания и роль — как в первоисточнике. Для неизвестной зарплаты — `Unknown`. |
| `level` | enum | См. допустимые значения. |
| `original_url`, `source_url`, `contact_url` | URL | `original_url` — официальный ATS/careers URL и главный ключ дедупликации; `source_url` — место находки. |
| `source` | enum | Первичный источник для аналитики и обратной совместимости. Полная provenance хранится в `data/job_sources.csv`. |
| `remote_policy` | enum | `Remote` сам по себе не означает `Global`. |
| `stack` | текст | Технологии через `; `, не запятую. |
| `posted_at` | `YYYY-MM-DD` | Дата публикации из источника; не переинтерпретируется как локальный timestamp. |
| `found_at`, `applied_at`, `response_at`, `next_action_date`, `verified_at`, `last_update` | `YYYY-MM-DD` | Календарные tracker-даты считаются в `Europe/Belgrade`. `verified_at` — дата последней проверки первоисточника/Apply; `last_update` меняется при каждом обновлении строки. Точные audit/run timestamps хранятся отдельно в UTC. |
| `match_score` | `1`–`10` | Допускаются десятичные значения, например `7.5`. |
| `stage_reached` | упорядоченный enum | Максимально достигнутая стадия; может только расти. |
| `decision_reason` | enum | Причина отсева или завершения; для `other` требуется пояснение в `notes`. |
| `first_party_verified` | enum | Проверен официальный careers/ATS источник. Исторические строки без структурированного доказательства получают `unknown`. |
| `apply_verified` | enum | Проверено, что Apply доступен и принимает заявки. |
| `next_action` | короткий текст | Например: `verify first-party`, `follow-up`, `prepare test task`. |
| `cv_version` | необязательный slug | Соответствует значению из `cv/current/README.md`; если версия не была зафиксирована, оставить поле пустым. В отчёте это отображается как `not recorded`. |
| `cover_letter` | `no` или путь | Например: `cv/cover-letters/job-0001-exequt.md`. |
| `contact_name` | текст | Рекрутёр или сотрудник. |
| `notes` | одна строка | Без переводов строк; длинный текст — в `applications/<id>.md`. |

## Допустимые значения

| Поле | Значения |
|---|---|
| `application_status` | `not_started`, `reviewing`, `apply`, `applied`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn` |
| `listing_status` | `open`, `closed`, `unknown` |
| `first_party_verified`, `apply_verified` | `yes`, `no`, `unknown` |
| `level` | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Unknown` |
| `source` | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Himalayas`, `Startit Jobs`, `Company Careers`, `Referral`, `Manual`, `Other` |
| `remote_policy` | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` |
| `stage_reached` | `None` → `Applied` → `Recruiter screen` → `Tech interview` → `Test task` → `Final interview` → `Offer` |
| `decision_reason` | `geo_restriction`, `work_authorization`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `role_not_frontend`, `salary_too_low`, `company_not_interesting`, `closed_before_application`, `already_applied`, `duplicate_listing`, `no_response_timeout`, `withdrawn_by_me`, `other` |

## Детерминированная миграция v1 → v2

Миграция не извлекает факты из свободного текста. Для каждой исторической строки
она ставит `verified_at=""`, `first_party_verified=unknown` и
`apply_verified=unknown`.

| v1 `status` | v2 `application_status` | v2 `listing_status` | Сохраняемое правило |
|---|---|---|---|
| `New` | `not_started` | `unknown` | — |
| `Reviewing` | `reviewing` | `unknown` | — |
| `Apply` | `apply` | `unknown` | — |
| `Applied` | `applied` | `unknown` | `applied_at` |
| `Interviewing` | `interviewing` | `unknown` | даты и `stage_reached` |
| `Offer` | `offer` | `unknown` | даты и `stage_reached` |
| `Rejected` | `rejected` | `unknown` | историю отклика |
| `Ghosted` | `ghosted` | `unknown` | историю отклика |
| `Withdrawn` | `withdrawn` | `unknown` | `decision_reason` |
| `Skipped` | `not_started` | `unknown` | `decision_reason` |
| `Closed` | `not_started` | `closed` | `decision_reason=closed_before_application` |
| `Duplicate` | `not_started` | `unknown` | `decision_reason=duplicate_listing` и legacy-ссылку на оригинал |

## Вычисляемые представления

`Skipped`, `Closed` и `Duplicate` больше не являются значениями lifecycle.
Они вычисляются из структурированных полей:

| Представление | Условие |
|---|---|
| Duplicate (только legacy row) | `decision_reason=duplicate_listing` |
| Closed before application | `listing_status=closed` и `application_status=not_started` |
| Skipped | `application_status=not_started`, заполнена причина и она не `duplicate_listing`/`closed_before_application` |
| Active candidate | нет terminal decision и `listing_status` не `closed` |

`stats` и `report` используют эти правила для основного `derived_state`:
например, `Skipped: geo_restriction`, `Closed`, `Reviewing`, `Apply` или
`Applied`. `listing_status` остаётся отдельным свойством объявления и не
заменяет человеческий статус решения/отклика.

## Source references: `data/job_sources.csv`

```text
job_id,source,source_url,source_job_id,found_at
```

| Поле | Правило |
|---|---|
| `job_id` | Обязательный foreign key на существующий `jobs.csv:id`. |
| `source` | Тот же source enum, что в `jobs.csv`. |
| `source_url` | URL конкретной карточки или discovery page; нужен `source_url` или `source_job_id`. |
| `source_job_id` | Стабильный ID карточки внутри источника, если он известен. |
| `found_at` | Обязательная дата первого обнаружения reference по календарю `Europe/Belgrade`, `YYYY-MM-DD`. |

Пара `source + source_job_id` уникальна во всём dataset. Нормализованный
`source_url` проверяется при записи: совпадение с другой canonical job требует
явный `--force`, поскольку discovery page иногда действительно содержит несколько
вакансий. Backfill исторических общих Wellfound discovery URL уже выполнил такое
явное разрешение; это не влияет на уникальность stable source IDs.

Для новой вакансии с внешним источником `jobs.py add` создаёт первичную source
reference в той же операции. Нужен `--source-url` или `--source-job-id`; без
reference допустимы только `Manual` и `Referral`. `--duplicate-of JOB_ID` больше
не создаёт новый job ID: он добавляет source reference к canonical `JOB_ID` и
идемпотентно завершается, если такая reference уже существует.

## Инварианты

- `applied`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn` требуют `applied_at`.
- `interviewing`, `offer`, `rejected` требуют `response_at`.
- `listing_status=closed` не меняет `application_status` автоматически: закрытие после отклика сохраняет историю заявки.
- Любая CLI-правка `listing_status`, `first_party_verified` или `apply_verified` обновляет `verified_at`; историческая миграция дату не выдумывает.
- `first_party_verified=yes` требует непустой валидный `original_url`.
- `apply_verified=yes` требует `first_party_verified=yes` и `verified_at`.
- `first_party_verified=yes|no` или `apply_verified=yes|no` требует `verified_at`.
- Для `decision_reason=closed_before_application` обязательны `listing_status=closed` и пустой `applied_at`.
- Pre-application причина отсева требует `application_status=not_started`.
- `decision_reason` несовместим с `application_status=reviewing` и `apply`: любое завершённое решение хранится как `not_started` с причиной. Иначе строка описывает одновременно «работа идёт» и «работа прекращена» и не попадает ни в одно представление.
- `listing_status=closed` до отклика требует `application_status=not_started` и `decision_reason=closed_before_application`. Для записи в `reviewing`/`apply` закрытие объявления фиксируется через `verify --listing-status closed --decision-reason closed_before_application`, а не через `set`.
- Legacy `decision_reason=duplicate_listing` требует `application_status=not_started` и ID оригинальной строки в `notes`; новые duplicate rows прекращаются после появления source references в Phase 3.
- Каждая source reference ссылается на существующий `jobs.csv:id`; её `source + source_job_id` не может принадлежать второй вакансии.
- `validate` проверяет `jobs.csv` и `job_sources.csv` как единый dataset.
- `stage_reached` не понижается и остаётся независимой исторической метрикой.
- `application_status=applied` ставится только после фактической отправки человеком.

## Примеры CLI

```bash
# Проверенная открытая вакансия, которую нужно разобрать
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source LinkedIn \
  --source-url "https://www.linkedin.com/jobs/view/123" \
  --application-status reviewing --listing-status open \
  --original-url "https://careers.example.com/jobs/frontend" \
  --first-party-verified yes --apply-verified yes

# Первичный источник закрылся до отклика
python3 scripts/jobs.py set job-0001 \
  listing_status=closed decision_reason=closed_before_application

# Человек фактически отправил заявку
python3 scripts/jobs.py status job-0001 \
  --application-status applied --cv-version frontend-2026-08

# Подтверждённый duplicate: новая job-строка не создаётся
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source LinkedIn \
  --source-url "https://www.linkedin.com/jobs/view/another-location" \
  --duplicate-of job-0001 --no-file

# После любого изменения
python3 scripts/jobs.py validate --strict
```
