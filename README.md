# Job Search Tracker

Личный Git-трекер поиска frontend-ролей. Он сохраняет каждую найденную вакансию,
предотвращает повторный анализ и позволяет видеть, какие источники, версии CV и
типы ролей приносят ответы.

Главный принцип: **ни одна найденная вакансия не исчезает без записи**.

## Ежедневная работа в браузере

Откройте [Job tracker](docs/tracker.md) в GitHub: это основное read-only
представление активных действий, откликов, verification queue и архива. Страница
генерируется из canonical dataset и не редактируется вручную. Для изменения
состояния сообщите агенту job ID и новое состояние; trusted workflow обновит
`data/jobs.csv` и tracker в одном commit/PR.

## Быстрый старт

Перед поиском прочитайте [профиль кандидата](config/profile.md) и весь
[`data/jobs.csv`](data/jobs.csv). Затем добавляйте вакансии только через CLI:

```bash
# Найденная вакансия, которую нужно изучить
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source LinkedIn \
  --source-url "https://www.linkedin.com/jobs/view/123" \
  --application-status reviewing --listing-status open \
  --original-url "https://careers.example.com/jobs/frontend" \
  --first-party-verified yes --apply-verified yes

# После фактической отправки заявки человеком
python3 scripts/jobs.py status job-0001 \
  --application-status applied --applied-at 2026-08-12 \
  --cv-version frontend-2026-08

# После любого изменения
python3 scripts/jobs.py validate
```

Для неподходящей или закрытой позиции всё равно создаётся запись, например:

```bash
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source Hirify \
  --source-url "https://hirify.example/jobs/123" \
  --application-status not_started --decision-reason geo_restriction --no-file
```

## Где что находится

| Что | Где |
|---|---|
| правила работы ИИ-агента | [AGENTS.md](AGENTS.md) |
| основной browser UI | [docs/tracker.md](docs/tracker.md) |
| профиль, приоритеты и доказательства | [config/profile.md](config/profile.md) |
| поисковые запросы | [config/search-queries.md](config/search-queries.md) |
| playbooks по ATS и источникам | [docs/sources/](docs/sources/) |
| canonical storage вакансий | [data/jobs.csv](data/jobs.csv) |
| provenance источников | [data/job_sources.csv](data/job_sources.csv) |
| поля и допустимые значения | [data/schema.md](data/schema.md) |
| подробности по вакансии | [applications/](applications/) |
| актуальные версии резюме | [cv/current/](cv/current/) |
| шаблоны писем | [templates/](templates/) |
| отчёты | [reports/](reports/) |
| historical architecture research | [docs/architecture.md](docs/architecture.md) |
| дальнейшие улучшения | [docs/roadmap.md](docs/roadmap.md) |
| подробный план Tracker v2 | [docs/tracker-v2-plan.md](docs/tracker-v2-plan.md) |
| connector → tracker operation gateway | [data/operations/README.md](data/operations/README.md) |

## Правила в двух словах

- Сначала проверяйте дубли: `original_url`, затем компания + роль, затем похожие
  названия в одной компании.
- Агрегатор нужен для поиска, но актуальность, географию и Apply нужно проверять
  только на первоисточнике работодателя или ATS.
- `Remote` не означает global remote: при неясности используйте
  `remote_policy=Unclear`.
- `application_status=applied` ставится только после реальной отправки человеком.
- `listing_status` описывает доступность объявления отдельно от истории отклика;
  проверка первоисточника и Apply хранится в отдельных полях.
- Длинный контекст храните в `applications/<id>.md`; CSV остаётся однострочным и
  аналитическим.

Полные обязательные правила — в [AGENTS.md](AGENTS.md), а точная схема — в
[data/schema.md](data/schema.md).

## Проверка

```bash
python3 scripts/jobs.py validate
python3 scripts/jobs.py render-tracker --check
python3 -m unittest discover -s tests -v
python3 scripts/jobs.py dupes
```

GitHub Actions запускает эти проверки на `main`, `codex/restructure` и pull request.
