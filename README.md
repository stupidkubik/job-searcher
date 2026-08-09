# Job Search Tracker

Личный Git-трекер поиска frontend-ролей. Он сохраняет каждую найденную вакансию,
предотвращает повторный анализ и позволяет видеть, какие источники, версии CV и
типы ролей приносят ответы.

Главный принцип: **ни одна найденная вакансия не исчезает без записи**.

## Быстрый старт

Перед поиском прочитайте [профиль кандидата](config/profile.md) и весь
[`data/jobs.csv`](data/jobs.csv). Затем добавляйте вакансии только через CLI:

```bash
# Найденная вакансия, которую нужно изучить
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source LinkedIn \
  --status Reviewing

# После фактической отправки заявки человеком
python3 scripts/jobs.py set job-0001 \
  status=Applied cv_version=frontend-2026-08

# После любого изменения
python3 scripts/jobs.py validate
```

Для неподходящей или закрытой позиции всё равно создаётся запись, например:

```bash
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source Hirify \
  --status Skipped --decision-reason geo_restriction --no-file
```

## Где что находится

| Что | Где |
|---|---|
| правила работы ИИ-агента | [AGENTS.md](AGENTS.md) |
| профиль, приоритеты и доказательства | [config/profile.md](config/profile.md) |
| поисковые запросы | [config/search-queries.md](config/search-queries.md) |
| единый реестр вакансий | [data/jobs.csv](data/jobs.csv) |
| поля и допустимые значения | [data/schema.md](data/schema.md) |
| подробности по вакансии | [applications/](applications/) |
| актуальные версии резюме | [cv/current/](cv/current/) |
| шаблоны писем | [templates/](templates/) |
| отчёты | [reports/](reports/) |
| архитектурные решения | [docs/architecture.md](docs/architecture.md) |
| дальнейшие улучшения | [docs/roadmap.md](docs/roadmap.md) |

## Правила в двух словах

- Сначала проверяйте дубли: `original_url`, затем компания + роль, затем похожие
  названия в одной компании.
- Агрегатор нужен для поиска, но актуальность, географию и Apply нужно проверять
  только на первоисточнике работодателя или ATS.
- `Remote` не означает global remote: при неясности используйте
  `remote_policy=Unclear`.
- `Applied` ставится только после реальной отправки человеком.
- Длинный контекст храните в `applications/<id>.md`; CSV остаётся однострочным и
  аналитическим.

Полные обязательные правила — в [AGENTS.md](AGENTS.md), а точная схема — в
[data/schema.md](data/schema.md).

## Проверка

```bash
python3 scripts/jobs.py validate
python3 -m unittest discover -s tests -v
python3 scripts/jobs.py dupes
```

GitHub Actions запускает эти проверки на `main`, `codex/restructure` и pull request.
