# Tracker v3 planning workspace

Статус: active design workspace on branch `codex/tracker-v3`.

> Эти документы описывают подготовку и рекомендуемую последовательность работ.
> Они не заменяют `AGENTS.md`, `data/schema.md`, operation contract или текущую
> архитектуру, пока соответствующее решение не принято и не реализовано.

## Цель workspace

Подготовить следующую версию трекера без преждевременного переписывания
работающей системы. V3 должна добавить память о событиях после отклика,
воспроизводимые application packets и доказательный анализ соответствия,
сохранив сильные стороны текущего проекта:

- Git-аудируемый canonical state;
- `jobs.csv` как компактный текущий snapshot;
- many-to-one provenance в `job_sources.csv`;
- first-party verification;
- один авторизованный write path;
- человеческое подтверждение lifecycle-событий и отправки заявки;
- fail-closed validation и deterministic generated views.

Основание:

- [`../deep-research-report.md`](../deep-research-report.md) — углублённый аудит
  и конкретные рекомендации;
- [`../github-job-tracker-inspiration-analysis-2026-09-22.md`](../github-job-tracker-inspiration-analysis-2026-09-22.md) — первый широкий обзор;
- [`../current-architecture.md`](../current-architecture.md) — работающая
  архитектура, которую v3 пока не отменяет;
- [`../../data/schema.md`](../../data/schema.md) и
  [`../../data/operations/contract.md`](../../data/operations/contract.md) —
  действующие контракты.

## Документы инициативы

| Документ | Роль | Как обновляется |
|---|---|---|
| [`implementation-plan.md`](implementation-plan.md) | последовательность фаз, зависимости, gates, migration и rollout | при изменении scope или порядка работ |
| [`baseline.md`](baseline.md) | воспроизводимый снимок до первого изменения кода | новый snapshot перед каждой крупной фазой, старые цифры не переписываются |
| [`work-log.md`](work-log.md) | append-only журнал фактически выполненных действий | после каждого завершённого work package |
| [`open-issues.md`](open-issues.md) | открытые вопросы и реальные блокеры | при появлении, изменении статуса или разрешении вопроса |
| [`decisions.md`](decisions.md) | ADR-lite журнал принятых и предложенных решений | решение не удаляется; изменение оформляется новой записью или supersedes |
| [`risk-register.md`](risk-register.md) | риски, триггеры и меры защиты | на каждом phase gate |
| [`verification-matrix.md`](verification-matrix.md) | требование → тест → evidence → gate | вместе с контрактом и тестами каждой фазы |
| [`annotation-review-2026-09-23.md`](annotation-review-2026-09-23.md) | разбор пользовательских пометок и evidence gaps | historical review; дальнейшие решения в `decisions.md` |
| [`event-contract-v1.md`](event-contract-v1.md) | exact read-only event schema, projection и layout evidence | versioned contract; production write gated by B-003 |
| [`transaction-prototype.md`](transaction-prototype.md) | результаты изолированных crash/recovery tests и integration gaps | WP1.3a prototype; production path не подключён |
| [`reader-audit.md`](reader-audit.md) | аудит согласованного чтения и legacy writers после event integration | при изменении reader/write path |
| [`rehearsal-2026-09-24.md`](rehearsal-2026-09-24.md) | WP1.3 fault/recovery rehearsal на копии текущих данных | новый отчёт перед cutover |

## Статус программы

| Фаза | Статус | Следующий gate |
|---|---|---|
| Phase 0 — planning and baseline | Gate 0 passed | D-012, baseline и synthetic scenarios |
| Phase 1 — application event ledger | WP1.1–WP1.2 verified; WP1.3 transaction boundary verified on current-data copy | WP1.4 public command contract |
| Phase 2 — application packet manifest | planned | Gate 2: packet воспроизводим и проверяем |
| Phase 3 — evidence-backed matching | planned | Gate 3: golden corpus подтверждает модель |
| Phase 4 — source health/freshness | planned | Gate 4: observation не меняет listing truth |
| Phase 5 — inbox reconciliation | deferred until events stabilize | Gate 5: только proposed events |
| Phase 6 — event analytics | deferred until real event history exists | Gate 6: метрики воспроизводимы |
| Phase 7 — contacts/outreach | deferred by D-011: сейчас нет contact data | новая инвентаризация и решение |
| Phase 8 — browser assistance/UI/DB | explicitly deferred | только после доказанной потребности |

## Governance

### Статусы решений

- `accepted` — часть утверждённого design baseline;
- `proposed` — рекомендация, ещё не контракт;
- `blocked` — решение невозможно принять без нового evidence или выбора;
- `rejected` — рассмотрено и сознательно не выбрано;
- `superseded` — заменено более новым решением.

### Статусы work package

- `planned` → `ready` → `in_progress` → `verified` → `complete`;
- `blocked` используется только с ID из `open-issues.md`;
- work package не становится `complete`, пока не пройдены его tests и phase gate.

### Правила изменения

1. Один work package — один логический commit, если разделение не требуется для
   безопасной migration.
2. Schema, validator и tests появляются до canonical migration.
3. Миграция не смешивается с unrelated refactor или UI.
4. Работа идёт на fixtures и временных копиях данных; текущие canonical CSV не
   меняются до отдельного cutover commit.
5. `codex/tracker-v3` — integration branch. Публичную ветку не force-push'ить.
6. Изменения `main` регулярно подтягиваются явными sync checkpoints, потому что
   обычные job operations продолжают менять canonical data.
7. Любое принятое решение получает ID в `decisions.md`; любой настоящий blocker
   — ID в `open-issues.md`.
8. Work log фиксирует факт, а не намерение. Планы остаются в implementation plan.
9. Current architecture обновляется только после реально завершённого cutover.

## Неподвижные границы

До отдельного решения v3 не включает:

- автоматический final Submit;
- автоматическое присвоение `applied`, `interviewing`, `offer`, `rejected`,
  `ghosted` или `withdrawn` по косвенному сигналу;
- миграцию canonical state в SQLite/Postgres;
- обязательный SPA;
- browser extension;
- прямой canonical write из inbox/source adapter;
- вывод `listing_status=closed` из отсутствия объявления в очередном sweep;
- копирование AGPL-кода из исследованных проектов.

## Следующий шаг

Внутренний event append проходит через общий crash-safe publisher;
production events не создавались. Reader/legacy-writer audit, fault matrix и
rehearsal на копии текущего dataset выполнены. Connector staging включает
event JSONL; event + immutable result проверены в одном journal. Следующий
срез — WP1.4 public CLI/connector command contract и CI allowlist. B-005
остаётся gate для historical backfill. Разбор исходных
пометок — в [`annotation-review-2026-09-23.md`](annotation-review-2026-09-23.md).
