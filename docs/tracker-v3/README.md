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

## Статус программы

| Фаза | Статус | Следующий gate |
|---|---|---|
| Phase 0 — planning and baseline | active | принять ключевые решения D-003–D-008 |
| Phase 1 — application event ledger | blocked by design decisions | Gate 1: events + snapshot согласованы |
| Phase 2 — application packet manifest | planned | Gate 2: packet воспроизводим и проверяем |
| Phase 3 — evidence-backed matching | planned | Gate 3: golden corpus подтверждает модель |
| Phase 4 — source health/freshness | planned | Gate 4: observation не меняет listing truth |
| Phase 5 — inbox reconciliation | deferred until events stabilize | Gate 5: только proposed events |
| Phase 6 — event analytics | deferred until real event history exists | Gate 6: метрики воспроизводимы |
| Phase 7 — contacts/outreach | needs demonstrated data density | отдельное решение |
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

## Первый следующий шаг

Не начинать код Phase 1, пока не разрешены B-001–B-005 и не приняты D-003–D-005.
Первый implementation slice должен содержать только event contract, fixtures и
validator; dual-write и migration идут следующими отдельными work packages.
