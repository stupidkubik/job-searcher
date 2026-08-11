# Правила работы с этим репозиторием

Это личный трекер поиска работы. Единственный структурированный источник истины —
`data/jobs.csv`. Схема и допустимые значения: `data/schema.md`. Профиль кандидата:
`config/profile.md`.

## Перед любым поиском вакансий

1. Прочитать `data/jobs.csv` целиком.
2. Прочитать `config/profile.md` (приоритеты, гео, стек, компенсация).
3. Только потом искать новое.

Не анализировать заново вакансию, которая уже есть в CSV. Если её
`application_status=applied` / `rejected` — не откликаться повторно; для
вычисляемого `Skipped` сначала прочитать `decision_reason`; запись с
`listing_status=closed` без отклика пропустить; `not_started` / `reviewing` /
`apply` продолжать с предыдущего шага.

## Железные правила

- **Ни одна найденная вакансия не остаётся без записи.** Закрытая, не подходящая,
  слишком senior, с гео-ограничением — всё равно строка в CSV. Это защита от
  повторного анализа того же самого через неделю.
- **Агрегатор не определяет актуальность.** Перед полным анализом открыть
  первоисточник (careers page, Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Teamtailor, BambooHR, Comeet). Закрыто в первоисточнике =
  закрыто, независимо от статуса на агрегаторе.
- **`Remote` сам по себе не значит global remote.** Проверять текст вакансии на
  ограничения по стране и work authorization. Не уверен → `remote_policy=Unclear`.
- **`application_status=applied` ставится только после фактической отправки
  заявки человеком.** Агент не отправляет отклики и не ставит `applied`
  самостоятельно.
- **Никогда не выдумывать факты о кандидате.** Метрики, должности, стек, срок
  опыта — только из `config/profile.md`. Нет доказательства → не писать.

## Как писать в CSV

- Только через `scripts/jobs.py` (`add` / `set` / `backfill-sources`). Ручная
  правка canonical CSV — исключение.
- Значения полей — по-английски и строго из enum в `data/schema.md`.
- `id` неизменяем после создания.
- `data/job_sources.csv` — provenance каждой вакансии. Для нового внешнего
  источника передавать `--source-url` или `--source-job-id`; без reference
  допустимы только `Manual` и `Referral`.
- Подтверждённый дубль создавать только через `add --duplicate-of job-NNNN`:
  команда добавляет source reference к canonical job и не создаёт новый ID.
  `--force` означает, что совпадающий URL — осознанно shared discovery page или
  похожая запись является отдельной вакансией.
- Никаких переводов строк в ячейках. Длинный текст → `applications/<id>.md`.
- Разделитель в `stack` — `; `, не запятая.
- После любых изменений: `python3 scripts/jobs.py validate` — должно быть 0 ошибок.

## Порядок обработки одной вакансии

1. Проверить дубли: сначала `data/job_sources.csv` по `source + source_job_id`,
   затем `original_url`, source URL и company + role.
2. Открыть первоисточник, проверить доступность вакансии и работу кнопки Apply;
   записать `listing_status`, `first_party_verified`, `apply_verified` и дату
   проверки через CLI.
3. Если есть hard blocker (гео, work authorization, seniority), сразу выполнить
   `add --application-status not_started --decision-reason <причина> --no-file` и
   не проводить полный анализ. Для закрытого объявления использовать
   `--listing-status closed --decision-reason closed_before_application` вместо
   обычной причины отсева.
4. Если фильтр пройден, провести полный анализ, присвоить `match_score` от 1 до 10,
   поставить `application_status=reviewing` и заполнить `applications/<id>.md`.
5. Принять решение `apply` или вычисляемое `Skipped` / `Closed` через
   структурированные поля.
6. Подготовить материалы: CV только из `cv/current/`, cover letter и ответы формы.
7. Человек отправляет заявку; только после этого выполнить
   `set <id> application_status=applied cv_version=...`.

## Файлы

| Задача | Файл |
|---|---|
| структурированные данные | `data/jobs.csv` |
| provenance источников | `data/job_sources.csv` |
| длинный контекст по вакансии | `applications/<id>.md` из `_TEMPLATE.md` |
| профиль, приоритеты, доказательства | `config/profile.md` |
| резюме для отправки | `cv/current/` — только оттуда |
| шаблоны сообщений | `templates/outreach.md` |
| недельный отчёт | `reports/weekly/YYYY-Wxx.md` |

Не создавать новые файлы в корне. Не менять схему CSV без обновления
`data/schema.md` и `scripts/jobs.py` в том же коммите.

## Коммиты

Одна логическая операция = один коммит. Формат:

```text
jobs: add job-0042 SomeCo Frontend Developer (Reviewing)
jobs: job-0031 -> Applied
report: week 2026-W32
```
