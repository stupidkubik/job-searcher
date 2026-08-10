# Схема `jobs.csv`

`data/jobs.csv` — единственный структурированный источник истины: одна строка =
одна уникальная вакансия. Все значения в CSV пишутся на английском. Порядок
колонок фиксирован и проверяется `python3 scripts/jobs.py validate`.
Первые две колонки — `id`, затем `status`, чтобы состояние вакансии было видно
без горизонтальной прокрутки.

## Обязательные поля при создании

`id`, `company`, `role`, `source`, `found_at`, `status`, `stage_reached`,
`last_update`.

## Поля

| Поле | Формат | Правило |
|---|---|---|
| `id` | `job-NNNN` | Неизменяемый идентификатор; выдаётся `jobs.py add`. |
| `company`, `role`, `location`, `salary` | текст | Компания и роль — как в первоисточнике. Для неизвестной зарплаты — `Unknown`. |
| `level` | enum | См. допустимые значения. |
| `original_url`, `source_url`, `contact_url` | URL | `original_url` — ATS/careers, главный ключ дедупликации; `source_url` — место находки. |
| `source` | enum | Источник для аналитики. |
| `remote_policy` | enum | `Remote` сам по себе не означает `Global`. |
| `stack` | текст | Технологии через `; `, не запятую. |
| `posted_at`, `found_at`, `applied_at`, `response_at`, `next_action_date`, `last_update` | `YYYY-MM-DD` | `last_update` меняется при каждом обновлении строки. |
| `match_score` | `1`–`10` | Допускаются десятичные значения, например `7.5`. |
| `status` | enum | Текущее состояние вакансии. |
| `stage_reached` | упорядоченный enum | Максимально достигнутая стадия; может только расти. |
| `decision_reason` | enum | Обязателен для `Skipped`, `Closed`, `Duplicate`, `Withdrawn`. |
| `next_action` | короткий текст | Например: `follow-up`, `prepare test task`. |
| `cv_version` | slug | Соответствует значению из `cv/current/README.md`. |
| `cover_letter` | `no` или путь | Например: `cv/cover-letters/job-0001-exequt.md`. |
| `contact_name` | текст | Рекрутёр или сотрудник. |
| `notes` | одна строка | Без переводов строк; длинный текст — в `applications/<id>.md`. |

## Допустимые значения

| Поле | Значения |
|---|---|
| `level` | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Unknown` |
| `source` | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Himalayas`, `Startit Jobs`, `Company Careers`, `Referral`, `Manual`, `Other` |
| `remote_policy` | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` |
| `status` | `New`, `Reviewing`, `Apply`, `Applied`, `Interviewing`, `Offer`, `Rejected`, `Ghosted`, `Skipped`, `Closed`, `Duplicate`, `Withdrawn` |
| `stage_reached` | `None` → `Applied` → `Recruiter screen` → `Tech interview` → `Test task` → `Final interview` → `Offer` |
| `decision_reason` | `geo_restriction`, `work_authorization`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `role_not_frontend`, `salary_too_low`, `company_not_interesting`, `closed_before_application`, `already_applied`, `duplicate_listing`, `no_response_timeout`, `withdrawn_by_me`, `other` |

## Инварианты

- `applied_at` обязателен для `Applied`, `Interviewing`, `Offer`, `Rejected`, `Ghosted`, `Withdrawn` и ставится только после фактической отправки.
- `response_at` обязателен для `Interviewing`, `Offer`, `Rejected`.
- Для `decision_reason=other` требуется пояснение в `notes`.
- Для `Duplicate` в `notes` указывается ID оригинальной записи.
- `status` описывает текущее положение, а `stage_reached` — самый высокий пройденный этап. Например, `Rejected` + `Final interview` означает отказ после финального интервью.
