# Roadmap

## v1 — завершено

Базовый журнал уже работает: canonical `data/jobs.csv`, карточки
`applications/*.md`, безопасная запись через `scripts/jobs.py`, дедупликация,
отчёт и CI.

## v2 — запланировано

Подробная исполнимая спецификация с миграцией, зависимостями, артефактами,
acceptance criteria и Definition of Done находится в
[`tracker-v2-plan.md`](tracker-v2-plan.md). Исходная обратная связь сохранена в
[`tracker-v2-feedback.md`](tracker-v2-feedback.md).

| Phase | Результат |
|---:|---|
| 0 | Зафиксирован контракт v2. |
| 1 | Разделены listing/application status и мигрированы данные. |
| 2 | Ручной CLI и JSON используют единый write path. |
| 3 | Созданы source registry, `job_sources.csv` и raw inbox contract. |
| 4 | Работает универсальный атомарный ingestion engine. |
| 5 | Подключён и проверен Himalayas adapter. |
| 6 | Работают `todo`, `stale`, stats и weekly reports. |
| 7 | После стабилизации добавляются новые adapters и необязательная аналитика. |

## Позже, только при подтверждённой необходимости

- dashboard или другой UI;
- SQLite/Postgres;
- GitHub Issues как intake layer;
- автоматическая отправка заявок.

Эти пункты не входят в Tracker v2 и не должны опережать стабилизацию ingestion
pipeline.
